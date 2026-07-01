"""Espace commission : relecture (membres) et décisions finales (responsable).

Deux niveaux :

- le **membre** (rôle ``commission``) relit les dossiers qui lui sont affectés et
  pose, pour chaque élément déclaré, un avis (flag ``ok`` / ``pas_ok`` /
  ``explication`` + observation). Cet avis est purement consultatif : il
  n'influe **jamais** sur le score ;
- le **responsable** (rôle ``responsable_commission``, ou ``admin``) répartit les
  dossiers entre les membres, puis prend la décision finale par élément
  (validation/rejet, motif obligatoire art. 14-15), gèle le classement et exporte.

Le score commission est recalculé par le moteur à chaque décision du responsable
(les éléments rejetés sont exclus, les en attente restent comptés).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from classement.budget import simulate_budget

from webapp.auth import require_role
from webapp.db import get_db
from webapp.forms.grid_form import build_form_spec
from webapp.models import REVIEW_FLAGS, Dossier, ElementReview, Entry, Recours, User
from webapp.services.dossier import get_campaign, log_event
from webapp.services.exports import export_response, freeze_campaign, pending_entries_count
from webapp.services.recours import (
    MOTIF_LABELS,
    STATUT_LABELS,
    close_recours_window,
    decide_recours,
    list_open_recours,
    open_recours_count,
    open_recours_window,
    recours_phase,
)
from webapp.services.scoring import compute_ranking, compute_score, get_costs, grid_for_campaign
from webapp.templating import templates

router = APIRouter(prefix="/commission")

# Lecture (liste, dossier, classement) : membres, responsable et admin.
LECTURE = Depends(require_role("commission", "responsable_commission", "admin"))
# Décisions, affectations, gel, budget, exports : responsable et admin seulement.
RESPONSABLE = Depends(require_role("responsable_commission", "admin"))


def _sections(dossier: Dossier, grid: dict) -> list[dict]:
    """Sections d'examen : spécification du critère + éléments déclarés."""
    rows_by_cid: dict[str, list[Entry]] = {}
    for entry in dossier.entries:
        rows_by_cid.setdefault(entry.criterion_id, []).append(entry)
    sections = []
    for spec in build_form_spec(grid):
        rows = rows_by_cid.get(spec["criterion_id"], [])
        # « manual » sans entrée : rien à examiner. « formula » est conservé même
        # vide, pour laisser le responsable forcer n (ex. bénéfices sur 3 ans).
        if not rows and spec["widget"] == "manual":
            continue
        labels = {i["id"]: i["label"] for i in spec.get("items", [])}
        sections.append({"spec": spec, "rows": rows, "labels": labels})
    return sections


def _render_score(request: Request, db: Session, dossier: Dossier, *, oob: bool) -> str:
    breakdown, exclusions = compute_score(db, dossier, mode="commission")
    pending = sum(1 for e in dossier.entries if e.statut == "en_attente")
    return templates.get_template("commission/fragments/score.html").render(
        request=request, breakdown=breakdown, exclusions=exclusions,
        dossier=dossier, pending=pending, oob=oob,
    )


def _is_responsable(user: User) -> bool:
    return user.role in ("responsable_commission", "admin")


def _decidable(dossier: Dossier) -> bool:
    """Le responsable peut décider : dossier soumis et classement non gelé."""
    return dossier.statut == "soumis" and dossier.campaign.statut != "gelee"


def _reviewable(dossier: Dossier, user: User) -> bool:
    """Le membre affecté peut émettre un avis (dossier soumis, non gelé).

    L'admin est autorisé pour les cas d'assistance/correction.
    """
    if dossier.statut != "soumis" or dossier.campaign.statut == "gelee":
        return False
    return user.id == dossier.assigned_reviewer_id or user.role == "admin"


def _review_of(entry: Entry, reviewer_id: int | None) -> ElementReview | None:
    if reviewer_id is None:
        return None
    return next((r for r in entry.reviews if r.reviewer_id == reviewer_id), None)


def _element_context(entry: Entry, user: User) -> dict:
    """Contexte d'affichage d'un élément selon le rôle du visiteur.

    - responsable/admin : contrôles de décision + avis du relecteur affecté ;
    - membre affecté : formulaire d'avis (flag + observation), pas de décision ;
    - autre membre : lecture seule de l'avis existant.
    """
    dossier = entry.dossier
    can_decide = _is_responsable(user) and _decidable(dossier)
    can_review = (
        user.role == "commission"
        and _reviewable(dossier, user)
        and user.id == dossier.assigned_reviewer_id
    )
    # Avis montré : celui que le membre édite, sinon celui du relecteur affecté
    # (pour éclairer le responsable et les autres lecteurs).
    review = _review_of(entry, user.id if can_review else dossier.assigned_reviewer_id)
    return {"can_decide": can_decide, "can_review": can_review, "review": review}


def _render_element(request: Request, db: Session, entry: Entry, user: User,
                    *, with_score: bool) -> HTMLResponse:
    grid = grid_for_campaign(entry.dossier.campaign)
    labels: dict[str, str] = {}
    is_formula = False
    is_count = False
    has_position = False
    for spec in build_form_spec(grid):
        if spec["criterion_id"] == entry.criterion_id:
            labels = {i["id"]: i["label"] for i in spec.get("items", [])}
            is_formula = spec["widget"] == "formula"
            is_count = spec["widget"] == "count_detail"
            has_position = spec.get("has_position", False)
            break
    html = templates.get_template("commission/fragments/element.html").render(
        request=request, e=entry, labels=labels, is_formula=is_formula,
        is_count=is_count, has_position=has_position,
        **_element_context(entry, user),
    )
    if with_score:
        html += _render_score(request, db, entry.dossier, oob=True)
    return HTMLResponse(html)


def _get_dossier(db: Session, dossier_id: int) -> Dossier:
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return dossier


def _membres(db: Session) -> list[User]:
    """Membres évaluateurs actifs (cibles d'affectation)."""
    return list(
        db.scalars(
            select(User)
            .where(User.role == "commission", User.actif.is_(True))
            .order_by(User.nom, User.prenom)
        )
    )


@router.get("/dossiers")
def liste_dossiers(
    request: Request,
    affectation: str = "tous",
    user: User = LECTURE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    # Un membre peut filtrer sur « mes dossiers » (ceux qui lui sont affectés).
    mes_dossiers = affectation == "moi"
    stmt = select(Dossier).where(Dossier.campaign_id == campaign.id)
    if mes_dossiers:
        stmt = stmt.where(Dossier.assigned_reviewer_id == user.id)
    dossiers = list(db.scalars(stmt.order_by(Dossier.id)))
    lignes = []
    for d in dossiers:
        compte = {"en_attente": 0, "valide": 0, "rejete": 0}
        avis = 0
        for e in d.entries:
            compte[e.statut] += 1
            if _review_of(e, d.assigned_reviewer_id) is not None:
                avis += 1
        score = None
        if d.statut in ("soumis", "gele"):
            breakdown, _ = compute_score(db, d, mode="commission")
            score = breakdown.total
        lignes.append({"dossier": d, "compte": compte, "score": score,
                       "avis": avis, "total": len(d.entries)})
    return templates.TemplateResponse(
        request,
        "commission/dossiers.html",
        {"user": user, "campaign": campaign, "lignes": lignes,
         "grid": grid_for_campaign(campaign),
         "is_responsable": _is_responsable(user),
         "membres": _membres(db) if _is_responsable(user) else [],
         "affectation": affectation},
    )


@router.get("/dossiers/{dossier_id}")
def vue_dossier(
    dossier_id: int,
    request: Request,
    user: User = LECTURE,
    db: Session = Depends(get_db),
):
    dossier = _get_dossier(db, dossier_id)
    grid = grid_for_campaign(dossier.campaign)
    breakdown, exclusions = compute_score(db, dossier, mode="commission")
    pending = sum(1 for e in dossier.entries if e.statut == "en_attente")
    can_review = (
        user.role == "commission"
        and _reviewable(dossier, user)
        and user.id == dossier.assigned_reviewer_id
    )
    # Synthèse des avis du relecteur affecté (pour le responsable).
    flag_counts = {f: 0 for f in REVIEW_FLAGS}
    for e in dossier.entries:
        r = _review_of(e, dossier.assigned_reviewer_id)
        if r is not None:
            flag_counts[r.flag] += 1
    return templates.TemplateResponse(
        request,
        "commission/dossier.html",
        {
            "user": user,
            "dossier": dossier,
            "grid": grid,
            "sections": _sections(dossier, grid),
            "breakdown": breakdown,
            "exclusions": exclusions,
            "pending": pending,
            "decidable": _decidable(dossier),
            "is_responsable": _is_responsable(user),
            "can_review": can_review,
            "flag_counts": flag_counts,
            "elem_ctx": {e.id: _element_context(e, user) for e in dossier.entries},
            "benefits": dossier.user.benefits,
        },
    )


@router.get("/dossiers/{dossier_id}/score")
def fragment_score(
    dossier_id: int,
    request: Request,
    user: User = LECTURE,
    db: Session = Depends(get_db),
):
    dossier = _get_dossier(db, dossier_id)
    return HTMLResponse(_render_score(request, db, dossier, oob=False))


@router.post("/entrees/{entry_id}/avis")
async def avis(
    entry_id: int,
    request: Request,
    user: User = LECTURE,
    db: Session = Depends(get_db),
):
    """Avis consultatif du membre affecté sur un élément (flag + observation).

    N'affecte jamais le score : aucun recalcul, pas de mise à jour OOB du total.
    """
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    dossier = entry.dossier
    if not (user.role == "commission" and user.id == dossier.assigned_reviewer_id
            and _reviewable(dossier, user)):
        raise HTTPException(
            status_code=403,
            detail="Avis impossible : dossier non affecté, non soumis ou classement gelé.",
        )
    form = await request.form()
    flag = form.get("flag")
    if flag not in REVIEW_FLAGS:
        raise HTTPException(status_code=422, detail=f"Avis inconnu : {flag!r}.")
    observation = (form.get("observation") or "").strip() or None
    review = _review_of(entry, user.id)
    if review is None:
        review = ElementReview(entry_id=entry.id, reviewer_id=user.id)
        db.add(review)
    review.flag = flag
    review.observation = observation
    log_event(db, user, "avis_membre", dossier,
              detail=f"entry={entry.id} {entry.criterion_id}/{entry.item_id or '-'} flag={flag}")
    db.commit()
    db.refresh(entry)
    return _render_element(request, db, entry, user, with_score=False)


@router.post("/entrees/{entry_id}/decision")
async def decision(
    entry_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    if not _decidable(entry.dossier):
        raise HTTPException(
            status_code=403,
            detail="Décision impossible : dossier non soumis ou classement gelé.",
        )
    form = await request.form()
    statut = form.get("statut")
    motif = (form.get("motif") or "").strip()
    if statut not in ("valide", "rejete", "en_attente"):
        raise HTTPException(status_code=422, detail=f"Décision inconnue : {statut!r}.")
    if statut == "rejete" and not motif:
        raise HTTPException(
            status_code=422,
            detail="Le rejet doit être motivé (art. 14-15 de l'arrêté).",
        )
    entry.statut = statut
    entry.decision_motif = motif if statut == "rejete" else None
    entry.decided_by = user.id if statut != "en_attente" else None
    entry.decided_at = datetime.now(timezone.utc) if statut != "en_attente" else None
    log_event(db, user, f"decision_{statut}", entry.dossier,
              detail=f"entry={entry.id} {entry.criterion_id}/{entry.item_id or '-'}"
                     + (f" motif={motif}" if motif else ""))
    db.commit()
    db.refresh(entry)
    return _render_element(request, db, entry, user, with_score=True)


@router.post("/entrees/{entry_id}/ajuster")
async def ajuster_formule(
    entry_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Ajuste la valeur n (et N) d'un critère formule, puis la valide.

    Sert au premier exercice : le candidat saisit n (faute d'historique Odoo),
    la commission le vérifie et le corrige. Champ vide => n supprimé => retour
    au calcul automatique depuis l'historique des bénéfices.
    """
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    if not _decidable(entry.dossier):
        raise HTTPException(
            status_code=403,
            detail="Ajustement impossible : dossier non soumis ou classement gelé.",
        )
    grid = grid_for_campaign(entry.dossier.campaign)
    criterion = next((c for c in grid.get("criteria", []) if c["id"] == entry.criterion_id), None)
    if criterion is None or criterion.get("type") != "formula":
        raise HTTPException(status_code=422, detail="Ce critère n'est pas une formule.")

    form = await request.form()
    payload = dict(entry.payload or {})

    def _int_field(name: str) -> int | None:
        raw = form.get(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{name} doit être un entier.")
        if value < 0:
            raise HTTPException(status_code=422, detail=f"{name} doit être ≥ 0.")
        return value

    n = _int_field("n")
    if n is None:
        payload.pop("n", None)
    else:
        payload["n"] = n
    if "N" in (criterion.get("formula") or ""):
        big_n = _int_field("N")
        if big_n is None:
            payload.pop("N", None)
        else:
            payload["N"] = big_n

    entry.payload = payload
    entry.statut = "valide"
    entry.decided_by = user.id
    entry.decided_at = datetime.now(timezone.utc)
    entry.decision_motif = None
    log_event(db, user, "ajustement_formule", entry.dossier,
              detail=f"entry={entry.id} {entry.criterion_id} n={payload.get('n', 'auto')}")
    db.commit()
    db.refresh(entry)
    return _render_element(request, db, entry, user, with_score=True)


@router.post("/entrees/{entry_id}/ajuster-quantite")
async def ajuster_quantite(
    entry_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Rectifie la quantité (et la position d'auteur) d'un élément détaillé.

    Corrige la confusion fréquente « nombre d'auteurs saisi dans la quantité » :
    le responsable remet la quantité réelle (en général 1 par publication) et,
    le cas échéant, la position d'auteur. Réservé au responsable (modifie le
    score, comme l'ajustement des formules). La rectification est tracée ;
    le statut de validation/rejet de l'élément n'est pas modifié ici.
    """
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Élément introuvable.")
    if not _decidable(entry.dossier):
        raise HTTPException(
            status_code=403,
            detail="Rectification impossible : dossier non soumis ou classement gelé.",
        )
    grid = grid_for_campaign(entry.dossier.campaign)
    spec = next(
        (s for s in build_form_spec(grid) if s["criterion_id"] == entry.criterion_id),
        None,
    )
    if spec is None or spec["widget"] != "count_detail":
        raise HTTPException(
            status_code=422,
            detail="Ce critère ne se saisit pas par éléments comptés.",
        )

    form = await request.form()
    payload = dict(entry.payload or {})
    ancienne_qte = payload.get("count", 1)

    raw_count = (form.get("quantite") or "").strip()
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="La quantité doit être un entier.")
    if count < 1:
        raise HTTPException(status_code=422, detail="La quantité doit être ≥ 1.")
    payload["count"] = count

    detail = f"entry={entry.id} {entry.criterion_id}/{entry.item_id or '-'} " \
             f"quantité {ancienne_qte}→{count}"
    if spec.get("has_position"):
        raw_pos = (form.get("author_position") or "").strip()
        ancienne_pos = payload.get("author_position")
        if raw_pos:
            try:
                position = int(raw_pos)
            except ValueError:
                raise HTTPException(status_code=422, detail="La position doit être un entier.")
            if position < 1:
                raise HTTPException(status_code=422, detail="La position doit être ≥ 1.")
            payload["author_position"] = position
        else:
            payload.pop("author_position", None)
        nouvelle_pos = payload.get("author_position")
        if nouvelle_pos != ancienne_pos:
            detail += f", position {ancienne_pos or '-'}→{nouvelle_pos or '-'}"

    entry.payload = payload
    log_event(db, user, "rectification_quantite", entry.dossier, detail=detail)
    db.commit()
    db.refresh(entry)
    return _render_element(request, db, entry, user, with_score=True)


@router.post("/dossiers/{dossier_id}/critere/{criterion_id}/valeur")
async def definir_valeur(
    dossier_id: int,
    criterion_id: str,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Renseigne/corrige un critère à choix (enum), ex. le rang scientifique.

    Utile quand le candidat a laissé le critère vide (« Rien de déclaré ») ou
    s'est trompé de rang. Réservé au responsable (modifie le score, comme les
    autres corrections). Crée l'entrée si absente, la met à jour, ou la supprime
    si « non renseigné » est choisi. L'élément créé reste « en attente » (compté
    au score) : le responsable peut le valider/rejeter ensuite comme les autres.
    """
    dossier = _get_dossier(db, dossier_id)
    if not _decidable(dossier):
        raise HTTPException(
            status_code=403,
            detail="Dossier non soumis ou classement gelé.",
        )
    grid = grid_for_campaign(dossier.campaign)
    spec = next(
        (s for s in build_form_spec(grid) if s["criterion_id"] == criterion_id),
        None,
    )
    if spec is None or spec["widget"] != "enum":
        raise HTTPException(status_code=422, detail="Ce critère n'est pas un critère à choix.")

    form = await request.form()
    value = (form.get("value") or "").strip()
    entry = next((e for e in dossier.entries if e.criterion_id == criterion_id), None)

    if not value:
        if entry is not None:
            db.delete(entry)
            log_event(db, user, "critere_efface", dossier, detail=criterion_id)
            db.commit()
        request.session["flash"] = f"{spec['label']} : valeur effacée."
        return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)

    if value not in {o["value"] for o in spec["options"]}:
        raise HTTPException(status_code=422, detail=f"Option inconnue : {value!r}.")
    payload: dict = {"value": value}
    if form.get("option_bonus"):
        payload["option_bonus"] = True

    if entry is None:
        entry = Entry(dossier_id=dossier.id, criterion_id=criterion_id, payload=payload)
        db.add(entry)
        action = "critere_defini"
    else:
        entry.payload = payload
        action = "critere_corrige"
    log_event(db, user, action, dossier, detail=f"{criterion_id}={value}")
    db.commit()
    request.session["flash"] = f"{spec['label']} enregistré : {value}."
    return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)


@router.post("/dossiers/{dossier_id}/critere/{criterion_id}/nombre")
async def definir_nombre(
    dossier_id: int,
    criterion_id: str,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Ajuste un critère à saisie simple (nombre + URL), ex. citations Scopus.

    Le responsable corrige le nombre déclaré (et l'URL du profil). Crée l'entrée
    si absente, la met à jour, ou l'efface si le nombre est vide/0. Réservé au
    responsable (modifie le score) ; l'élément reste « en attente » (compté),
    décidable ensuite ; action tracée.
    """
    dossier = _get_dossier(db, dossier_id)
    if not _decidable(dossier):
        raise HTTPException(status_code=403, detail="Dossier non soumis ou classement gelé.")
    grid = grid_for_campaign(dossier.campaign)
    spec = next(
        (s for s in build_form_spec(grid) if s["criterion_id"] == criterion_id),
        None,
    )
    if spec is None or spec["widget"] != "count_simple":
        raise HTTPException(status_code=422, detail="Ce critère n'est pas à saisie simple.")

    form = await request.form()
    raw = (form.get("count") or "").strip()
    count: int | None = None
    if raw:
        try:
            count = int(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="Nombre entier attendu.")
        if count < 0:
            raise HTTPException(status_code=422, detail="Le nombre doit être ≥ 0.")

    entry = next((e for e in dossier.entries if e.criterion_id == criterion_id), None)

    if not count:  # None (vide) ou 0 → effacer
        if entry is not None:
            db.delete(entry)
            log_event(db, user, "nombre_efface", dossier, detail=criterion_id)
            db.commit()
        request.session["flash"] = f"{spec['label']} : effacé."
        return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)

    payload: dict = {"count": count}
    url = (form.get("url") or "").strip()
    if url:
        payload["url"] = url

    if entry is None:
        entry = Entry(dossier_id=dossier.id, criterion_id=criterion_id,
                      item_id=spec["item_id"], payload=payload)
        db.add(entry)
        action = "nombre_defini"
    else:
        entry.payload = payload
        entry.item_id = spec["item_id"]
        action = "nombre_corrige"
    log_event(db, user, action, dossier, detail=f"{criterion_id}={count}")
    db.commit()
    request.session["flash"] = f"{spec['label']} : {count} enregistré."
    return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)


@router.post("/dossiers/{dossier_id}/formule/{criterion_id}")
async def definir_formule(
    dossier_id: int,
    criterion_id: str,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Force la valeur n (et N) d'un critère formule sans entrée déclarée.

    Cas normal : n (ex. bénéfices antérieurs sur 3 ans) est calculé
    automatiquement depuis l'historique — aucune entrée n'existe, la section est
    « Rien de déclaré ». Ce contrôle laisse le responsable forcer n quand
    l'historique est incomplet/erroné : crée l'entrée d'override, la valide.
    n vide + entrée existante => suppression => retour au calcul automatique.
    Réservé au responsable (modifie le score). Quand une entrée existe déjà,
    l'ajustement passe par « Ajuster n… » sur l'élément (route /entrees/.../ajuster).
    """
    dossier = _get_dossier(db, dossier_id)
    if not _decidable(dossier):
        raise HTTPException(status_code=403, detail="Dossier non soumis ou classement gelé.")
    grid = grid_for_campaign(dossier.campaign)
    criterion = next((c for c in grid.get("criteria", []) if c["id"] == criterion_id), None)
    if criterion is None or criterion.get("type") != "formula":
        raise HTTPException(status_code=422, detail="Ce critère n'est pas une formule.")

    form = await request.form()

    def _int_field(name: str) -> int | None:
        raw = form.get(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{name} doit être un entier.")
        if value < 0:
            raise HTTPException(status_code=422, detail=f"{name} doit être ≥ 0.")
        return value

    entry = next((e for e in dossier.entries if e.criterion_id == criterion_id), None)
    payload: dict = dict(entry.payload) if entry else {}

    n = _int_field("n")
    if n is None:
        payload.pop("n", None)
    else:
        payload["n"] = n
    if "N" in (criterion.get("formula") or ""):
        big_n = _int_field("N")
        if big_n is None:
            payload.pop("N", None)
        else:
            payload["N"] = big_n

    label = criterion.get("label_fr", criterion_id)
    if not payload:
        # Aucune valeur forcée : revenir au calcul automatique.
        if entry is not None:
            db.delete(entry)
            log_event(db, user, "formule_reset", dossier, detail=criterion_id)
            db.commit()
        request.session["flash"] = f"{label} : retour au calcul automatique."
        return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)

    now = datetime.now(timezone.utc)
    if entry is None:
        entry = Entry(dossier_id=dossier.id, criterion_id=criterion_id, payload=payload,
                      statut="valide", decided_by=user.id, decided_at=now)
        db.add(entry)
    else:
        entry.payload = payload
        entry.statut = "valide"
        entry.decided_by = user.id
        entry.decided_at = now
        entry.decision_motif = None
    log_event(db, user, "ajustement_formule", dossier,
              detail=f"{criterion_id} n={payload.get('n', 'auto')}")
    db.commit()
    request.session["flash"] = f"{label} : n = {payload.get('n')} enregistré."
    return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)


@router.post("/dossiers/{dossier_id}/tout-valider")
def tout_valider(
    dossier_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Passe les éléments encore en attente à « validé » (après revue du dossier)."""
    dossier = _get_dossier(db, dossier_id)
    if not _decidable(dossier):
        raise HTTPException(status_code=403, detail="Dossier non soumis ou classement gelé.")
    now = datetime.now(timezone.utc)
    n = 0
    for entry in dossier.entries:
        if entry.statut == "en_attente":
            entry.statut = "valide"
            entry.decided_by = user.id
            entry.decided_at = now
            n += 1
    log_event(db, user, "tout_valider", dossier, detail=f"{n} élément(s) validé(s)")
    db.commit()
    request.session["flash"] = f"{n} élément(s) en attente validé(s)."
    return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)


# ---------------------------------------------------------------------------
# Affectation des dossiers aux membres (responsable)
# ---------------------------------------------------------------------------


@router.get("/affectations")
def affectations(
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    dossiers = list(
        db.scalars(select(Dossier).where(Dossier.campaign_id == campaign.id).order_by(Dossier.id))
    )
    membres = _membres(db)
    # Charge par membre (nombre de dossiers affectés) + non affectés.
    charge = {m.id: 0 for m in membres}
    non_affectes = 0
    for d in dossiers:
        if d.assigned_reviewer_id in charge:
            charge[d.assigned_reviewer_id] += 1
        elif d.assigned_reviewer_id is None:
            non_affectes += 1
    return templates.TemplateResponse(
        request,
        "commission/affectations.html",
        {"user": user, "campaign": campaign, "dossiers": dossiers,
         "membres": membres, "charge": charge, "non_affectes": non_affectes},
    )


@router.post("/dossiers/{dossier_id}/affecter")
async def affecter(
    dossier_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Affecte (ou retire) le relecteur d'un dossier. reviewer_id vide = retrait."""
    dossier = _get_dossier(db, dossier_id)
    form = await request.form()
    raw = (form.get("reviewer_id") or "").strip()
    if raw:
        membre = db.get(User, int(raw)) if raw.isdigit() else None
        if membre is None or membre.role != "commission" or not membre.actif:
            raise HTTPException(status_code=422, detail="Relecteur invalide.")
        dossier.assigned_reviewer_id = membre.id
        detail = f"→ {membre.nom} {membre.prenom}".strip()
    else:
        dossier.assigned_reviewer_id = None
        detail = "retrait"
    log_event(db, user, "affectation_relecteur", dossier, detail=detail)
    db.commit()
    redirect = form.get("redirect") or "/commission/affectations"
    request.session["flash"] = f"Affectation mise à jour pour {dossier.candidate_ref}."
    return RedirectResponse(redirect, status_code=303)


@router.get("/classement")
def classement(
    request: Request,
    user: User = LECTURE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    result = compute_ranking(db, campaign, mode="commission")
    noms = {
        d.candidate_ref: f"{d.user.nom} {d.user.prenom}".strip() for d in result.dossiers
    }
    departements = {d.candidate_ref: d.departement for d in result.dossiers}
    nb_brouillons = db.scalar(
        select(func.count(Dossier.id)).where(
            Dossier.campaign_id == campaign.id, Dossier.statut == "brouillon"
        )
    ) or 0
    return templates.TemplateResponse(
        request,
        "commission/classement.html",
        {
            "user": user,
            "campaign": campaign,
            "grid": grid_for_campaign(campaign),
            "groups": result.groups,
            "noms": noms,
            "departements": departements,
            "pending": pending_entries_count(db, campaign),
            "nb_brouillons": nb_brouillons,
            "nb_classes": len(result.dossiers),
            "is_responsable": _is_responsable(user),
            "recours_ouverts_count": open_recours_count(db, campaign),
        },
    )


def _parse_da(value: str | None) -> float | None:
    """Montant saisi par la commission : tolère espaces (1 200 000) et virgule décimale."""
    if value is None or not str(value).strip():
        return None
    text = str(value).replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    return float(text.replace(",", "."))


@router.get("/budget")
def simulation_budget(
    request: Request,
    budget: str | None = None,
    plafond_billet: str | None = None,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Simulation budgétaire : qui peut bénéficier avec une enveloppe donnée.

    Simulation pure (aucune écriture) : financement par rang tous groupes
    confondus, départage au score, coupure stricte — voir ``classement.budget``.
    """
    campaign = get_campaign(db)
    erreur = None
    montant = plafond = None
    try:
        montant = _parse_da(budget)
        plafond = _parse_da(plafond_billet)
    except ValueError:
        erreur = "Montant invalide : saisir un nombre en dinars (ex. 1 200 000)."
    if montant is not None and montant <= 0:
        erreur = "L'enveloppe doit être strictement positive."
        montant = None
    if plafond is not None and plafond < 0:
        erreur = "Le plafond billet ne peut pas être négatif."
        montant = None

    simulation = None
    noms: dict[str, str] = {}
    dossier_ids: dict[str, int] = {}
    if montant is not None and erreur is None:
        result = compute_ranking(db, campaign, mode="commission")
        noms = {
            d.candidate_ref: f"{d.user.nom} {d.user.prenom}".strip() for d in result.dossiers
        }
        dossier_ids = {d.candidate_ref: d.id for d in result.dossiers}
        simulation = simulate_budget(
            result.candidates,
            result.groups,
            grid_for_campaign(campaign),
            get_costs(),
            montant,
            plafond,
        )
    nb_brouillons = db.scalar(
        select(func.count(Dossier.id)).where(
            Dossier.campaign_id == campaign.id, Dossier.statut == "brouillon"
        )
    ) or 0
    return templates.TemplateResponse(
        request,
        "commission/budget.html",
        {
            "user": user,
            "campaign": campaign,
            "grid": grid_for_campaign(campaign),
            "simulation": simulation,
            "noms": noms,
            "dossier_ids": dossier_ids,
            "erreur": erreur,
            "budget_saisi": budget or "",
            "plafond_saisi": plafond_billet or "",
            "nb_brouillons": nb_brouillons,
        },
    )


@router.post("/classement/geler")
def geler(
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    freeze_campaign(db, campaign, user)
    request.session["flash"] = "Le classement a été gelé."
    return RedirectResponse("/commission/classement", status_code=303)


# ---------------------------------------------------------------------------
# Recours (responsable) : ouverture de la fenêtre + traitement de la file
# ---------------------------------------------------------------------------


def _recours_ligne(spec_map: dict, recours: Recours) -> dict:
    """Résumé d'un recours pour la file du responsable (élément, décision, avis)."""
    entry = recours.entry
    spec = spec_map.get(entry.criterion_id)
    item_label = None
    if entry.item_id and spec:
        item_label = next((i["label"] for i in spec.get("items", [])
                           if i["id"] == entry.item_id), entry.item_id)
    return {
        "recours": recours,
        "dossier": entry.dossier,
        "entry": entry,
        "titre": spec["label"] if spec else entry.criterion_id,
        "item_label": item_label,
        "intitule": (entry.payload or {}).get("intitule"),
        "review": _review_of(entry, entry.dossier.assigned_reviewer_id),
    }


@router.post("/recours/fenetre")
async def basculer_fenetre_recours(
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    """Ouvre ou ferme la période de recours (publication des résultats provisoires)."""
    campaign = get_campaign(db)
    form = await request.form()
    action = form.get("action")
    if action == "ouvrir":
        open_recours_window(db, campaign, user, form.get("recours_deadline"))
        flash = "Période de recours ouverte : les enseignants voient le classement provisoire."
    elif action == "fermer":
        close_recours_window(db, campaign, user)
        flash = "Période de recours fermée."
    else:
        raise HTTPException(status_code=422, detail="Action inconnue.")
    request.session["flash"] = flash
    return RedirectResponse("/commission/classement", status_code=303)


@router.get("/recours")
def recours_a_traiter(
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    grid = grid_for_campaign(campaign)
    spec_map = {s["criterion_id"]: s for s in build_form_spec(grid)}
    lignes = [_recours_ligne(spec_map, r) for r in list_open_recours(db, campaign)]
    return templates.TemplateResponse(
        request,
        "commission/recours.html",
        {
            "user": user,
            "campaign": campaign,
            "grid": grid,
            "lignes": lignes,
            "recours_motif_labels": MOTIF_LABELS,
            "recours_statut_labels": STATUT_LABELS,
            "en_recours": recours_phase(campaign),
        },
    )


@router.post("/recours/{recours_id}/decision")
async def trancher_recours(
    recours_id: int,
    request: Request,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    recours = db.get(Recours, recours_id)
    if recours is None:
        raise HTTPException(status_code=404, detail="Recours introuvable.")
    form = await request.form()
    decide_recours(db, recours, user, form.get("decision") or "",
                   form.get("reponse_motif") or "")
    request.session["flash"] = (
        "Recours traité. Pour un recours accepté, corrigez l'élément dans le dossier "
        "(re-validation ou ajustement) : le score sera recalculé."
    )
    return RedirectResponse("/commission/recours", status_code=303)


@router.get("/exports/{kind}")
def telecharger_export(
    kind: str,
    user: User = RESPONSABLE,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    return export_response(db, campaign, kind)
