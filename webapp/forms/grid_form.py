"""Génération de la spécification du formulaire de saisie depuis une grille JSON.

La grille reste la seule source de vérité : chaque critère devient une section,
le type détermine le widget. Contrairement au circuit Excel (où certains `count`
se réduisent à une colonne quantité), la saisie web est détaillée ligne par
ligne pour tout critère `count` — chaque élément déclaré porte son justificatif
PDF et sera validé/rejeté individuellement par la commission. Seuls les
critères marqués ``excel.saisie_simple`` (ex. citations Scopus) restent une
saisie agrégée (nombre + URL du profil).
"""

from __future__ import annotations


def _label(obj: dict) -> str:
    return obj.get("label_fr") or obj.get("label_ar") or obj.get("id", "?")


def build_form_spec(grid: dict) -> list[dict]:
    """Retourne une section par critère : {criterion_id, label, widget, ...}."""
    sections: list[dict] = []
    for criterion in grid.get("criteria", []):
        ctype = criterion.get("type")
        section = {
            "criterion_id": criterion["id"],
            "label": _label(criterion),
            "type": ctype,
        }
        if ctype == "enum":
            section["widget"] = "enum"
            section["options"] = [
                {
                    "value": o["value"],
                    "label": _label(o) if "label_fr" in o or "label_ar" in o else o["value"],
                    "points": o.get("points", 0),
                    "bonus_condition": (o.get("bonus") or {}).get("condition_fr"),
                    "bonus_points": (o.get("bonus") or {}).get("points"),
                }
                for o in criterion.get("options", [])
            ]
        elif ctype == "fixed":
            if criterion.get("is_cap"):
                section["widget"] = "fixed_cap"
                section["cap_points"] = criterion.get("points", 0)
            else:
                section["widget"] = "fixed"
                section["points"] = criterion.get("points", 0)
                section["bonuses"] = [
                    {"index": i, "condition": b.get("condition", "?"), "points": b.get("points", 0)}
                    for i, b in enumerate(criterion.get("bonuses", []))
                ]
        elif ctype == "capped":
            section["widget"] = "capped"
            section["cap_points"] = criterion.get("cap_points", 0)
        elif ctype == "manual_scores":
            section["widget"] = "manual"
            section["items"] = [
                {"id": i["id"], "label": _label(i), "cap_points": i.get("cap_points", 0)}
                for i in criterion.get("items", [])
            ]
        elif ctype == "formula":
            section["widget"] = "formula"
            section["formula"] = criterion.get("formula", "")
            section["variable"] = criterion.get("variable", "")
            section["needs_N"] = "N" in criterion.get("formula", "")
        elif ctype == "count":
            if criterion.get("excel", {}).get("saisie_simple"):
                item = criterion["items"][0]
                section["widget"] = "count_simple"
                section["item_id"] = item["id"]
                section["points_per_unit"] = item.get("points_per_unit", 0)
                section["url_profil"] = bool(criterion.get("excel", {}).get("url_profil"))
            else:
                section["widget"] = "count_detail"
                section["has_date"] = criterion.get("window") == "after_last_benefit"
                section["has_position"] = "author_position_weighting" in criterion.get("rules", [])
                section["bonuses"] = [
                    {"condition": b.get("condition", "?"), "points": b.get("points", 0)}
                    for b in criterion.get("bonuses", [])
                ]
                section["items"] = [
                    {
                        "id": i["id"],
                        "label": _label(i),
                        "points_per_unit": i.get("points_per_unit", 0),
                        "unit": i.get("unit", "unité"),
                        "cap_units": i.get("cap_units"),
                        "cap_points": i.get("cap_points"),
                        "reference_recommended": bool(i.get("reference_recommended")),
                        "leader_bonus": (i.get("bonus") or {}).get("points"),
                    }
                    for i in criterion.get("items", [])
                ]
                section["has_leader"] = any(i["leader_bonus"] for i in section["items"])
        else:
            section["widget"] = "inconnu"
        sections.append(section)
    return sections
