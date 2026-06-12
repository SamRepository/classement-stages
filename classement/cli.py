"""Interface en ligne de commande.

Exemples :
    python -m classement score --grid u1-manifestations-internationales \
        --candidates examples/candidats-u1.json --campaign-date 2026-06-30
    python -m classement score --grid u4-perfectionnement --institution enset-skikda \
        --candidates examples/enset/candidats-u4.json --format markdown --breakdown
    python -m classement places --institution enset-skikda --total 40
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from classement.engine import score_candidate
from classement.grids import DEFAULT_GRIDS_DIR, find_grid, load_grid, load_shared_rules
from classement.institutions import (
    DEFAULT_INSTITUTIONS_DIR,
    allocate_places,
    group_by_for,
    load_institution,
    validate_candidate,
)
from classement.ranking import rank_candidates


def _load_candidates(
    path: str, grid: dict | None = None, institution: dict | None = None
) -> tuple[list[dict], list[str]]:
    """Charge des candidats depuis un .json ou un classeur .xlsx (modèle de saisie)."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        from classement.excel_io import read_candidates

        if grid is None:
            raise ValueError("L'import Excel nécessite la grille (--grid).")
        return read_candidates(path, grid, institution)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("candidates", [])
    if not isinstance(data, list):
        raise ValueError("Le fichier candidats doit contenir une liste ou {candidates: [...]}.")
    return data, []


def _resolve_grid(spec: str, grids_dir: Path) -> dict:
    path = Path(spec)
    if path.suffix == ".json" and path.exists():
        return load_grid(path)
    return find_grid(spec, grids_dir)


def _render_json(
    groups: dict, breakdowns: list, include_breakdown: bool, institution: dict | None = None
) -> str:
    payload: dict = {}
    if institution:
        payload["institution"] = {
            "id": institution["id"],
            "nom_fr": institution.get("nom_fr"),
        }
    payload["rankings"] = [
        {
            "group": list(key),
            "candidates": [r.to_dict() for r in ranked],
        }
        for key, ranked in groups.items()
    ]
    if include_breakdown:
        payload["breakdowns"] = [b.to_dict() for b in breakdowns]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_markdown(
    groups: dict, breakdowns: list, include_breakdown: bool, institution: dict | None = None
) -> str:
    out: list[str] = []
    if institution:
        out.append(f"# {institution.get('nom_fr', institution['id'])}")
        out.append("")
    for key, ranked in groups.items():
        out.append(f"## Groupe : {' / '.join(map(str, key))}")
        out.append("")
        out.append("| Rang | Candidat | Score | Ex aequo |")
        out.append("|---:|---|---:|:--:|")
        for r in ranked:
            out.append(
                f"| {r.rank} | {r.candidate_id} | {r.total:g} | {'oui' if r.ex_aequo else ''} |"
            )
        out.append("")
    if include_breakdown:
        out.append("## Détail des scores")
        out.append("")
        for b in breakdowns:
            out.append(f"### {b.candidate_id} — total {b.total:g} pts")
            for line in b.lines:
                if not line.points and not line.warnings:
                    continue
                out.append(f"- **{line.label}** : {line.points:g} pts")
                for d in line.details:
                    out.append(f"  - {d}")
                for w in line.warnings:
                    out.append(f"  - ⚠ {w}")
            for w in b.warnings:
                out.append(f"- ⚠ {w}")
            out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="classement",
        description="Classement des candidats à la mobilité (arrêté 345/2026).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="Scorer et classer un fichier de candidats.")
    score.add_argument("--grid", required=True, help="Id de grille ou chemin d'un JSON de grille.")
    score.add_argument("--candidates", required=True, help="Fichier JSON des candidats.")
    score.add_argument("--grids-dir", default=str(DEFAULT_GRIDS_DIR))
    score.add_argument(
        "--institution",
        default=None,
        help="Id d'un profil de data/institutions (ex. enset-skikda) ou chemin d'un JSON : "
        "valide les dossiers et applique les règles de classement du profil.",
    )
    score.add_argument("--institutions-dir", default=str(DEFAULT_INSTITUTIONS_DIR))
    score.add_argument("--campaign-date", default=None, help="Date de référence (AAAA-MM-JJ).")
    score.add_argument(
        "--reference-fenetre",
        choices=["cloture", "mobilite"],
        default="cloture",
        help="Repère de la fenêtre « après dernier bénéfice » retenu par la commission : "
        "cloture = clôture de plateforme du dernier bénéfice (défaut, repli sur la date "
        "de mobilité si non renseignée) ; mobilite = toujours la date de la mobilité.",
    )
    score.add_argument(
        "--group-by",
        default=None,
        help="Clés de candidate.grouping séparées par des virgules (ex. departement). "
        "Prioritaire sur les règles du profil d'établissement.",
    )
    score.add_argument("--format", choices=["json", "markdown"], default="json")
    score.add_argument("--breakdown", action="store_true", help="Inclure le détail par candidat.")
    score.add_argument("--out", default=None, help="Fichier de sortie (défaut : stdout).")
    score.add_argument("--export-pv", default=None, help="Exporter le PV de classement (.xlsx).")
    score.add_argument(
        "--export-fiches", default=None, help="Exporter les fiches d'évaluation individuelles (.xlsx)."
    )
    score.add_argument(
        "--export-html", default=None, help="Exporter PV + fiches en HTML imprimable (PDF via navigateur)."
    )

    places = sub.add_parser(
        "places", help="Répartir un total de places selon les quotas d'un établissement (art. 5)."
    )
    places.add_argument("--institution", required=True)
    places.add_argument("--institutions-dir", default=str(DEFAULT_INSTITUTIONS_DIR))
    places.add_argument("--total", required=True, type=int, help="Nombre total de places.")

    template = sub.add_parser(
        "template", help="Générer le modèle de saisie Excel d'une grille (.xlsx)."
    )
    template.add_argument("--grid", required=True, help="Id de grille ou chemin d'un JSON de grille.")
    template.add_argument("--grids-dir", default=str(DEFAULT_GRIDS_DIR))
    template.add_argument("--institution", default=None)
    template.add_argument("--institutions-dir", default=str(DEFAULT_INSTITUTIONS_DIR))
    template.add_argument("--out", required=True, help="Chemin du classeur à créer.")

    budget = sub.add_parser(
        "budget",
        help="Simulation budgétaire : qui peut bénéficier avec un budget donné (coûts "
        "indemnités/billets/frais selon l'arrêté du 25/12/2011).",
    )
    budget.add_argument("--grid", required=True)
    budget.add_argument("--candidates", required=True)
    budget.add_argument("--grids-dir", default=str(DEFAULT_GRIDS_DIR))
    budget.add_argument("--institution", default=None)
    budget.add_argument("--institutions-dir", default=str(DEFAULT_INSTITUTIONS_DIR))
    budget.add_argument("--campaign-date", default=None)
    budget.add_argument(
        "--reference-fenetre", choices=["cloture", "mobilite"], default="cloture",
        help="Repère de la fenêtre « après dernier bénéfice » (voir la commande score).",
    )
    budget.add_argument("--group-by", default=None)
    budget.add_argument("--budget", required=True, type=float, help="Enveloppe en DA.")
    budget.add_argument("--plafond-billet", type=float, default=None, help="Plafond billet (DA).")
    budget.add_argument("--format", choices=["json", "markdown"], default="markdown")
    budget.add_argument("--out", default=None)

    exercice = sub.add_parser(
        "exercice",
        help="Simulation de l'enveloppe d'un exercice sur plusieurs campagnes (art. 6 : "
        "répartition proposée selon les besoins, en dérogation des quotas de l'art. 5).",
    )
    exercice.add_argument(
        "--campagne",
        action="append",
        required=True,
        metavar="GRILLE=FICHIER",
        help="Campagne à financer (répétable). L'ordre des --campagne = ordre de priorité "
        "(mettre les prioritaires en premier, ex. perfectionnement/doctorants).",
    )
    exercice.add_argument("--grids-dir", default=str(DEFAULT_GRIDS_DIR))
    exercice.add_argument("--institution", default=None)
    exercice.add_argument("--institutions-dir", default=str(DEFAULT_INSTITUTIONS_DIR))
    exercice.add_argument("--campaign-date", default=None)
    exercice.add_argument(
        "--reference-fenetre", choices=["cloture", "mobilite"], default="cloture",
        help="Repère de la fenêtre « après dernier bénéfice » (voir la commande score).",
    )
    exercice.add_argument("--budget", required=True, type=float, help="Enveloppe de l'exercice (DA).")
    exercice.add_argument("--plafond-billet", type=float, default=None)
    exercice.add_argument("--format", choices=["json", "markdown"], default="markdown")
    exercice.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    if args.command == "exercice":
        from classement.budget import render_exercice_markdown, simulate_exercice
        from classement.costs import load_costs

        grids_dir = Path(args.grids_dir)
        shared = load_shared_rules(grids_dir)
        institution = (
            load_institution(args.institution, args.institutions_dir) if args.institution else None
        )
        campagnes = []
        for spec in args.campagne:
            if "=" not in spec:
                parser.error(f"--campagne attend GRILLE=FICHIER, reçu : {spec!r}")
            grid_spec, file_spec = spec.split("=", 1)
            grid = _resolve_grid(grid_spec.strip(), grids_dir)
            candidates, import_errors = _load_candidates(file_spec.strip(), grid, institution)
            for error in import_errors:
                print(f"  [{grid['id']}] {error}", file=sys.stderr)
            if institution:
                group_by = lambda c, g=grid: group_by_for(institution, g["id"], c.get("population"))  # noqa: E731
            else:
                group_by = None
            breakdowns = [
                score_candidate(grid, c, shared_rules=shared, campaign_date=args.campaign_date,
                            window_reference=args.reference_fenetre)
                for c in candidates
            ]
            groups = rank_candidates(candidates, breakdowns, group_by=group_by)
            campagnes.append({"grid": grid, "candidates": candidates, "groups": groups})

        resultat = simulate_exercice(campagnes, args.budget, load_costs(), args.plafond_billet)
        if args.format == "markdown":
            rendered = render_exercice_markdown(resultat, institution)
        else:
            rendered = json.dumps(resultat, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
            print(f"Simulation d'exercice écrite dans {args.out}")
        else:
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
            print(rendered)
        return 0

    if args.command == "template":
        from classement.excel_io import write_template

        grid = _resolve_grid(args.grid, Path(args.grids_dir))
        institution = (
            load_institution(args.institution, args.institutions_dir) if args.institution else None
        )
        write_template(args.out, grid, institution)
        print(f"Modèle de saisie écrit dans {args.out}")
        return 0

    if args.command == "places":
        institution = load_institution(args.institution, args.institutions_dir)
        allocation = allocate_places(args.total, institution)
        print(json.dumps({"institution": institution["id"], "total": args.total,
                          "allocation": allocation}, ensure_ascii=False, indent=2))
        return 0

    grids_dir = Path(args.grids_dir)
    grid = _resolve_grid(args.grid, grids_dir)
    shared = load_shared_rules(grids_dir)

    institution = None
    if args.institution:
        institution = load_institution(args.institution, args.institutions_dir)

    candidates, import_errors = _load_candidates(args.candidates, grid, institution)
    if import_errors:
        print(f"-- {len(import_errors)} erreur(s) d'import --", file=sys.stderr)
        for error in import_errors:
            print(f"  {error}", file=sys.stderr)

    if args.command == "budget":
        from classement.budget import render_budget_markdown, simulate_budget
        from classement.costs import load_costs

        if args.group_by:
            group_by = [g.strip() for g in args.group_by.split(",")]
        elif institution:
            group_by = lambda c: group_by_for(institution, grid["id"], c.get("population"))  # noqa: E731
        else:
            group_by = None
        breakdowns = [
            score_candidate(grid, c, shared_rules=shared, campaign_date=args.campaign_date,
                            window_reference=args.reference_fenetre)
            for c in candidates
        ]
        groups = rank_candidates(candidates, breakdowns, group_by=group_by)
        simulation = simulate_budget(
            candidates, groups, grid, load_costs(), args.budget, args.plafond_billet
        )
        if args.format == "markdown":
            rendered = render_budget_markdown(simulation, institution)
        else:
            rendered = json.dumps(simulation, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
            print(f"Simulation écrite dans {args.out}")
        else:
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
            print(rendered)
        return 0

    if args.group_by:
        group_by = [g.strip() for g in args.group_by.split(",")]
    elif institution:
        group_by = lambda c: group_by_for(institution, grid["id"], c.get("population"))  # noqa: E731
    else:
        group_by = None

    breakdowns = [
        score_candidate(grid, c, shared_rules=shared, campaign_date=args.campaign_date,
                            window_reference=args.reference_fenetre)
        for c in candidates
    ]
    if institution:
        for candidate, breakdown in zip(candidates, breakdowns):
            breakdown.warnings.extend(validate_candidate(institution, candidate, grid))
    groups = rank_candidates(candidates, breakdowns, group_by=group_by)

    if args.export_pv or args.export_fiches or args.export_html:
        from classement import exports

        if args.export_pv:
            exports.export_pv(args.export_pv, groups, candidates, grid, institution, args.campaign_date)
            print(f"PV de classement écrit dans {args.export_pv}")
        if args.export_fiches:
            exports.export_fiches(
                args.export_fiches, breakdowns, candidates, groups, grid, institution, args.campaign_date
            )
            print(f"Fiches d'évaluation écrites dans {args.export_fiches}")
        if args.export_html:
            exports.export_html(
                args.export_html, groups, breakdowns, candidates, grid, institution, args.campaign_date
            )
            print(f"Document HTML imprimable écrit dans {args.export_html}")

    if args.format == "markdown":
        rendered = _render_markdown(groups, breakdowns, args.breakdown, institution)
    else:
        rendered = _render_json(groups, breakdowns, args.breakdown, institution)

    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(f"Résultats écrits dans {args.out}")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
