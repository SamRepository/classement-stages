"""Espace enseignant : saisie du dossier, score provisoire en temps réel, soumission.

Chaque modification renvoie le fragment HTMX de la section concernée plus le
fragment du score recalculé (hx-swap-oob) — le moteur est rappelé à chaque fois,
aucune logique de calcul côté client.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile
from sqlalchemy.orm import Session

from webapp.auth import require_role
from webapp.db import get_db
from webapp.forms.grid_form import build_form_spec
from webapp.models import Benefit, Dossier, Entry, User
from webapp.services.dossier import assert_editable, ensure_dossier, get_campaign, submit_dossier
from webapp.services.scoring import compute_score, get_grid, get_institution
from webapp.services.uploads import delete_justificatif, save_justificatif
from webapp.templating import templates

router = APIRouter(prefix="/mon-dossier")

SINGLE_WIDGETS = {"enum", "fixed", "fixed_cap", "capped", "count_simple"}


def _context(db: Session, user: User):
    campaign = get_campaign(db)
    dossier = ensure_dossier(db, user, campaign)
    grid = get_grid(campaign.grid_id)
    return campaign, dossier, grid


def _sections(dossier: Dossier, grid: dict) -> list[dict]:
    rows_by_cid: dict[str, list[Entry]] = {}
    for entry in dossier.entries:
        rows_by_cid.setdefault(entry.criterion_id, []).append(entry)
    return [
        {"spec": spec, "rows": rows_by_cid.get(spec["criterion_id"], [])}
        for spec in build_form_spec(grid)
    ]


def _find_section(dossier: Dossier, grid: dict, criterion_id: str) -> dict:
    for section in _sections(dossier, grid):
        if section["spec"]["criterion_id"] == criterion_id:
            return section
    raise HTTPException(status_code=404, detail=f"Critère inconnu : {criterion_id!r}.")


def _render_score(request: Request, db: Session, dossier: Dossier, *, oob: bool) -> str:
    breakdown, _ = compute_score(db, dossier, mode="declare")
    return templates.get_template("enseignant/fragments/score.html").render(
        request=request, breakdown=breakdown, oob=oob
    )


def _section_response(
    request: Request, db: Session, dossier: Dossier, grid: dict, criterion_id: str
) -> HTMLResponse:
    """Fragment de la section + fragment du score (hx-swap-oob)."""
    section = _find_section(dossier, grid, criterion_id)
    html = templates.get_template("enseignant/fragments/section_critere.html").render(
        request=request, section=section, editable=dossier.statut == "brouillon"
    )
    html += _render_score(request, db, dossier, oob=True)
    return HTMLResponse(html)


@router.get("")
def page_dossier(
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    campaign, dossier, grid = _context(db, user)
    institution = get_institution(campaign.institution_id)
    benefits = db.query(Benefit).filter(Benefit.user_id == user.id).order_by(Benefit.date).all()
    return templates.TemplateResponse(
        request,
        "enseignant/dossier.html",
        {
            "user": user,
            "campaign": campaign,
            "dossier": dossier,
            "grid": grid,
            "departements": institution.get("departements", []),
            "benefits": benefits,
            "sections": _sections(dossier, grid),
            "editable": dossier.statut == "brouillon",
        },
    )


@router.get("/score")
def fragment_score(
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    _, dossier, _ = _context(db, user)
    return HTMLResponse(_render_score(request, db, dossier, oob=False))


@router.post("/infos")
async def maj_infos(
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    _, dossier, _ = _context(db, user)
    assert_editable(dossier)
    form = await request.form()
    dossier.departement = (form.get("departement") or None) or dossier.departement
    dossier.pays = (form.get("pays") or "").strip() or None
    dossier.duree_jours = _to_int(form.get("duree_jours"))
    dossier.billet_estime_da = _to_float(form.get("billet_estime_da"))
    dossier.frais_divers_da = _to_float(form.get("frais_divers_da"))
    db.commit()
    return RedirectResponse("/mon-dossier", status_code=303)


def _to_int(value, default=None):
    try:
        return int(str(value).strip()) if value not in (None, "") else default
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Nombre entier attendu : {value!r}.")


def _to_float(value, default=None):
    try:
        return float(str(value).replace(",", ".").strip()) if value not in (None, "") else default
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Nombre attendu : {value!r}.")


def _to_date(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Date AAAA-MM-JJ attendue : {value!r}.")


def _reset_decision(entry: Entry) -> None:
    """Toute modification par l'enseignant invalide une décision antérieure."""
    entry.statut = "en_attente"
    entry.decision_motif = None
    entry.decided_by = None
    entry.decided_at = None


def _single_payload(spec: dict, form) -> tuple[dict | None, str | None]:
    """(payload, item_id) pour les critères à entrée unique ; payload None = suppression."""
    widget = spec["widget"]
    if widget == "enum":
        value = form.get("value")
        if not value:
            return None, None
        if value not in {o["value"] for o in spec["options"]}:
            raise HTTPException(status_code=422, detail=f"Option inconnue : {value!r}.")
        payload: dict = {"value": value}
        if form.get("option_bonus"):
            payload["option_bonus"] = True
        return payload, None
    if widget == "fixed":
        if not form.get("applies"):
            return None, None
        indices = sorted({int(i) for i in form.getlist("bonus")})
        for i in indices:
            if not (0 <= i < len(spec["bonuses"])):
                raise HTTPException(status_code=422, detail=f"Bonus inconnu : {i}.")
        payload = {"applies": True}
        if indices:
            payload["bonuses"] = indices
        return payload, None
    if widget in ("fixed_cap", "capped"):
        points = _to_float(form.get("points"))
        if points is None:
            return None, None
        return {"points": points}, None
    if widget == "count_simple":
        count = _to_int(form.get("quantite"))
        if not count or count <= 0:
            return None, None
        payload = {"count": count}
        url = (form.get("url") or "").strip()
        if url:
            payload["url"] = url
        return payload, spec["item_id"]
    raise HTTPException(status_code=422, detail=f"Saisie non supportée pour {widget!r}.")


@router.post("/entrees/{criterion_id}")
async def maj_entree(
    criterion_id: str,
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    """Critères à entrée unique (enum, fixed, capped, saisie simple) : upsert."""
    _, dossier, grid = _context(db, user)
    assert_editable(dossier)
    section = _find_section(dossier, grid, criterion_id)
    spec = section["spec"]
    if spec["widget"] not in SINGLE_WIDGETS:
        raise HTTPException(status_code=422, detail="Ce critère se saisit par éléments (activités).")

    form = await request.form()
    payload, item_id = _single_payload(spec, form)
    existing = section["rows"][0] if section["rows"] else None

    if payload is None:
        if existing is not None:
            delete_justificatif(db, existing)
            db.delete(existing)
            db.commit()
            db.refresh(dossier)
        return _section_response(request, db, dossier, grid, criterion_id)

    if existing is None:
        existing = Entry(dossier_id=dossier.id, criterion_id=criterion_id)
        db.add(existing)
    existing.payload = payload
    existing.item_id = item_id
    _reset_decision(existing)
    db.flush()

    fichier = form.get("fichier")
    if isinstance(fichier, UploadFile) and fichier.filename:
        save_justificatif(db, existing, fichier)
    db.commit()
    db.refresh(dossier)
    return _section_response(request, db, dossier, grid, criterion_id)


@router.post("/activites")
async def ajout_activite(
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    """Ajoute un élément déclaré (une ligne `count`) avec son justificatif."""
    _, dossier, grid = _context(db, user)
    assert_editable(dossier)
    form = await request.form()
    criterion_id = form.get("criterion_id") or ""
    section = _find_section(dossier, grid, criterion_id)
    spec = section["spec"]
    if spec["widget"] != "count_detail":
        raise HTTPException(status_code=422, detail="Ce critère ne se saisit pas par éléments.")

    item_id = form.get("item")
    items = {i["id"]: i for i in spec["items"]}
    if item_id not in items:
        raise HTTPException(status_code=422, detail=f"Élément inconnu : {item_id!r}.")

    payload: dict = {"count": _to_int(form.get("quantite"), default=1) or 1}
    if payload["count"] <= 0:
        raise HTTPException(status_code=422, detail="La quantité doit être positive.")
    intitule = (form.get("intitule") or "").strip()
    if intitule:
        payload["intitule"] = intitule
    activite_date = _to_date(form.get("date"))
    if spec["has_date"] and not activite_date:
        raise HTTPException(
            status_code=422,
            detail="Date obligatoire : ce critère ne compte que les éléments postérieurs "
                   "au dernier bénéfice.",
        )
    if activite_date:
        payload["date"] = activite_date
    if spec["has_position"]:
        position = _to_int(form.get("author_position"))
        if position is not None:
            if position < 1:
                raise HTTPException(status_code=422, detail="Position d'auteur ≥ 1 attendue.")
            payload["author_position"] = position
    for key in ("doi", "url"):
        value = (form.get(key) or "").strip()
        if value:
            payload[key] = value
    if items[item_id]["leader_bonus"]:
        leader = _to_int(form.get("leader_count"))
        if leader:
            payload["leader_count"] = leader
    if spec["bonuses"]:
        bonus = _to_int(form.get("bonus_count"))
        if bonus:
            payload["bonus_count"] = bonus

    entry = Entry(
        dossier_id=dossier.id,
        criterion_id=criterion_id,
        item_id=item_id,
        payload=payload,
        date_activite=date.fromisoformat(activite_date) if activite_date else None,
    )
    db.add(entry)
    db.flush()

    fichier = form.get("fichier")
    if isinstance(fichier, UploadFile) and fichier.filename:
        save_justificatif(db, entry, fichier)
    db.commit()
    db.refresh(dossier)
    return _section_response(request, db, dossier, grid, criterion_id)


@router.post("/activites/{entry_id}/justificatif")
async def remplace_justificatif(
    entry_id: int,
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    _, dossier, grid = _context(db, user)
    assert_editable(dossier)
    entry = db.get(Entry, entry_id)
    if entry is None or entry.dossier_id != dossier.id:
        raise HTTPException(status_code=404)
    form = await request.form()
    fichier = form.get("fichier")
    if not (isinstance(fichier, UploadFile) and fichier.filename):
        raise HTTPException(status_code=422, detail="Aucun fichier fourni.")
    save_justificatif(db, entry, fichier)
    _reset_decision(entry)
    db.commit()
    db.refresh(dossier)
    return _section_response(request, db, dossier, grid, entry.criterion_id)


@router.delete("/activites/{entry_id}")
def supprime_activite(
    entry_id: int,
    request: Request,
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    _, dossier, grid = _context(db, user)
    assert_editable(dossier)
    entry = db.get(Entry, entry_id)
    if entry is None or entry.dossier_id != dossier.id:
        raise HTTPException(status_code=404)
    criterion_id = entry.criterion_id
    delete_justificatif(db, entry)
    db.delete(entry)
    db.commit()
    db.refresh(dossier)
    return _section_response(request, db, dossier, grid, criterion_id)


@router.post("/soumettre")
def soumettre(
    user: User = Depends(require_role("enseignant")),
    db: Session = Depends(get_db),
):
    _, dossier, _ = _context(db, user)
    submit_dossier(db, dossier, user)
    return RedirectResponse("/mon-dossier", status_code=303)
