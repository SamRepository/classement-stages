"""Calcul des coûts de mobilité : indemnités réglementaires, billet plafonné, frais.

Barème : arrêté interministériel du 25/12/2011 (JORA n° 71, docs/journal71-1.pdf),
transcrit dans data/costs/indemnites.json et validé contre le tableau interne
« Nouveau » (voir tests/test_costs.py).

Données candidat attendues (clé "mobilite" du dossier) :
{
  "pays": "France",
  "duree_jours": 21,
  "type": "perfectionnement",        # optionnel — défaut : mobility_type de la grille
  "indemnite_da": 450000,            # informatif (export Odoo) — le moteur recalcule
  "billet_estime_da": 95000,
  "frais_divers_da": 30000           # visa, assurance voyage…
}
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

DEFAULT_COSTS_DIR = Path(__file__).resolve().parent.parent / "data" / "costs"


def load_costs(costs_dir: str | Path = DEFAULT_COSTS_DIR) -> dict:
    costs_dir = Path(costs_dir)
    with open(costs_dir / "indemnites.json", encoding="utf-8") as fh:
        costs = json.load(fh)
    with open(costs_dir / "zones.json", encoding="utf-8") as fh:
        costs["zones"] = json.load(fh)
    return costs


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


def zone_of(pays: str | None, costs: dict) -> tuple[str, bool]:
    """Retourne ('zone1'|'zone2', pays_connu). Pays inconnu ou absent → zone2."""
    if not pays:
        return "zone2", False
    zones = costs.get("zones", {})
    targets = {_norm(p) for p in zones.get("zone1", [])}
    aliases = {_norm(a): _norm(c) for a, c in zones.get("alias", {}).items()}
    key = _norm(pays)
    key = aliases.get(key, key)
    if key in targets:
        return "zone1", True
    return "zone2", True


def bareme_base(scale: dict, days: int) -> float:
    """Formule de l'annexe n° 1 (montants de base, hors majoration)."""
    if days <= 0:
        raise ValueError("La durée doit être d'au moins un jour.")
    if days <= 10:
        return scale["jour_1_10"] * days
    if days <= 29:
        return scale["jour_1_10"] * 10 + scale["supp_11_29"] * (days - 10)
    if days == 30:
        return scale["mois"]
    return scale["mois"] + scale["supp_apres_30"] * (days - 30)


def indemnite(
    costs: dict,
    mobility_type: str,
    zone: str,
    days: int,
    population: str | None = None,
) -> tuple[float, str]:
    """Indemnité réglementaire (montant, explication)."""
    base = bareme_base(costs["bareme_base"][zone], days)
    if mobility_type == "manifestation_scientifique":
        mult = float(costs["manifestation_scientifique"]["multiplicateur"])
        return base * mult, (
            f"manifestation : base {zone} {days} j = {base:,.0f} DA × {mult:g}"
        )
    majoration = costs.get("majoration_enseignants", {})
    if population in majoration.get("populations_majorees", []):
        taux = float(majoration.get("taux", 0))
        return base * (1 + taux), (
            f"stage : base {zone} {days} j = {base:,.0f} DA × {1 + taux:g} "
            f"(majoration enseignants/chercheurs)"
        )
    return base, f"stage : base {zone} {days} j = {base:,.0f} DA (barème de base)"


def candidate_cost(
    candidate: dict,
    grid: dict,
    costs: dict,
    plafond_billet: float | None = None,
) -> dict:
    """Coût total estimé d'un dossier : indemnité + billet retenu + frais divers."""
    m = candidate.get("mobilite", {}) or {}
    warnings: list[str] = []
    cid = candidate.get("id", "?")

    mobility_type = m.get("type")
    if not mobility_type:
        grid_type = grid.get("mobility_type")
        mobility_type = grid_type[0] if isinstance(grid_type, list) else grid_type
        if isinstance(grid_type, list):
            warnings.append(
                f"{cid} : type de mobilité non précisé, {mobility_type!r} retenu "
                f"(grille à types multiples)."
            )

    pays = m.get("pays")
    zone, known = zone_of(pays, costs)
    if not pays:
        warnings.append(f"{cid} : pays de destination non renseigné — Zone II appliquée.")

    days = m.get("duree_jours")
    montant_indemnite = 0.0
    detail = ""
    if days:
        montant_indemnite, detail = indemnite(
            costs, mobility_type, zone, int(days), candidate.get("population")
        )
    else:
        warnings.append(f"{cid} : durée non renseignée — indemnité non calculée.")

    billet_estime = float(m.get("billet_estime_da") or 0)
    billet_retenu = billet_estime
    if plafond_billet is not None and billet_estime > plafond_billet:
        billet_retenu = float(plafond_billet)
        warnings.append(
            f"{cid} : billet estimé {billet_estime:,.0f} DA plafonné à "
            f"{plafond_billet:,.0f} DA."
        )
    if not billet_estime:
        warnings.append(f"{cid} : billet d'avion non estimé.")

    frais_divers = float(m.get("frais_divers_da") or 0)

    return {
        "candidate_id": str(cid),
        "pays": pays,
        "zone": zone,
        "duree_jours": int(days) if days else None,
        "type_mobilite": mobility_type,
        "indemnite": round(montant_indemnite, 2),
        "indemnite_detail": detail,
        "billet_estime": billet_estime,
        "billet_retenu": billet_retenu,
        "frais_divers": frais_divers,
        "total": round(montant_indemnite + billet_retenu + frais_divers, 2),
        "warnings": warnings,
    }
