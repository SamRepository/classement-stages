"""Espace commission : examen des dossiers, décisions motivées, classement, exports.

Chaque élément déclaré est validé ou rejeté individuellement ; le rejet exige un
motif (art. 14-15). Le score commission est recalculé par le moteur à chaque
décision (les éléments rejetés sont exclus, les en attente restent comptés).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.auth import require_role
from webapp.db import get_db
from webapp.forms.grid_form import build_form_spec
from webapp.models import Dossier, Entry, User
from webapp.services.dossier import get_campaign, log_event
from webapp.services.exports import export_response, freeze_campaign, pending_entries_count
from webapp.services.scoring import compute_ranking, compute_score, get_grid
from webapp.templating import templates

router = APIRouter(prefix="/commission")

COMMISSION = Depends(require_role("commission", "admin"))


def _sections(dossier: Dossier, grid: dict) -> list[dict]:
    """Sections d'examen : spécification du critère + éléments déclarés."""
    rows_by_cid: dict[str, list[Entry]] = {}
    for entry in dossier.entries:
        rows_by_cid.setdefault(entry.criterion_id, []).append(entry)
    sections = []
    for spec in build_form_spec(grid):
        rows = rows_by_cid.get(spec["criterion_id"], [])
        if not rows and spec["widget"] in ("formula", "manual"):
            continue  # rien à examiner
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


def _render_element(request: Request, db: Session, entry: Entry, *, with_score: bool) -> HTMLResponse:
    grid = get_grid(entry.dossier.campaign.grid_id)
    labels: dict[str, str] = {}
    for spec in build_form_spec(grid):
        if spec["criterion_id"] == entry.criterion_id:
            labels = {i["id"]: i["label"] for i in spec.get("items", [])}
            break
    html = templates.get_template("commission/fragments/element.html").render(
        request=request, e=entry, labels=labels, decidable=_decidable(entry.dossier)
    )
    if with_score:
        html += _render_score(request, db, entry.dossier, oob=True)
    return HTMLResponse(html)


def _decidable(dossier: Dossier) -> bool:
    return dossier.statut == "soumis" and dossier.campaign.statut != "gelee"


def _get_dossier(db: Session, dossier_id: int) -> Dossier:
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return dossier


@router.get("/dossiers")
def liste_dossiers(
    request: Request,
    user: User = COMMISSION,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    dossiers = list(
        db.scalars(select(Dossier).where(Dossier.campaign_id == campaign.id).order_by(Dossier.id))
    )
    lignes = []
    for d in dossiers:
        compte = {"en_attente": 0, "valide": 0, "rejete": 0}
        for e in d.entries:
            compte[e.statut] += 1
        score = None
        if d.statut in ("soumis", "gele"):
            breakdown, _ = compute_score(db, d, mode="commission")
            score = breakdown.total
        lignes.append({"dossier": d, "compte": compte, "score": score})
    return templates.TemplateResponse(
        request,
        "commission/dossiers.html",
        {"user": user, "campaign": campaign, "lignes": lignes,
         "grid": get_grid(campaign.grid_id)},
    )


@router.get("/dossiers/{dossier_id}")
def vue_dossier(
    dossier_id: int,
    request: Request,
    user: User = COMMISSION,
    db: Session = Depends(get_db),
):
    dossier = _get_dossier(db, dossier_id)
    grid = get_grid(dossier.campaign.grid_id)
    breakdown, exclusions = compute_score(db, dossier, mode="commission")
    pending = sum(1 for e in dossier.entries if e.statut == "en_attente")
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
            "benefits": dossier.user.benefits,
        },
    )


@router.get("/dossiers/{dossier_id}/score")
def fragment_score(
    dossier_id: int,
    request: Request,
    user: User = COMMISSION,
    db: Session = Depends(get_db),
):
    dossier = _get_dossier(db, dossier_id)
    return HTMLResponse(_render_score(request, db, dossier, oob=False))


@router.post("/entrees/{entry_id}/decision")
async def decision(
    entry_id: int,
    request: Request,
    user: User = COMMISSION,
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
    return _render_element(request, db, entry, with_score=True)


@router.post("/dossiers/{dossier_id}/tout-valider")
def tout_valider(
    dossier_id: int,
    request: Request,
    user: User = COMMISSION,
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
    return RedirectResponse(f"/commission/dossiers/{dossier_id}", status_code=303)


@router.get("/classement")
def classement(
    request: Request,
    user: User = COMMISSION,
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
            "grid": get_grid(campaign.grid_id),
            "groups": result.groups,
            "noms": noms,
            "departements": departements,
            "pending": pending_entries_count(db, campaign),
            "nb_brouillons": nb_brouillons,
            "nb_classes": len(result.dossiers),
        },
    )


@router.post("/classement/geler")
def geler(
    user: User = COMMISSION,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    freeze_campaign(db, campaign, user)
    return RedirectResponse("/commission/classement", status_code=303)


@router.get("/exports/{kind}")
def telecharger_export(
    kind: str,
    user: User = COMMISSION,
    db: Session = Depends(get_db),
):
    campaign = get_campaign(db)
    return export_response(db, campaign, kind)
