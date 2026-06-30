"""Détection des quantités suspectes (confusion « nombre d'auteurs » ↔ quantité).

Beaucoup de candidats ont saisi le **nombre d'auteurs** dans le champ
« Quantité » au lieu de 1 (publications/communications), ce qui multiplie
l'élément et fait perdre la décote de position d'auteur. Ce script — en
**lecture seule**, il ne modifie aucune donnée — liste les éléments à vérifier
par la commission après clôture : toute entrée ``count_detail`` dont la quantité
est > 1.

Sévérité :
  - HAUTE  : critère avec position d'auteur (publications/communications) — la
             quantité devrait quasiment toujours valoir 1 (une ligne par
             publication). Une quantité > 1 y est presque toujours l'erreur.
  - moyenne : autre critère détaillé (encadrements, projets, cours…) — une
             quantité > 1 peut être légitime ; à confirmer sur justificatif.

Usage :
    python -m webapp.scripts.detecter_quantites                 # toutes les campagnes
    python -m webapp.scripts.detecter_quantites --campaign-id 3
    python -m webapp.scripts.detecter_quantites --inclure-brouillons
    python -m webapp.scripts.detecter_quantites --csv rapport.csv
"""

from __future__ import annotations

import argparse
import csv as _csv

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp import models  # noqa: F401 — enregistre les tables sur Base.metadata
from webapp.db import SessionLocal
from webapp.forms.grid_form import build_form_spec
from webapp.models import Campaign, Dossier, Entry, User
from webapp.services.scoring import grid_for_campaign

# Dossiers réellement en lice par défaut (le brouillon n'est pas évalué).
STATUTS_RETENUS = ("soumis", "gele")


def _count_detail_specs(grid: dict) -> dict[str, dict]:
    """criterion_id -> {label, has_position} pour les seuls critères détaillés."""
    return {
        spec["criterion_id"]: {"label": spec["label"], "has_position": spec.get("has_position", False)}
        for spec in build_form_spec(grid)
        if spec.get("widget") == "count_detail"
    }


def _suspects(db: Session, campaign: Campaign, *, inclure_brouillons: bool) -> list[dict]:
    specs = _count_detail_specs(grid_for_campaign(campaign))
    if not specs:
        return []

    stmt = (
        select(Entry, Dossier, User)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .join(User, Dossier.user_id == User.id)
        .where(Dossier.campaign_id == campaign.id)
        .where(Entry.criterion_id.in_(specs.keys()))
    )
    if not inclure_brouillons:
        stmt = stmt.where(Dossier.statut.in_(STATUTS_RETENUS))

    lignes: list[dict] = []
    for entry, dossier, user in db.execute(stmt).all():
        count = entry.payload.get("count", 1) or 1
        if count <= 1:
            continue
        spec = specs[entry.criterion_id]
        lignes.append(
            {
                "campaign_id": campaign.id,
                "grid_id": campaign.grid_id,
                "dossier_id": dossier.id,
                "candidat": f"{user.nom} {user.prenom}".strip(),
                "candidate_ref": dossier.candidate_ref,
                "statut_dossier": dossier.statut,
                "critere": spec["label"],
                "element": entry.item_id or entry.criterion_id,
                "quantite": count,
                "position_auteur": entry.payload.get("author_position", ""),
                "intitule": entry.payload.get("intitule", ""),
                "doi_url": entry.payload.get("doi") or entry.payload.get("url") or "",
                "statut_element": entry.statut,
                "severite": "HAUTE" if spec["has_position"] else "moyenne",
                "entry_id": entry.id,
            }
        )
    # Les plus graves d'abord, puis les plus grosses quantités.
    lignes.sort(key=lambda r: (r["severite"] != "HAUTE", -r["quantite"]))
    return lignes


def _print_rapport(lignes: list[dict]) -> None:
    if not lignes:
        print("Aucune quantité suspecte (> 1) détectée. ✓")
        return

    hautes = sum(1 for r in lignes if r["severite"] == "HAUTE")
    print(f"\n{len(lignes)} élément(s) à vérifier — dont {hautes} en sévérité HAUTE "
          f"(publications/communications).\n")

    par_dossier: dict[int, list[dict]] = {}
    for r in lignes:
        par_dossier.setdefault(r["dossier_id"], []).append(r)

    for dossier_id, rows in par_dossier.items():
        tete = rows[0]
        print(f"━━ {tete['candidat']} ({tete['candidate_ref']}) "
              f"— dossier {dossier_id} [{tete['statut_dossier']}]")
        for r in rows:
            marque = "‼️ " if r["severite"] == "HAUTE" else "•  "
            pos = f", position {r['position_auteur']}" if r["position_auteur"] != "" else ""
            ref = f"  réf={r['doi_url']}" if r["doi_url"] else ""
            intitule = f" « {r['intitule']} »" if r["intitule"] else ""
            print(f"   {marque}[{r['severite']}] {r['critere']} / {r['element']} : "
                  f"quantité = {r['quantite']}{pos}{intitule}"
                  f"  (entry {r['entry_id']}, élément {r['statut_element']}){ref}")
        print()


def _ecrire_csv(lignes: list[dict], chemin: str) -> None:
    champs = [
        "campaign_id", "grid_id", "dossier_id", "candidat", "candidate_ref",
        "statut_dossier", "severite", "critere", "element", "quantite",
        "position_auteur", "intitule", "doi_url", "statut_element", "entry_id",
    ]
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=champs)
        writer.writeheader()
        writer.writerows(lignes)
    print(f"\nRapport CSV écrit : {chemin}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Liste les quantités suspectes (confusion avec le nombre d'auteurs)."
    )
    parser.add_argument("--campaign-id", type=int, default=None,
                        help="Restreindre à une campagne (défaut : toutes).")
    parser.add_argument("--inclure-brouillons", action="store_true",
                        help="Inclure aussi les dossiers en brouillon (non soumis).")
    parser.add_argument("--csv", default=None, help="Chemin d'un export CSV.")
    args = parser.parse_args()

    with SessionLocal() as db:
        stmt = select(Campaign)
        if args.campaign_id is not None:
            stmt = stmt.where(Campaign.id == args.campaign_id)
        campaigns = list(db.scalars(stmt))
        if not campaigns:
            print("Aucune campagne trouvée.")
            return

        lignes: list[dict] = []
        for campaign in campaigns:
            lignes.extend(_suspects(db, campaign, inclure_brouillons=args.inclure_brouillons))

    _print_rapport(lignes)
    if args.csv:
        _ecrire_csv(lignes, args.csv)


if __name__ == "__main__":
    main()
