"""Consolide les fiches de déclaration individuelles renvoyées par les candidats
en un dossier maître unique, prêt pour le classement.

Usage :
    python scripts/consolider_declarations.py --dir declarations
        [--grid u3-residences-scientifiques] [--out examples/enset/dossier-u3-consolide.xlsx]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from classement.excel_io import read_candidates, write_candidates
from classement.grids import find_grid
from classement.institutions import load_institution


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Répertoire des fiches renvoyées (.xlsx).")
    parser.add_argument("--grid", default="u3-residences-scientifiques")
    parser.add_argument("--institution", default="enset-skikda")
    parser.add_argument("--out", default=str(ROOT / "examples" / "enset" / "dossier-u3-consolide.xlsx"))
    args = parser.parse_args()

    grid = find_grid(args.grid)
    institution = load_institution(args.institution)

    merged: dict[str, dict] = {}
    total_errors = 0
    files = sorted(p for p in Path(args.dir).glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        print(f"Aucune fiche .xlsx trouvée dans {args.dir}")
        return 1

    for path in files:
        candidates, errors = read_candidates(path, grid, institution)
        for error in errors:
            print(f"  ⚠ [{path.name}] {error}")
        total_errors += len(errors)
        for candidate in candidates:
            cid = str(candidate.get("id", "?"))
            if cid in merged:
                print(f"  ⚠ [{path.name}] candidat {cid} en double — première fiche conservée.")
                continue
            merged[cid] = candidate

    write_candidates(args.out, grid, institution, list(merged.values()))
    print(f"{len(merged)} dossier(s) consolidé(s) depuis {len(files)} fiche(s) → {args.out}")
    if total_errors:
        print(f"{total_errors} erreur(s) de saisie à corriger dans les fiches concernées.")
    print("Étape suivante : python -m classement score / budget sur ce fichier.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
