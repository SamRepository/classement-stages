"""Profils d'établissements (data/institutions) : validation, règles de
classement et quotas propres à chaque établissement.

Un profil décrit les départements/facultés, les populations présentes, les
grilles applicables et les règles de regroupement du classement. Le moteur de
scoring reste générique ; toute la personnalisation passe par ces profils.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_INSTITUTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "institutions"


def load_institution(
    spec: str | Path, institutions_dir: str | Path = DEFAULT_INSTITUTIONS_DIR
) -> dict:
    """Charge un profil par id (data/institutions/<id>.json) ou par chemin."""
    path = Path(spec)
    if path.suffix == ".json" and path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    candidate = Path(institutions_dir) / f"{spec}.json"
    if candidate.exists():
        with open(candidate, encoding="utf-8") as fh:
            return json.load(fh)
    raise FileNotFoundError(f"Profil d'établissement '{spec}' introuvable dans {institutions_dir}")


def department_ids(institution: dict) -> set[str]:
    return {d["id"] for d in institution.get("departements", [])}


def department_label(institution: dict, dept_id: str) -> str:
    for dept in institution.get("departements", []):
        if dept["id"] == dept_id:
            return dept.get("label_fr", dept_id)
    return dept_id


def validate_candidate(institution: dict, candidate: dict, grid: dict) -> list[str]:
    """Contrôles de cohérence d'un dossier vis-à-vis du profil. Retourne des avertissements."""
    warnings: list[str] = []
    cid = candidate.get("id", "?")

    population = candidate.get("population")
    known_populations = institution.get("populations")
    if population and known_populations and population not in known_populations:
        warnings.append(
            f"[{institution['id']}] {cid} : population {population!r} inconnue de l'établissement."
        )

    grids_map = institution.get("grids", {})
    if grids_map:
        if grid["id"] not in grids_map:
            warnings.append(
                f"[{institution['id']}] {cid} : la grille {grid['id']!r} n'est pas applicable "
                f"à cet établissement."
            )
        elif population and population not in grids_map[grid["id"]]:
            warnings.append(
                f"[{institution['id']}] {cid} : population {population!r} hors du champ de la "
                f"grille {grid['id']!r} pour cet établissement."
            )

    dept = candidate.get("grouping", {}).get("departement")
    known_depts = department_ids(institution)
    if dept and known_depts and dept not in known_depts:
        warnings.append(
            f"[{institution['id']}] {cid} : département {dept!r} inconnu "
            f"(attendus : {', '.join(sorted(known_depts))})."
        )

    if institution.get("institution_type") and grid.get("institution_type"):
        if institution["institution_type"] != grid["institution_type"]:
            warnings.append(
                f"[{institution['id']}] {cid} : grille de type {grid['institution_type']!r} "
                f"pour un établissement de type {institution['institution_type']!r}."
            )

    return warnings


def group_by_for(institution: dict, grid_id: str, population: str | None) -> list[str]:
    """Clés de regroupement du classement : première règle qui matche."""
    for rule in institution.get("ranking_rules", []):
        if rule.get("grid") and rule["grid"] != grid_id:
            continue
        if rule.get("population") and rule["population"] != population:
            continue
        return list(rule.get("group_by", []))
    return []


def allocate_places(total: int, institution: dict) -> dict[str, int]:
    """Répartit un nombre total de places selon les quotas du profil
    (méthode du plus fort reste pour que la somme tombe juste)."""
    quotas: dict[str, float] = institution.get("quotas", {})
    if not quotas:
        return {}
    raw = {key: total * share for key, share in quotas.items()}
    floors = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(floors.values())
    by_fraction = sorted(raw, key=lambda k: raw[k] - floors[k], reverse=True)
    for key in by_fraction[:remainder]:
        floors[key] += 1
    return floors
