"""Assemblage BDD → dict candidat et appels au moteur de classement.

Aucune logique réglementaire ici : uniquement de la transformation de format.
Les barèmes, plafonds, fenêtres et pénalités restent dans ``classement.engine``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from classement.engine import score_candidate
from classement.grids import find_grid, load_shared_rules
from classement.institutions import group_by_for, load_institution
from classement.models import RankedCandidate, ScoreBreakdown
from classement.ranking import rank_candidates
from webapp.models import Benefit, Campaign, Dossier, Entry

Mode = Literal["declare", "commission"]

# Types de critères saisis en une seule entrée (pas de lignes multiples).
SINGLE_ENTRY_TYPES = {"enum", "fixed", "capped", "manual_scores", "formula"}


@lru_cache
def get_grid(grid_id: str) -> dict:
    return find_grid(grid_id)


@lru_cache
def get_shared_rules() -> dict:
    return load_shared_rules()


@lru_cache
def get_institution(institution_id: str) -> dict:
    return load_institution(institution_id)


@dataclass
class AssembledCandidate:
    candidate: dict
    # Éléments rejetés par la commission, exclus du calcul mais jamais perdus :
    # [{entry_id, criterion_id, item_id, motif, decided_by, decided_at}]
    exclusions: list[dict] = field(default_factory=list)


def assemble_candidate(
    dossier: Dossier,
    entries: list[Entry],
    benefits: list[Benefit],
    grid: dict,
    *,
    mode: Mode,
) -> AssembledCandidate:
    """Reconstruit le dict candidat attendu par ``score_candidate``.

    - ``mode="declare"`` : tout ce qui est déclaré est compté (score provisoire
      affiché à l'enseignant) ;
    - ``mode="commission"`` : les éléments rejetés sont exclus du calcul et
      tracés dans ``exclusions`` (rejet motivé, art. 14-15) ; les éléments
      encore en attente restent comptés.
    """
    criteria = {c["id"]: c for c in grid.get("criteria", [])}
    exclusions: list[dict] = []
    kept: list[Entry] = []
    for entry in entries:
        if mode == "commission" and entry.statut == "rejete":
            exclusions.append(
                {
                    "entry_id": entry.id,
                    "criterion_id": entry.criterion_id,
                    "item_id": entry.item_id,
                    "motif": entry.decision_motif,
                    "decided_by": entry.decided_by,
                    "decided_at": entry.decided_at.isoformat() if entry.decided_at else None,
                }
            )
        else:
            kept.append(entry)

    candidate_entries: dict[str, dict] = {}
    for entry in kept:
        criterion = criteria.get(entry.criterion_id)
        if criterion is None:
            # Critère disparu de la grille : transmis tel quel, le moteur
            # produira l'avertissement « entrée sans critère correspondant ».
            candidate_entries.setdefault(entry.criterion_id, dict(entry.payload or {}))
            continue
        if criterion.get("type") in SINGLE_ENTRY_TYPES:
            candidate_entries[entry.criterion_id] = dict(entry.payload or {})
        else:  # count : une ligne BDD = un élément déclaré
            item = dict(entry.payload or {})
            item["item"] = entry.item_id
            candidate_entries.setdefault(entry.criterion_id, {"items": []})
            candidate_entries[entry.criterion_id].setdefault("items", []).append(item)

    user = dossier.user
    candidate = {
        "id": dossier.candidate_ref,
        "nom": user.nom,
        "prenom": user.prenom,
        "population": dossier.population,
        "grouping": {"departement": dossier.departement},
        "benefits": [
            {
                "date": b.date.isoformat(),
                "platform_close_date": (
                    b.platform_close_date.isoformat() if b.platform_close_date else None
                ),
            }
            for b in benefits
        ],
        "entries": candidate_entries,
    }
    mobilite = {
        "pays": dossier.pays,
        "duree_jours": dossier.duree_jours,
        "type": grid.get("mobility_type"),
        "billet_estime_da": dossier.billet_estime_da,
        "frais_divers_da": dossier.frais_divers_da,
    }
    if any(v is not None for v in mobilite.values()):
        candidate["mobilite"] = mobilite
    return AssembledCandidate(candidate=candidate, exclusions=exclusions)


def _assemble_from_db(db: Session, dossier: Dossier, *, mode: Mode) -> AssembledCandidate:
    grid = get_grid(dossier.campaign.grid_id)
    benefits = list(db.scalars(select(Benefit).where(Benefit.user_id == dossier.user_id)))
    return assemble_candidate(dossier, dossier.entries, benefits, grid, mode=mode)


def compute_score(
    db: Session, dossier: Dossier, *, mode: Mode
) -> tuple[ScoreBreakdown, list[dict]]:
    """Score d'un dossier (breakdown moteur + exclusions motivées)."""
    campaign = dossier.campaign
    assembled = _assemble_from_db(db, dossier, mode=mode)
    breakdown = score_candidate(
        get_grid(campaign.grid_id),
        assembled.candidate,
        get_shared_rules(),
        campaign.campaign_date,
        campaign.window_reference,
    )
    return breakdown, assembled.exclusions


@dataclass
class RankingResult:
    groups: dict[tuple, list[RankedCandidate]]
    breakdowns: list[ScoreBreakdown]
    candidates: list[dict]
    dossiers: list[Dossier]
    exclusions: dict[int, list[dict]]  # dossier_id → exclusions


def compute_ranking(
    db: Session,
    campaign: Campaign,
    *,
    mode: Mode = "commission",
    statuts: tuple[str, ...] = ("soumis", "gele"),
) -> RankingResult:
    """Classe les dossiers de la campagne (statuts soumis/gelé par défaut)."""
    grid = get_grid(campaign.grid_id)
    institution = get_institution(campaign.institution_id)
    dossiers = list(
        db.scalars(
            select(Dossier)
            .where(Dossier.campaign_id == campaign.id, Dossier.statut.in_(statuts))
            .order_by(Dossier.id)
        )
    )
    candidates: list[dict] = []
    breakdowns: list[ScoreBreakdown] = []
    exclusions: dict[int, list[dict]] = {}
    for dossier in dossiers:
        assembled = _assemble_from_db(db, dossier, mode=mode)
        breakdown = score_candidate(
            grid,
            assembled.candidate,
            get_shared_rules(),
            campaign.campaign_date,
            campaign.window_reference,
        )
        candidates.append(assembled.candidate)
        breakdowns.append(breakdown)
        exclusions[dossier.id] = assembled.exclusions

    # group_by appelable : retourne les noms de champs de regroupement du
    # candidat (résolus par ranking._group_key depuis candidate.grouping).
    def group_key(candidate: dict) -> list[str]:
        return group_by_for(institution, grid["id"], candidate.get("population"))

    groups = rank_candidates(candidates, breakdowns, group_by=group_key)
    return RankingResult(
        groups=groups,
        breakdowns=breakdowns,
        candidates=candidates,
        dossiers=dossiers,
        exclusions=exclusions,
    )
