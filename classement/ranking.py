"""Classement des candidats par population et par groupe.

L'arrêté ne définit pas de critère de départage : les ex aequo partagent le même
rang (classement « compétition » : 1, 2, 2, 4) et sont signalés par `ex_aequo`.
"""

from __future__ import annotations

from typing import Callable

from classement.models import RankedCandidate, ScoreBreakdown


def _group_fields(candidate: dict, group_by) -> list[str]:
    if callable(group_by):
        return group_by(candidate) or []
    return list(group_by or [])


def _group_key(candidate: dict, breakdown: ScoreBreakdown, group_by) -> tuple:
    key: list = [breakdown.grid_id, candidate.get("population") or "?"]
    for field in _group_fields(candidate, group_by):
        key.append(str(candidate.get("grouping", {}).get(field, "?")))
    return tuple(key)


def rank_candidates(
    candidates: list[dict],
    breakdowns: list[ScoreBreakdown],
    group_by: list[str] | Callable[[dict], list[str]] | None = None,
) -> dict[tuple, list[RankedCandidate]]:
    """Classe les candidats au sein de chaque groupe (grille, population[, groupes]).

    `group_by` : liste des clés de `candidate.grouping` à utiliser, p. ex.
    ["departement"] pour le classement des doctorants au niveau du département
    (règle u4), ["faculte"] pour les cotutelles — ou un appelable
    `candidate -> list[str]` pour résoudre les clés candidat par candidat
    (règles de classement d'un profil d'établissement).
    """
    by_id = {b.candidate_id: b for b in breakdowns}
    groups: dict[tuple, list[tuple[dict, ScoreBreakdown]]] = {}
    for candidate in candidates:
        breakdown = by_id.get(str(candidate.get("id", "?")))
        if breakdown is None:
            continue
        key = _group_key(candidate, breakdown, group_by)
        groups.setdefault(key, []).append((candidate, breakdown))

    results: dict[tuple, list[RankedCandidate]] = {}
    for key, members in groups.items():
        members.sort(key=lambda pair: pair[1].total, reverse=True)
        totals = [b.total for _, b in members]
        ranked: list[RankedCandidate] = []
        for index, (_, breakdown) in enumerate(members):
            rank = totals.index(breakdown.total) + 1  # rang « compétition »
            ex_aequo = totals.count(breakdown.total) > 1
            ranked.append(
                RankedCandidate(
                    candidate_id=breakdown.candidate_id,
                    total=breakdown.total,
                    rank=rank,
                    ex_aequo=ex_aequo,
                )
            )
        results[key] = ranked
    return results
