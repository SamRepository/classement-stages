"""Chargement des grilles d'évaluation et des règles transverses (data/grids)."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_GRIDS_DIR = Path(__file__).resolve().parent.parent / "data" / "grids"

# Pondération par défaut si shared-rules.json est absent (annexes, note commune).
DEFAULT_AUTHOR_WEIGHTS = {1: 1.0, 2: 0.9, 3: 0.8, 4: 0.7}
DEFAULT_AUTHOR_WEIGHT_5_PLUS = 0.5


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_grid(path: str | Path) -> dict:
    """Charge une grille et indexe ses critères par id."""
    grid = _read_json(Path(path))
    if "id" not in grid or "criteria" not in grid:
        raise ValueError(f"Fichier de grille invalide (id/criteria manquants) : {path}")
    grid["_criteria_by_id"] = {c["id"]: c for c in grid["criteria"]}
    return grid


def load_shared_rules(grids_dir: str | Path = DEFAULT_GRIDS_DIR) -> dict:
    path = Path(grids_dir) / "shared-rules.json"
    if not path.exists():
        return {}
    return _read_json(path)


def find_grid(grid_id: str, grids_dir: str | Path = DEFAULT_GRIDS_DIR) -> dict:
    """Retrouve une grille par son champ `id` dans le répertoire des grilles."""
    grids_dir = Path(grids_dir)
    direct = grids_dir / f"{grid_id}.json"
    if direct.exists():
        return load_grid(direct)
    for path in grids_dir.glob("*.json"):
        if path.name == "shared-rules.json":
            continue
        grid = _read_json(path)
        if grid.get("id") == grid_id:
            grid["_criteria_by_id"] = {c["id"]: c for c in grid["criteria"]}
            return grid
    raise FileNotFoundError(f"Grille '{grid_id}' introuvable dans {grids_dir}")


def author_weights(shared_rules: dict | None) -> tuple[dict[int, float], float]:
    """Retourne (poids par position 1-4, poids 5 et plus)."""
    if shared_rules:
        raw = (
            shared_rules.get("rules", {})
            .get("author_position_weighting", {})
            .get("weights", {})
        )
        if raw:
            weights = {int(k): float(v) for k, v in raw.items() if k.isdigit()}
            plus = float(raw.get("5_et_plus", DEFAULT_AUTHOR_WEIGHT_5_PLUS))
            return weights, plus
    return dict(DEFAULT_AUTHOR_WEIGHTS), DEFAULT_AUTHOR_WEIGHT_5_PLUS
