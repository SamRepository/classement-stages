"""Moteur de classement des candidats à la mobilité (arrêté n° 345 du 09/03/2026)."""

from classement.engine import score_candidate
from classement.grids import load_grid, load_shared_rules, find_grid
from classement.institutions import (
    allocate_places,
    group_by_for,
    load_institution,
    validate_candidate,
)
from classement.models import ScoreBreakdown, ScoreLine
from classement.ranking import rank_candidates

__version__ = "0.2.0"

__all__ = [
    "score_candidate",
    "load_grid",
    "load_shared_rules",
    "find_grid",
    "rank_candidates",
    "load_institution",
    "validate_candidate",
    "group_by_for",
    "allocate_places",
    "ScoreBreakdown",
    "ScoreLine",
]
