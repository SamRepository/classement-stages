"""Moteur de scoring : évalue un dossier candidat contre une grille.

Format attendu du dossier candidat (JSON) :

{
  "id": "C001",
  "nom": "...", "prenom": "...",
  "population": "enseignant_chercheur",
  "grouping": {"departement": "Informatique", "faculte": "NTIC"},
  "benefits": [{"date": "2024-05-10", "platform_close_date": "2024-03-01"}],
  "entries": {
    "<criterion_id>": <entrée selon le type du critère>
  }
}

Entrées par type de critère :
- enum          : {"value": "mca", "option_bonus": true}
- fixed         : {"applies": true, "bonuses": [0, 1]}        (indices des bonus de la grille)
                  si le critère porte "is_cap": {"points": 0.5}
- capped        : {"points": 2}
- manual_scores : {"scores": {"assiduite": 3, "initiative": 2}}
- formula       : {} (n calculé depuis benefits) ou {"n": 1, "N": 4}
- count         : {"items": [{"item": "classe_a", "count": 2, "author_position": 1,
                              "date": "2025-06-01", "doi": "10.1000/xyz", "url": "https://…",
                              "leader_count": 1, "bonus_count": 1}]}

Pour les critères `count` :
- author_position déclenche la pondération si la règle author_position_weighting
  est active sur le critère (défaut : position 1 si absente, avec avertissement) ;
- date permet le filtrage `after_last_benefit` (entrée non datée : comptée avec
  avertissement) ;
- leader_count applique le bonus défini sur l'item (ex. +1/projet pour le porteur) ;
- bonus_count applique les bonus définis au niveau du critère (ex. +2 si support
  en anglais), autant de fois qu'indiqué ;
- doi/url sont reportés dans le détail de la fiche (vérification par la commission) ;
  leur absence sur un item marqué reference_recommended dans la grille (publications,
  communications indexées) produit un avertissement.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from classement.grids import author_weights
from classement.models import ScoreBreakdown, ScoreLine

_FORMULA_ALLOWED = re.compile(r"^[0-9nN\s()+*\-]+$")
_WINDOW_YEARS = re.compile(r"(\d)\s*ans")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _label(criterion: dict) -> str:
    return criterion.get("label_fr") or criterion.get("label_ar") or criterion["id"]


def _last_benefit_close_date(candidate: dict, window_reference: str = "cloture") -> date | None:
    """Repère de la fenêtre « après dernier bénéfice » de la dernière mobilité obtenue.

    Décision de la commission (window_reference) :
    - "cloture"  (défaut) : date de clôture de la plateforme si renseignée,
      repli sur la date de mobilité sinon ;
    - "mobilite" : toujours la date de la mobilité (les clôtures saisies sont ignorées).
    """
    if window_reference not in ("cloture", "mobilite"):
        raise ValueError(f"window_reference inconnu : {window_reference!r} (attendu : cloture, mobilite)")
    if window_reference == "cloture":
        explicit = candidate.get("last_benefit_platform_close_date")
        if explicit:
            return _parse_date(explicit)
    dates = [
        _parse_date(
            (b.get("platform_close_date") if window_reference == "cloture" else None)
            or b.get("date")
        )
        for b in candidate.get("benefits", [])
    ]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _benefits_in_window(candidate: dict, campaign_date: date, years: int) -> int:
    start = campaign_date - timedelta(days=round(365.25 * years))
    count = 0
    for benefit in candidate.get("benefits", []):
        d = _parse_date(benefit.get("date"))
        if d and start <= d <= campaign_date:
            count += 1
    return count


def _author_weight(position: int | None, weights: dict[int, float], plus: float) -> float:
    if position is None:
        return 1.0
    if position in weights:
        return weights[position]
    return plus


# ---------------------------------------------------------------------------
# Scoring par type de critère
# ---------------------------------------------------------------------------


def _score_enum(criterion: dict, entry: dict | None) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    if not entry or "value" not in entry:
        line.warnings.append("Aucune valeur fournie pour ce critère à choix unique.")
        return line
    option = next(
        (o for o in criterion.get("options", []) if o.get("value") == entry["value"]),
        None,
    )
    if option is None:
        line.warnings.append(f"Valeur inconnue : {entry['value']!r}.")
        return line
    line.points = float(option.get("points", 0))
    line.details.append(f"{entry['value']} : {line.points} pts")
    if entry.get("option_bonus"):
        bonus = option.get("bonus")
        if bonus:
            line.points += float(bonus["points"])
            line.details.append(
                f"Bonus ({bonus.get('condition_fr') or bonus.get('condition_ar', 'bonus')}) : "
                f"+{bonus['points']} pts"
            )
        else:
            line.warnings.append("option_bonus demandé mais l'option ne porte pas de bonus.")
    return line


def _score_fixed(criterion: dict, entry: dict | None) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    if not entry:
        return line
    base = float(criterion.get("points", 0))
    if criterion.get("is_cap"):
        value = float(entry.get("points", base if entry.get("applies") else 0))
        line.points = max(0.0, min(value, base))
        line.details.append(f"{line.points} pts (plafond {base})")
        return line
    if not entry.get("applies"):
        return line
    line.points = base
    line.details.append(f"Acquis : {base} pts")
    bonuses = criterion.get("bonuses", [])
    for index in entry.get("bonuses", []):
        if 0 <= index < len(bonuses):
            bonus = bonuses[index]
            line.points += float(bonus["points"])
            line.details.append(f"Bonus ({bonus.get('condition', '?')}) : +{bonus['points']} pts")
        else:
            line.warnings.append(f"Indice de bonus inconnu : {index}.")
    return line


def _score_capped(criterion: dict, entry: dict | None) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    cap = float(criterion.get("cap_points", 0))
    if not entry:
        return line
    value = float(entry.get("points", 0))
    line.points = max(0.0, min(value, cap))
    if value > cap:
        line.warnings.append(f"Valeur {value} plafonnée à {cap}.")
    line.details.append(f"{line.points} pts (plafond {cap})")
    return line


def _score_manual_scores(criterion: dict, entry: dict | None) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    if not entry:
        return line
    items = {i["id"]: i for i in criterion.get("items", [])}
    for item_id, value in entry.get("scores", {}).items():
        item = items.get(item_id)
        if item is None:
            line.warnings.append(f"Sous-critère inconnu : {item_id!r}.")
            continue
        cap = float(item.get("cap_points", 0))
        granted = max(0.0, min(float(value), cap))
        if float(value) > cap:
            line.warnings.append(f"{item_id} : {value} plafonné à {cap}.")
        line.points += granted
        line.details.append(f"{item_id} : {granted}/{cap}")
    return line


def _score_formula(
    criterion: dict,
    entry: dict | None,
    candidate: dict,
    campaign_date: date,
) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    entry = entry or {}
    formula = criterion.get("formula", "")
    if not _FORMULA_ALLOWED.match(formula):
        line.warnings.append(f"Formule non supportée : {formula!r}.")
        return line

    n = entry.get("n")
    if n is None:
        window = _WINDOW_YEARS.search(criterion["id"])
        if window:
            n = _benefits_in_window(candidate, campaign_date, int(window.group(1)))
            line.details.append(
                f"n = {n} bénéfice(s) sur les {window.group(1)} dernières années "
                f"(référence {campaign_date.isoformat()})"
            )
        else:
            line.warnings.append(
                "Impossible de déduire n (fenêtre non identifiable) : fournir entry.n."
            )
            return line
    else:
        line.details.append(f"n = {n} (fourni)")

    names: dict[str, float] = {"n": float(n)}
    if "N" in formula:
        big_n = entry.get("N")
        if big_n is None:
            line.warnings.append("La formule requiert N : fournir entry.N.")
            return line
        names["N"] = float(big_n)
        line.details.append(f"N = {big_n} (fourni)")

    result = float(eval(formula, {"__builtins__": {}}, names))  # noqa: S307 — motif validé par regex

    # rc6 : « 4-ن (max 03) », « 5-ن (max 04) » → plafond N-1.
    if "N" in names and criterion.get("formula") == "(N) - n":
        result = min(result, names["N"] - 1)
        result = max(result, 0.0)
        line.details.append(f"Plafond N-1 = {names['N'] - 1:g} appliqué")

    line.points = result
    line.details.append(f"{formula} = {result:g} pts")
    return line


def _score_count(
    criterion: dict,
    entry: dict | None,
    weights: dict[int, float],
    weight_5_plus: float,
    last_close: date | None,
) -> ScoreLine:
    line = ScoreLine(criterion["id"], _label(criterion), 0.0)
    if not entry:
        return line
    items_def = {i["id"]: i for i in criterion.get("items", [])}
    weighting_active = "author_position_weighting" in criterion.get("rules", [])
    window_filter = criterion.get("window") == "after_last_benefit" and last_close

    units: list[dict] = []  # une entrée par unité comptée
    bonus_points = 0.0

    for raw in entry.get("items", []):
        item_id = raw.get("item")
        item = items_def.get(item_id)
        if item is None:
            line.warnings.append(f"Item inconnu : {item_id!r}.")
            continue
        count = int(raw.get("count", 1))
        if count <= 0:
            continue

        if window_filter:
            d = _parse_date(raw.get("date"))
            if d is None:
                line.warnings.append(
                    f"{item_id} : entrée non datée, comptée sans vérification de la "
                    f"fenêtre 'après dernier bénéfice'."
                )
            elif d <= last_close:
                line.warnings.append(
                    f"{item_id} : antérieur au {last_close.isoformat()}, ignoré."
                )
                continue

        weight = 1.0
        if weighting_active:
            position = raw.get("author_position")
            if position is None:
                line.warnings.append(
                    f"{item_id} : position d'auteur absente, pondération 100 % appliquée."
                )
            weight = _author_weight(position, weights, weight_5_plus)

        # référence (DOI/URL) pour la vérification par la commission
        reference = " — ".join(
            str(raw[k]).strip() for k in ("doi", "url") if raw.get(k) and str(raw[k]).strip()
        )
        if reference:
            line.details.append(f"{item_id} : réf. {reference}")
        elif item.get("reference_recommended"):
            line.warnings.append(
                f"{item_id} : DOI/URL non fourni (recommandé pour la vérification)."
            )

        pts = float(item.get("points_per_unit", 0)) * weight
        units.extend(
            {"item": item_id, "scope": item.get("scope"), "pts": pts} for _ in range(count)
        )

        if item.get("bonus") and raw.get("leader_count"):
            k = min(int(raw["leader_count"]), count)
            extra = float(item["bonus"]["points"]) * k
            bonus_points += extra
            line.details.append(f"{item_id} : bonus porteur ×{k} = +{extra:g} pts")

        if raw.get("bonus_count") and criterion.get("bonuses"):
            k = int(raw["bonus_count"])
            extra = sum(float(b["points"]) for b in criterion["bonuses"]) * k
            bonus_points += extra
            line.details.append(f"{item_id} : bonus de critère ×{k} = +{extra:g} pts")

    units = _apply_unit_caps(units, items_def, line)
    units = _apply_shared_caps(units, criterion, items_def, line)
    units = _apply_block_unit_caps(units, criterion, line)

    per_item: dict[str, float] = {}
    for unit in units:
        per_item[unit["item"]] = per_item.get(unit["item"], 0.0) + unit["pts"]
    for item_id, pts in list(per_item.items()):
        cap = items_def[item_id].get("cap_points")
        if cap is not None and pts > cap:
            per_item[item_id] = float(cap)
            line.warnings.append(f"{item_id} : {pts:g} pts plafonnés à {cap}.")

    total = sum(per_item.values())
    total = _apply_block_point_caps(total, per_item, criterion, items_def, line)

    for item_id, pts in per_item.items():
        if pts:
            line.details.append(f"{item_id} : {pts:g} pts")

    line.points = total + bonus_points
    return line


def _apply_unit_caps(units: list[dict], items_def: dict, line: ScoreLine) -> list[dict]:
    """Plafond `cap_units` par item : on garde les unités les mieux valorisées."""
    kept: list[dict] = []
    by_item: dict[str, list[dict]] = {}
    for unit in units:
        by_item.setdefault(unit["item"], []).append(unit)
    for item_id, item_units in by_item.items():
        cap = items_def[item_id].get("cap_units")
        if cap is not None and len(item_units) > cap:
            item_units.sort(key=lambda u: u["pts"], reverse=True)
            line.warnings.append(
                f"{item_id} : {len(item_units)} unités, plafonné à {cap} (les mieux "
                f"valorisées sont retenues)."
            )
            item_units = item_units[:cap]
        kept.extend(item_units)
    return kept


def _apply_shared_caps(
    units: list[dict], criterion: dict, items_def: dict, line: ScoreLine
) -> list[dict]:
    """Plafonds partagés entre items (`shared_cap` / `shared_caps`)."""
    shared = criterion.get("shared_caps", {})
    if not shared:
        return units
    result = [u for u in units if not items_def[u["item"]].get("shared_cap")]
    for cap_id, cap_def in shared.items():
        members = [u for u in units if items_def[u["item"]].get("shared_cap") == cap_id]
        cap = cap_def.get("cap_units")
        if cap is not None and len(members) > cap:
            members.sort(key=lambda u: u["pts"], reverse=True)
            line.warnings.append(
                f"Plafond partagé {cap_id} : {len(members)} unités, plafonné à {cap}."
            )
            members = members[:cap]
        result.extend(members)
    return result


def _apply_block_unit_caps(units: list[dict], criterion: dict, line: ScoreLine) -> list[dict]:
    """Plafonds de bloc en unités (`block_caps[].cap_units`), filtrés par scope."""
    for block in criterion.get("block_caps", []):
        cap = block.get("cap_units")
        if cap is None:
            continue
        scope = block.get("scope")
        in_scope = [u for u in units if scope is None or u["scope"] == scope]
        if len(in_scope) <= cap:
            continue
        in_scope.sort(key=lambda u: u["pts"], reverse=True)
        keep = set(map(id, in_scope[:cap]))
        line.warnings.append(
            f"Bloc {scope or 'global'} : {len(in_scope)} unités, plafonné à {cap}."
        )
        units = [
            u for u in units if (scope is not None and u["scope"] != scope) or id(u) in keep
        ]
    return units


def _apply_block_point_caps(
    total: float, per_item: dict, criterion: dict, items_def: dict, line: ScoreLine
) -> float:
    """Plafonds de bloc en points (`block_caps[].cap_points`), ex. 70 pts publications."""
    for block in criterion.get("block_caps", []):
        cap = block.get("cap_points")
        if cap is None:
            continue
        scope = block.get("scope")
        subtotal = sum(
            pts
            for item_id, pts in per_item.items()
            if scope is None or items_def[item_id].get("scope") == scope
        )
        if subtotal > cap:
            line.warnings.append(
                f"Bloc {scope or 'global'} : {subtotal:g} pts plafonnés à {cap}."
            )
            total -= subtotal - cap
    return total


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def score_candidate(
    grid: dict,
    candidate: dict,
    shared_rules: dict | None = None,
    campaign_date: date | str | None = None,
    window_reference: str = "cloture",
) -> ScoreBreakdown:
    """Calcule le score détaillé d'un candidat sur une grille.

    `window_reference` : repère de la fenêtre « après dernier bénéfice » retenu par
    la commission — "cloture" (clôture de plateforme, défaut) ou "mobilite" (date de
    la mobilité). Voir `_last_benefit_close_date`.
    """
    if isinstance(campaign_date, str):
        campaign_date = date.fromisoformat(campaign_date)
    campaign_date = campaign_date or date.today()

    weights, weight_5_plus = author_weights(shared_rules)
    last_close = _last_benefit_close_date(candidate, window_reference)
    entries = candidate.get("entries", {})

    breakdown = ScoreBreakdown(
        candidate_id=str(candidate.get("id", "?")),
        grid_id=grid["id"],
        population=candidate.get("population"),
        lines=[],
        total=0.0,
    )

    known_ids = set(grid["_criteria_by_id"])
    for entry_id in entries:
        if entry_id not in known_ids:
            breakdown.warnings.append(f"Entrée sans critère correspondant : {entry_id!r}.")

    population = candidate.get("population")
    if population and population not in grid.get("population", [population]):
        breakdown.warnings.append(
            f"Population {population!r} hors du champ de la grille {grid['id']}."
        )

    for criterion in grid["criteria"]:
        entry = entries.get(criterion["id"])
        ctype = criterion.get("type")
        if ctype == "enum":
            line = _score_enum(criterion, entry)
        elif ctype == "fixed":
            line = _score_fixed(criterion, entry)
        elif ctype == "capped":
            line = _score_capped(criterion, entry)
        elif ctype == "manual_scores":
            line = _score_manual_scores(criterion, entry)
        elif ctype == "formula":
            line = _score_formula(criterion, entry, candidate, campaign_date)
        elif ctype == "count":
            line = _score_count(criterion, entry, weights, weight_5_plus, last_close)
        else:
            line = ScoreLine(criterion["id"], _label(criterion), 0.0)
            line.warnings.append(f"Type de critère non supporté : {ctype!r}.")
        breakdown.lines.append(line)

    breakdown.total = sum(line.points for line in breakdown.lines)
    return breakdown
