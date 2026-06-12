"""Espace admin : comptes, historique des bénéfices, campagne, réouvertures."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from webapp.auth import require_role
from webapp.db import get_db
from webapp.models import Benefit, Dossier, User
from webapp.security import generate_password, hash_password
from webapp.services.accounts import import_accounts
from webapp.services.dossier import get_campaign, log_event, reopen_dossier
from webapp.templating import templates

router = APIRouter(prefix="/admin")

ADMIN = Depends(require_role("admin"))


def _page_utilisateurs(request: Request, db: Session, user: User, **extra):
    users = list(db.scalars(select(User).order_by(User.role, User.nom)))
    contexte = {"user": user, "users": users, "nouveaux": [], "ignores": [], **extra}
    return templates.TemplateResponse(request, "admin/utilisateurs.html", contexte)


@router.get("/utilisateurs")
def utilisateurs(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    return _page_utilisateurs(request, db, user)


@router.post("/utilisateurs")
async def creer_utilisateur(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    nom = (form.get("nom") or "").strip()
    role = form.get("role") or "enseignant"
    if not email or "@" not in email or not nom:
        raise HTTPException(status_code=422, detail="Email et nom obligatoires.")
    if role not in ("enseignant", "commission", "admin"):
        raise HTTPException(status_code=422, detail=f"Rôle inconnu : {role!r}.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=422, detail=f"{email} existe déjà.")
    password = generate_password()
    nouveau = User(email=email, password_hash=hash_password(password), nom=nom,
                   prenom=(form.get("prenom") or "").strip(), role=role)
    db.add(nouveau)
    log_event(db, user, "creation_compte", detail=f"{email} ({role})")
    db.commit()
    return _page_utilisateurs(
        request, db, user,
        nouveaux=[{"email": email, "nom": nom, "prenom": nouveau.prenom, "password": password}],
    )


@router.post("/utilisateurs/import")
async def importer_utilisateurs(
    request: Request, user: User = ADMIN, db: Session = Depends(get_db)
):
    form = await request.form()
    fichier = form.get("fichier")
    if not (isinstance(fichier, UploadFile) and fichier.filename):
        raise HTTPException(status_code=422, detail="Aucun fichier fourni.")
    campaign = get_campaign(db)
    created, skipped = import_accounts(db, campaign, fichier.filename, await fichier.read())
    log_event(db, user, "import_comptes",
              detail=f"{fichier.filename} : {len(created)} créé(s), {len(skipped)} ignoré(s)")
    db.commit()
    return _page_utilisateurs(request, db, user, nouveaux=created, ignores=skipped)


@router.post("/utilisateurs/{user_id}/basculer-actif")
def basculer_actif(user_id: int, user: User = ADMIN, db: Session = Depends(get_db)):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    if cible.id == user.id:
        raise HTTPException(status_code=422, detail="Impossible de désactiver son propre compte.")
    cible.actif = not cible.actif
    log_event(db, user, "bascule_actif", detail=f"{cible.email} → actif={cible.actif}")
    db.commit()
    return RedirectResponse("/admin/utilisateurs", status_code=303)


@router.post("/utilisateurs/{user_id}/motdepasse")
def reinitialiser_motdepasse(
    request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    password = generate_password()
    cible.password_hash = hash_password(password)
    log_event(db, user, "reinit_motdepasse", detail=cible.email)
    db.commit()
    return _page_utilisateurs(
        request, db, user,
        nouveaux=[{"email": cible.email, "nom": cible.nom, "prenom": cible.prenom,
                   "password": password}],
    )


# ---------------------------------------------------------------------------
# Historique des bénéfices
# ---------------------------------------------------------------------------


@router.get("/benefices")
def benefices(
    request: Request,
    user_id: int | None = None,
    user: User = ADMIN,
    db: Session = Depends(get_db),
):
    enseignants = list(
        db.scalars(select(User).where(User.role == "enseignant").order_by(User.nom))
    )
    cible = db.get(User, user_id) if user_id else None
    return templates.TemplateResponse(
        request,
        "admin/benefices.html",
        {"user": user, "enseignants": enseignants, "cible": cible,
         "benefits": cible.benefits if cible else []},
    )


@router.post("/benefices")
async def ajouter_benefice(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    cible = db.get(User, int(form.get("user_id") or 0))
    if cible is None:
        raise HTTPException(status_code=404, detail="Enseignant introuvable.")
    try:
        date_mobilite = date.fromisoformat(form.get("date") or "")
    except ValueError:
        raise HTTPException(status_code=422, detail="Date de mobilité invalide (AAAA-MM-JJ).")
    close = None
    if form.get("platform_close_date"):
        try:
            close = date.fromisoformat(form.get("platform_close_date"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Date de clôture invalide (AAAA-MM-JJ).")
    db.add(Benefit(user_id=cible.id, date=date_mobilite, platform_close_date=close,
                   note=(form.get("note") or "").strip() or None))
    log_event(db, user, "ajout_benefice", detail=f"{cible.email} : {date_mobilite}")
    db.commit()
    return RedirectResponse(f"/admin/benefices?user_id={cible.id}", status_code=303)


@router.post("/benefices/{benefit_id}/supprimer")
def supprimer_benefice(benefit_id: int, user: User = ADMIN, db: Session = Depends(get_db)):
    benefit = db.get(Benefit, benefit_id)
    if benefit is None:
        raise HTTPException(status_code=404)
    user_id = benefit.user_id
    log_event(db, user, "suppression_benefice", detail=f"user={user_id} date={benefit.date}")
    db.delete(benefit)
    db.commit()
    return RedirectResponse(f"/admin/benefices?user_id={user_id}", status_code=303)


# ---------------------------------------------------------------------------
# Campagne et réouvertures
# ---------------------------------------------------------------------------


@router.get("/campagne")
def campagne(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    camp = get_campaign(db)
    dossiers = list(
        db.scalars(select(Dossier).where(Dossier.campaign_id == camp.id).order_by(Dossier.id))
    )
    return templates.TemplateResponse(
        request,
        "admin/campagne.html",
        {"user": user, "campaign": camp, "dossiers": dossiers},
    )


@router.post("/campagne")
async def maj_campagne(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    camp = get_campaign(db)
    if camp.statut == "gelee":
        raise HTTPException(status_code=403, detail="Campagne gelée : paramètres figés.")
    form = await request.form()

    def _dt(name: str) -> datetime | None:
        raw = (form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Date/heure invalide : {raw!r}.")

    statut = form.get("statut") or camp.statut
    if statut not in ("ouverte", "cloturee"):
        raise HTTPException(status_code=422, detail=f"Statut inconnu : {statut!r}.")
    if form.get("campaign_date"):
        try:
            camp.campaign_date = date.fromisoformat(form.get("campaign_date"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Date de campagne invalide.")
    camp.date_ouverture = _dt("date_ouverture")
    camp.date_cloture = _dt("date_cloture")
    camp.statut = statut
    log_event(db, user, "maj_campagne", detail=f"statut={statut}")
    db.commit()
    return RedirectResponse("/admin/campagne", status_code=303)


@router.post("/dossiers/{dossier_id}/reouvrir")
def reouvrir(dossier_id: int, user: User = ADMIN, db: Session = Depends(get_db)):
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404)
    reopen_dossier(db, dossier, user)
    return RedirectResponse("/admin/campagne", status_code=303)
