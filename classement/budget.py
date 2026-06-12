"""Simulation budgétaire : à partir d'un budget et des classements, déterminer qui
peut bénéficier cette année et chiffrer le coût total et ses composantes.

Ordre de financement : priorité au rang dans son groupe de classement (tous groupes
confondus : tous les rangs 1, puis les rangs 2…), départage par score décroissant.
Coupure stricte : dès qu'un dossier ne tient pas dans le budget restant, lui et tous
les suivants sont marqués non finançables (le rang prime — pas de saut vers un
dossier moins cher) ; le reliquat est affiché et laissé à l'arbitrage de la commission.
"""

from __future__ import annotations

from classement.costs import candidate_cost
from classement.models import RankedCandidate, ScoreBreakdown


def simulate_budget(
    candidates: list[dict],
    groups: dict[tuple, list[RankedCandidate]],
    grid: dict,
    costs: dict,
    budget: float,
    plafond_billet: float | None = None,
) -> dict:
    by_id = {str(c.get("id")): c for c in candidates}

    # ordre de financement : (rang, -score), puis nom de groupe pour la stabilité
    order: list[tuple[tuple, RankedCandidate]] = []
    for key, ranked in groups.items():
        order.extend((key, entry) for entry in ranked)
    order.sort(key=lambda pair: (pair[1].rank, -pair[1].total, str(pair[0])))

    lignes: list[dict] = []
    reste = float(budget)
    coupure_atteinte = False
    totaux = {"indemnites": 0.0, "billets": 0.0, "frais_divers": 0.0,
              "demande": 0.0, "finance": 0.0}
    par_population: dict[str, dict] = {}

    for key, entry in order:
        candidate = by_id.get(entry.candidate_id, {})
        cost = candidate_cost(candidate, grid, costs, plafond_billet)
        total = cost["total"]
        totaux["demande"] += total

        if not coupure_atteinte and total <= reste:
            statut = "financé"
            reste -= total
            totaux["finance"] += total
            totaux["indemnites"] += cost["indemnite"]
            totaux["billets"] += cost["billet_retenu"]
            totaux["frais_divers"] += cost["frais_divers"]
        else:
            if not coupure_atteinte:
                coupure_atteinte = True
            statut = "non finançable"

        population = candidate.get("population") or "?"
        pop = par_population.setdefault(
            population, {"demande": 0.0, "finance": 0.0, "candidats": 0, "finances": 0}
        )
        pop["demande"] += total
        pop["candidats"] += 1
        if statut == "financé":
            pop["finance"] += total
            pop["finances"] += 1

        lignes.append({
            "groupe": list(key),
            "rang": entry.rank,
            "ex_aequo": entry.ex_aequo,
            "score": entry.total,
            **cost,
            "statut": statut,
            "budget_restant_apres": round(reste, 2) if statut == "financé" else None,
        })

    return {
        "grid_id": grid["id"],
        "budget": float(budget),
        "plafond_billet": plafond_billet,
        "lignes": lignes,
        "totaux": {k: round(v, 2) for k, v in totaux.items()},
        "reste": round(reste, 2),
        "tous_financables": not coupure_atteinte,
        "par_population": {
            k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}
            for k, v in par_population.items()
        },
    }


def simulate_exercice(
    campagnes: list[dict],
    budget: float,
    costs: dict,
    plafond_billet: float | None = None,
) -> dict:
    """Simulation de l'enveloppe d'un exercice sur plusieurs campagnes.

    `campagnes` : liste ordonnée par priorité de {"grid", "candidates", "groups"}.
    Chaque campagne consomme le reliquat de la précédente (art. 6 de l'arrêté 345 :
    l'établissement peut proposer une répartition selon ses besoins, en dérogation
    des quotas de l'art. 5). Le résultat inclut la répartition effective proposée.
    """
    reste = float(budget)
    resultats: list[dict] = []
    for campagne in campagnes:
        simulation = simulate_budget(
            campagne["candidates"], campagne["groups"], campagne["grid"],
            costs, reste, plafond_billet,
        )
        simulation["enveloppe_disponible"] = round(reste, 2)
        reste = simulation["reste"]
        resultats.append(simulation)

    repartition = []
    for simulation in resultats:
        finance = simulation["totaux"]["finance"]
        repartition.append({
            "grid_id": simulation["grid_id"],
            "demande": simulation["totaux"]["demande"],
            "finance": finance,
            "part_du_budget_pct": round(100 * finance / budget, 1) if budget else 0,
            "dossiers_finances": sum(1 for l in simulation["lignes"] if l["statut"] == "financé"),
            "dossiers": len(simulation["lignes"]),
        })

    return {
        "budget": float(budget),
        "plafond_billet": plafond_billet,
        "campagnes": resultats,
        "repartition_proposee": repartition,
        "reste": round(reste, 2),
    }


def render_budget_markdown(simulation: dict, institution: dict | None = None) -> str:
    out: list[str] = []
    if institution:
        out.append(f"# {institution.get('nom_fr', institution['id'])}")
        out.append("")
    out.append(f"## Simulation budgétaire — {simulation['grid_id']}")
    out.append("")
    out.append(f"Budget : **{simulation['budget']:,.0f} DA**"
               + (f" — plafond billet : {simulation['plafond_billet']:,.0f} DA"
                  if simulation.get("plafond_billet") else ""))
    out.append("")
    out.append("| Ordre | Groupe | Rang | Candidat | Pays (zone) | Jours | Indemnité | Billet retenu | Frais | Coût total | Statut |")
    out.append("|---:|---|---:|---|---|---:|---:|---:|---:|---:|---|")
    for i, ligne in enumerate(simulation["lignes"], start=1):
        groupe = " / ".join(map(str, ligne["groupe"][1:]))
        pays = f"{ligne['pays'] or '?'} ({ligne['zone'][-1]})"
        out.append(
            f"| {i} | {groupe} | {ligne['rang']} | {ligne['candidate_id']} | {pays} "
            f"| {ligne['duree_jours'] or '?'} | {ligne['indemnite']:,.0f} "
            f"| {ligne['billet_retenu']:,.0f} | {ligne['frais_divers']:,.0f} "
            f"| {ligne['total']:,.0f} | **{ligne['statut']}** |"
        )
    out.append("")
    t = simulation["totaux"]
    out.append("### Synthèse")
    out.append("")
    out.append(f"- Coût de **toutes** les demandes : {t['demande']:,.0f} DA"
               + (" — le budget couvre toutes les demandes ✔"
                  if simulation["tous_financables"] else ""))
    out.append(f"- Coût financé : {t['finance']:,.0f} DA "
               f"(indemnités {t['indemnites']:,.0f} + billets {t['billets']:,.0f} "
               f"+ frais divers {t['frais_divers']:,.0f})")
    out.append(f"- Reliquat budgétaire : **{simulation['reste']:,.0f} DA**")
    out.append("")
    out.append("| Population | Dossiers | Financés | Coût demandé | Coût financé |")
    out.append("|---|---:|---:|---:|---:|")
    for population, p in simulation["par_population"].items():
        out.append(f"| {population} | {p['candidats']} | {p['finances']} "
                   f"| {p['demande']:,.0f} | {p['finance']:,.0f} |")
    out.append("")
    warnings = [w for ligne in simulation["lignes"] for w in ligne.get("warnings", [])]
    if warnings:
        out.append("### Avertissements")
        out.append("")
        out.extend(f"- ⚠ {w}" for w in warnings)
    return "\n".join(out)


def render_exercice_markdown(exercice: dict, institution: dict | None = None) -> str:
    out: list[str] = []
    if institution:
        out.append(f"# {institution.get('nom_fr', institution['id'])}")
        out.append("")
    out.append("# Simulation de l'exercice budgétaire")
    out.append("")
    out.append(f"Enveloppe de l'exercice : **{exercice['budget']:,.0f} DA**"
               + (f" — plafond billet : {exercice['plafond_billet']:,.0f} DA"
                  if exercice.get("plafond_billet") else ""))
    out.append("")
    out.append("Les campagnes sont financées dans l'ordre de priorité ci-dessous ; chaque "
               "campagne consomme le reliquat de la précédente.")
    out.append("")

    for index, simulation in enumerate(exercice["campagnes"], start=1):
        out.append(f"---")
        out.append("")
        out.append(f"### Campagne {index} — {simulation['grid_id']} "
                   f"(enveloppe disponible : {simulation['enveloppe_disponible']:,.0f} DA)")
        out.append("")
        body = render_budget_markdown(simulation)
        # retire l'en-tête de la simulation unitaire (déjà contextualisé ici)
        lines = body.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("| Ordre"))
        out.extend(lines[start:])
        out.append("")

    out.append("---")
    out.append("")
    out.append("## Répartition proposée de l'enveloppe (art. 6)")
    out.append("")
    out.append("| Priorité | Campagne | Dossiers | Financés | Coût demandé | Coût financé | Part du budget |")
    out.append("|---:|---|---:|---:|---:|---:|---:|")
    for index, part in enumerate(exercice["repartition_proposee"], start=1):
        out.append(
            f"| {index} | {part['grid_id']} | {part['dossiers']} | {part['dossiers_finances']} "
            f"| {part['demande']:,.0f} | {part['finance']:,.0f} | {part['part_du_budget_pct']} % |"
        )
    out.append("")
    out.append(f"Reliquat final : **{exercice['reste']:,.0f} DA**")
    out.append("")
    out.append("> Répartition établie selon les besoins et demandes de l'établissement, en "
               "application de l'art. 6 de l'arrêté 345 (dérogation aux quotas de l'art. 5 : "
               "80 % perfectionnement enseignants/doctorants, 10 % PAT, 10 % "
               "résidences/manifestations).")
    return "\n".join(out)
