"""Structures de résultats du moteur de scoring."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreLine:
    """Score d'un critère de la grille pour un candidat."""

    criterion_id: str
    label: str
    points: float
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "label": self.label,
            "points": round(self.points, 4),
            "details": self.details,
            "warnings": self.warnings,
        }


@dataclass
class ScoreBreakdown:
    """Détail complet du score d'un candidat sur une grille."""

    candidate_id: str
    grid_id: str
    population: str | None
    lines: list[ScoreLine]
    total: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "grid_id": self.grid_id,
            "population": self.population,
            "total": round(self.total, 4),
            "lines": [line.to_dict() for line in self.lines],
            "warnings": self.warnings,
        }


@dataclass
class RankedCandidate:
    """Position d'un candidat dans le classement de son groupe."""

    candidate_id: str
    total: float
    rank: int
    ex_aequo: bool

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "total": round(self.total, 4),
            "rank": self.rank,
            "ex_aequo": self.ex_aequo,
        }
