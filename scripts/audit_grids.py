"""Audit des grilles : structure, libellés manquants et récapitulatif des critères.

Usage : python scripts/audit_grids.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "data" / "grids"


def main() -> int:
    issues: list[str] = []
    for path in sorted(GRIDS.glob("*.json")):
        if path.name == "shared-rules.json":
            continue
        with open(path, encoding="utf-8") as fh:
            grid = json.load(fh)
        gid = grid["id"]
        n_criteria = len(grid["criteria"])
        n_items = sum(len(c.get("items", [])) for c in grid["criteria"])
        n_options = sum(len(c.get("options", [])) for c in grid["criteria"])
        print(f"{gid:50s} criteres={n_criteria:3d} items={n_items:3d} options={n_options:2d}")

        for criterion in grid["criteria"]:
            cid = criterion["id"]
            if not criterion.get("label_fr"):
                issues.append(f"{gid} :: {cid} : label_fr manquant (critère)")
            if not criterion.get("label_ar"):
                issues.append(f"{gid} :: {cid} : label_ar manquant (critère)")
            for option in criterion.get("options", []):
                if not option.get("label_fr"):
                    issues.append(f"{gid} :: {cid}.{option['value']} : label_fr manquant (option)")
            if criterion.get("type") == "count":
                for item in criterion.get("items", []):
                    if not item.get("label_fr") and len(criterion["items"]) > 1:
                        issues.append(f"{gid} :: {cid}.{item['id']} : label_fr manquant (item)")
            if criterion.get("type") == "formula" and not criterion.get("formula"):
                issues.append(f"{gid} :: {cid} : formule manquante")

    print()
    if issues:
        print(f"{len(issues)} libellé(s)/champ(s) manquant(s) :")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("Aucun libellé manquant : toutes les grilles sont complètes et homogènes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
