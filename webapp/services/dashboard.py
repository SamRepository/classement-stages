"""Tableau de bord commission : agrégats de la campagne courante.

Vue de pilotage commune au portail commission (membres relecteurs + responsable,
voir ``routes/commission.py``). Deux familles d'indicateurs, toutes recalculées à
la volée depuis la base (pas de snapshot) :

- **administratif** : avancement de la campagne (candidatures par statut, examen
  des éléments, recours) — de simples ``func.count``/GROUP BY, sans le moteur ;
- **scientifique** : volumétrie de la production (publications par classe,
  communications indexées, projets, encadrement, citations…). Les postes sont
  **dérivés de la grille** (``build_form_spec``) et non codés en dur : le tableau
  s'adapte donc à la grille de la campagne (u1–u4, rc5–rc9). Chaque poste porte
  deux nombres : ``declare`` (tout ce qui est saisi) et ``retenu`` (hors éléments
  rejetés par la commission) ; ils convergent à mesure que l'examen avance.

Le comptage de l'examen et de la production est limité aux dossiers **soumis ou
gelés** (ceux effectivement soumis à la commission) ; la participation, elle,
compte tous les dossiers, brouillons compris.
"""

from __future__ import annotations

import csv
import io
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.forms.grid_form import build_form_spec
from webapp.models import (
    DOSSIER_STATUTS,
    ENTRY_STATUTS,
    RECOURS_STATUTS,
    REVIEW_FLAGS,
    Dossier,
    ElementReview,
    Entry,
    Recours,
    User,
)
from webapp.services.scoring import grid_for_campaign

# Dossiers effectivement soumis à l'examen de la commission.
SUBMITTED = ("soumis", "gele")

# Types de critères « comptés » (quantités) exposés dans la vue scientifique.
COUNT_WIDGETS = ("count_detail", "count_simple")


def _entry_count(payload: dict | None) -> int:
    """Quantité portée par un élément compté (défaut 1 si absente/illisible)."""
    if not isinstance(payload, dict):
        return 1
    raw = payload.get("count", 1)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _dossiers_administratif(db: Session, campaign_id: int) -> dict:
    """Candidatures par statut (tous dossiers, brouillons compris) + total."""
    counts = {s: 0 for s in DOSSIER_STATUTS}
    rows = db.execute(
        select(Dossier.statut, func.count(Dossier.id))
        .where(Dossier.campaign_id == campaign_id)
        .group_by(Dossier.statut)
    ).all()
    for statut, n in rows:
        counts[statut] = n
    counts["total"] = sum(counts[s] for s in DOSSIER_STATUTS)
    return counts


def _examen(db: Session, campaign_id: int) -> dict:
    """Éléments des dossiers soumis/gelés, ventilés par statut d'examen."""
    counts = {s: 0 for s in ENTRY_STATUTS}
    rows = db.execute(
        select(Entry.statut, func.count(Entry.id))
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign_id, Dossier.statut.in_(SUBMITTED))
        .group_by(Entry.statut)
    ).all()
    for statut, n in rows:
        counts[statut] = n
    counts["total"] = sum(counts[s] for s in ENTRY_STATUTS)
    return counts


def _prets_a_geler(db: Session, campaign_id: int, nb_soumis: int) -> int:
    """Dossiers soumis dont tous les éléments sont décidés (0 en attente).

    Un dossier soumis sans élément en attente est prêt : le gel exige une revue
    exhaustive (art. 14-15). On soustrait ceux qui ont encore de l'en-attente.
    """
    avec_attente = db.execute(
        select(func.count(func.distinct(Entry.dossier_id)))
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(
            Dossier.campaign_id == campaign_id,
            Dossier.statut == "soumis",
            Entry.statut == "en_attente",
        )
    ).scalar_one()
    return nb_soumis - avec_attente


def _recours(db: Session, campaign_id: int) -> dict:
    """Recours de la campagne ventilés par statut + total et nombre d'ouverts."""
    counts = {s: 0 for s in RECOURS_STATUTS}
    rows = db.execute(
        select(Recours.statut, func.count(Recours.id))
        .join(Entry, Recours.entry_id == Entry.id)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign_id)
        .group_by(Recours.statut)
    ).all()
    for statut, n in rows:
        counts[statut] = n
    counts["total"] = sum(counts[s] for s in RECOURS_STATUTS)
    counts["ouverts"] = counts["ouvert"]
    return counts


def _avis(db: Session, campaign) -> dict:
    """Avis consultatifs des relecteurs, ventilés par conformité (+ total).

    Flags de ``ElementReview`` : ``ok`` = conforme, ``pas_ok`` = non conforme,
    ``explication`` = à expliquer. Comptés sur les dossiers soumis/gelés. Avis
    purement consultatifs (sans effet sur le score, cf. commission à deux niveaux).

    ``par_critere`` éclate les avis **actionnables** (non conformes + à expliquer)
    par critère de la grille, pour repérer où se concentrent les points d'attention.
    Seuls les critères concernés apparaissent, triés par nombre de signalements.
    """
    counts = {f: 0 for f in REVIEW_FLAGS}
    par_critere: dict[str, dict[str, int]] = {}
    rows = db.execute(
        select(Entry.criterion_id, ElementReview.flag, func.count(ElementReview.id))
        .join(Entry, ElementReview.entry_id == Entry.id)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign.id, Dossier.statut.in_(SUBMITTED))
        .group_by(Entry.criterion_id, ElementReview.flag)
    ).all()
    for criterion_id, flag, n in rows:
        counts[flag] += n
        if flag in ("pas_ok", "explication"):
            bucket = par_critere.setdefault(criterion_id, {"pas_ok": 0, "explication": 0})
            bucket[flag] += n
    counts["total"] = sum(counts[f] for f in REVIEW_FLAGS)

    labels = {
        c["id"]: c.get("label_fr") or c["id"]
        for c in grid_for_campaign(campaign).get("criteria", [])
    }
    detail = [
        {
            "criterion_id": criterion_id,
            "label": labels.get(criterion_id, criterion_id),
            "pas_ok": v["pas_ok"],
            "explication": v["explication"],
            "total": v["pas_ok"] + v["explication"],
        }
        for criterion_id, v in par_critere.items()
    ]
    detail.sort(key=lambda d: (-d["total"], d["label"]))
    counts["par_critere"] = detail
    return counts


def _scientifique(db: Session, campaign) -> list[dict]:
    """Volumétrie de la production, poste par poste, dérivée de la grille.

    Un poste = un critère « compté » de la grille ; ses lignes = les items du
    critère (ex. publications → classes A+/A/B/C). Chaque ligne porte ``declare``
    (tous les éléments saisis) et ``retenu`` (hors rejetés). Seuls les critères
    ayant au moins un élément déclaré sont affichés, pour ne pas noyer la vue.
    """
    # (criterion_id, item_id) → [declare, retenu]
    agg: dict[tuple[str, str | None], list[int]] = {}
    rows = db.execute(
        select(Entry.criterion_id, Entry.item_id, Entry.statut, Entry.payload)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign.id, Dossier.statut.in_(SUBMITTED))
    ).all()
    for criterion_id, item_id, statut, payload in rows:
        n = _entry_count(payload)
        bucket = agg.setdefault((criterion_id, item_id), [0, 0])
        bucket[0] += n
        if statut != "rejete":
            bucket[1] += n

    sections: list[dict] = []
    for spec in build_form_spec(grid_for_campaign(campaign)):
        if spec["widget"] not in COUNT_WIDGETS:
            continue
        if spec["widget"] == "count_simple":
            items = [{"id": spec["item_id"], "label": spec["label"]}]
        else:
            items = [{"id": i["id"], "label": i["label"]} for i in spec.get("items", [])]
        lignes = []
        for item in items:
            declare, retenu = agg.get((spec["criterion_id"], item["id"]), [0, 0])
            lignes.append({"label": item["label"], "declare": declare, "retenu": retenu})
        total_declare = sum(l["declare"] for l in lignes)
        if total_declare == 0:
            continue  # rien de déclaré sur ce critère : masqué
        sections.append(
            {
                "criterion_id": spec["criterion_id"],
                "label": spec["label"],
                "lignes": lignes,
                "single": len(lignes) == 1,
                "declare": total_declare,
                "retenu": sum(l["retenu"] for l in lignes),
            }
        )
    return sections


# Tranches des histogrammes de distribution par candidat (nb d'éléments retenus).
HIST_BUCKETS = ("0", "1", "2", "3", "4", "5+")


def _bucket(value: int) -> str:
    return str(value) if value < 5 else "5+"


def _candidate_rows(db: Session, campaign, criterion_ids: list[str]) -> list[dict]:
    """Production retenue par candidat (dossiers soumis/gelés), par critère.

    Une ligne par candidat : ``counts`` porte le nombre d'éléments **retenus**
    (hors rejetés) pour chaque critère scientifique, ``total`` leur somme. Les
    candidats sans production apparaissent avec des zéros (utile aux histogrammes).
    """
    dossiers = db.execute(
        select(Dossier.id, Dossier.candidate_ref, Dossier.population, User.nom, User.prenom)
        .join(User, Dossier.user_id == User.id)
        .where(Dossier.campaign_id == campaign.id, Dossier.statut.in_(SUBMITTED))
        .order_by(Dossier.id)
    ).all()
    rows = {
        d.id: {
            "ref": d.candidate_ref,
            "nom": f"{d.nom} {d.prenom}".strip(),
            "population": d.population,
            "counts": {cid: 0 for cid in criterion_ids},
            "total": 0,
        }
        for d in dossiers
    }
    wanted = set(criterion_ids)
    entries = db.execute(
        select(Entry.dossier_id, Entry.criterion_id, Entry.statut, Entry.payload)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign.id, Dossier.statut.in_(SUBMITTED))
    ).all()
    for dossier_id, criterion_id, statut, payload in entries:
        if criterion_id not in wanted or statut == "rejete":
            continue
        n = _entry_count(payload)
        rows[dossier_id]["counts"][criterion_id] += n
        rows[dossier_id]["total"] += n
    return list(rows.values())


def _histograms(candidate_rows: list[dict], sections: list[dict]) -> list[dict]:
    """Distribution des candidats par nombre d'éléments retenus, poste par poste."""
    hists = []
    for section in sections:
        cid = section["criterion_id"]
        buckets = {b: 0 for b in HIST_BUCKETS}
        for row in candidate_rows:
            buckets[_bucket(row["counts"][cid])] += 1
        hists.append(
            {
                "criterion_id": cid,
                "label": section["label"],
                "buckets": buckets,
                "max": max(buckets.values()),
            }
        )
    return hists


def _top_contributors(candidate_rows: list[dict], sections: list[dict],
                      limit: int = 10) -> list[dict]:
    """Candidats les plus productifs (total d'éléments retenus décroissant)."""
    labels = {s["criterion_id"]: s["label"] for s in sections}
    classes = sorted(
        (r for r in candidate_rows if r["total"] > 0),
        key=lambda r: (-r["total"], r["ref"]),
    )
    top = []
    for row in classes[:limit]:
        detail = [
            {"label": labels[cid], "count": n}
            for cid, n in row["counts"].items()
            if n > 0
        ]
        detail.sort(key=lambda d: -d["count"])
        top.append({**row, "detail": detail})
    return top


# Palette catégorielle validée (skill dataviz, mode clair), assignée dans l'ordre
# des slots — jamais cyclée. Au-delà de 7 pays, le reste est regroupé en « Autres »
# (8ᵉ slot), pour rester dans les couleurs validées et lisibles.
PIE_COLORS = (
    "#2a78d6", "#1baf7a", "#eda100", "#008300",
    "#4a3aa7", "#e34948", "#e87ba4", "#eb6834",
)
PIE_MAX_SLICES = 7


def _destinations(db: Session, campaign_id: int) -> dict:
    """Répartition des pays de destination (dossiers soumis/gelés) pour le camembert.

    Renvoie les parts prêtes à tracer (chemin SVG + couleur + pourcentage). Les
    pays au-delà des 7 premiers sont regroupés en « Autres ». Une seule
    destination → cercle plein (``full``) plutôt qu'un arc dégénéré.
    """
    rows = db.execute(
        select(Dossier.pays, func.count(Dossier.id))
        .where(
            Dossier.campaign_id == campaign_id,
            Dossier.statut.in_(SUBMITTED),
            Dossier.pays.isnot(None),
            Dossier.pays != "",
        )
        .group_by(Dossier.pays)
        .order_by(func.count(Dossier.id).desc(), Dossier.pays)
    ).all()
    total = sum(n for _, n in rows)
    if total == 0:
        return {"total": 0, "slices": [], "full": None}

    data = [(pays, n) for pays, n in rows]
    if len(data) > PIE_MAX_SLICES + 1:
        autres = sum(n for _, n in data[PIE_MAX_SLICES:])
        data = data[:PIE_MAX_SLICES] + [("Autres", autres)]

    if len(data) == 1:
        pays, n = data[0]
        return {
            "total": total,
            "full": {"pays": pays, "count": n, "color": PIE_COLORS[0]},
            "slices": [{"pays": pays, "count": n, "pct": 100.0, "color": PIE_COLORS[0]}],
        }

    cx = cy = 100.0
    r = 100.0
    angle = -math.pi / 2  # départ à 12 h
    slices = []
    for i, (pays, n) in enumerate(data):
        frac = n / total
        end = angle + frac * 2 * math.pi
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
        large = 1 if frac > 0.5 else 0
        path = (f"M{cx:.2f},{cy:.2f} L{x1:.2f},{y1:.2f} "
                f"A{r:.2f},{r:.2f} 0 {large} 1 {x2:.2f},{y2:.2f} Z")
        slices.append({
            "pays": pays, "count": n, "pct": round(frac * 100, 1),
            "color": PIE_COLORS[i], "path": path,
        })
        angle = end
    return {"total": total, "full": None, "slices": slices}


def _relecture(db: Session, campaign_id: int) -> dict:
    """Répartition et avancement de la relecture (réservé au responsable).

    Charge par membre (dossiers affectés + avis posés), dossiers soumis non
    affectés, et couverture globale des avis rapportée aux éléments à relire.
    """
    membres = list(
        db.scalars(
            select(User)
            .where(User.role == "commission", User.actif.is_(True))
            .order_by(User.nom, User.prenom)
        )
    )
    charge = dict(
        db.execute(
            select(Dossier.assigned_reviewer_id, func.count(Dossier.id))
            .where(Dossier.campaign_id == campaign_id)
            .group_by(Dossier.assigned_reviewer_id)
        ).all()
    )
    avis_par_membre = dict(
        db.execute(
            select(ElementReview.reviewer_id, func.count(ElementReview.id))
            .join(Entry, ElementReview.entry_id == Entry.id)
            .join(Dossier, Entry.dossier_id == Dossier.id)
            .where(Dossier.campaign_id == campaign_id)
            .group_by(ElementReview.reviewer_id)
        ).all()
    )
    lignes = [
        {
            "membre": m,
            "dossiers": charge.get(m.id, 0),
            "avis": avis_par_membre.get(m.id, 0),
        }
        for m in membres
    ]
    non_affectes = db.execute(
        select(func.count(Dossier.id)).where(
            Dossier.campaign_id == campaign_id,
            Dossier.statut.in_(SUBMITTED),
            Dossier.assigned_reviewer_id.is_(None),
        )
    ).scalar_one()
    avis_total = sum(avis_par_membre.values())
    elements_total = db.execute(
        select(func.count(Entry.id))
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign_id, Dossier.statut.in_(SUBMITTED))
    ).scalar_one()
    return {
        "lignes": lignes,
        "non_affectes": non_affectes,
        "avis_total": avis_total,
        "elements_total": elements_total,
    }


def dashboard_csv(db: Session, campaign) -> str:
    """Sérialise le tableau de bord en CSV (séparateur ``;``, pour Excel FR).

    Trois blocs : indicateurs administratifs, production scientifique par poste
    (déclaré / retenu), puis le détail par candidat (éléments retenus). Un BOM
    UTF-8 est ajouté à l'écriture de la réponse pour l'affichage des accents.
    """
    dossiers = _dossiers_administratif(db, campaign.id)
    examen = _examen(db, campaign.id)
    recours = _recours(db, campaign.id)
    avis = _avis(db, campaign)
    sections = _scientifique(db, campaign)
    criterion_ids = [s["criterion_id"] for s in sections]
    candidate_rows = _candidate_rows(db, campaign, criterion_ids)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Tableau de bord", campaign.grid_id, campaign.campaign_date.isoformat()])

    w.writerow([])
    w.writerow(["Indicateurs administratifs"])
    w.writerow(["Indicateur", "Valeur"])
    w.writerow(["Candidatures (total)", dossiers["total"]])
    w.writerow(["Candidatures soumises", dossiers["soumis"]])
    w.writerow(["Candidatures en brouillon", dossiers["brouillon"]])
    w.writerow(["Candidatures gelées", dossiers["gele"]])
    w.writerow(["Dossiers prêts à geler", _prets_a_geler(db, campaign.id, dossiers["soumis"])])
    w.writerow(["Éléments (total)", examen["total"]])
    w.writerow(["Éléments validés", examen["valide"]])
    w.writerow(["Éléments en attente", examen["en_attente"]])
    w.writerow(["Éléments rejetés", examen["rejete"]])
    w.writerow(["Recours (total)", recours["total"]])
    w.writerow(["Recours en attente", recours["ouvert"]])
    w.writerow(["Avis relecteurs (total)", avis["total"]])
    w.writerow(["Avis conformes", avis["ok"]])
    w.writerow(["Avis non conformes", avis["pas_ok"]])
    w.writerow(["Avis à expliquer", avis["explication"]])

    if avis["par_critere"]:
        w.writerow([])
        w.writerow(["Avis par critère (non conformes / à expliquer)"])
        w.writerow(["Critère", "Non conformes", "À expliquer", "Total"])
        for c in avis["par_critere"]:
            w.writerow([c["label"], c["pas_ok"], c["explication"], c["total"]])

    w.writerow([])
    w.writerow(["Production scientifique (dossiers soumis/gelés)"])
    w.writerow(["Critère", "Poste", "Déclaré", "Retenu"])
    for section in sections:
        if section["single"]:
            ligne = section["lignes"][0]
            w.writerow([section["label"], ligne["label"], ligne["declare"], ligne["retenu"]])
        else:
            for ligne in section["lignes"]:
                w.writerow([section["label"], ligne["label"], ligne["declare"], ligne["retenu"]])
            w.writerow([section["label"], "Total", section["declare"], section["retenu"]])

    w.writerow([])
    w.writerow(["Détail par candidat (éléments retenus)"])
    w.writerow(["Référence", "Candidat", "Population",
                *[s["label"] for s in sections], "Total"])
    for row in candidate_rows:
        w.writerow([
            row["ref"], row["nom"], row["population"],
            *[row["counts"][cid] for cid in criterion_ids], row["total"],
        ])
    return buf.getvalue()


def build_dashboard(db: Session, campaign) -> dict:
    """Assemble les indicateurs du tableau de bord pour la campagne.

    La section « relecture » (données d'organisation : noms des relecteurs,
    charges) est calculée systématiquement mais n'est affichée qu'au responsable
    (le gabarit la masque aux membres).
    """
    dossiers = _dossiers_administratif(db, campaign.id)
    sections = _scientifique(db, campaign)
    criterion_ids = [s["criterion_id"] for s in sections]
    candidate_rows = _candidate_rows(db, campaign, criterion_ids)
    return {
        "campaign": campaign,
        "grid": grid_for_campaign(campaign),
        "dossiers": dossiers,
        "prets_a_geler": _prets_a_geler(db, campaign.id, dossiers["soumis"]),
        "jamais_connectes": db.execute(
            select(func.count(User.id)).where(
                User.role == "enseignant",
                User.actif.is_(True),
                User.last_login_at.is_(None),
            )
        ).scalar_one(),
        "examen": _examen(db, campaign.id),
        "recours": _recours(db, campaign.id),
        "avis": _avis(db, campaign),
        "destinations": _destinations(db, campaign.id),
        "scientifique": sections,
        "histogrammes": _histograms(candidate_rows, sections),
        "top_contributeurs": _top_contributors(candidate_rows, sections),
        "relecture": _relecture(db, campaign.id),
    }
