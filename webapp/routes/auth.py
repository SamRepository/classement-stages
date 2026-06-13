"""Connexion / déconnexion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.auth import current_user
from webapp.db import get_db
from webapp.models import User
from webapp.security import hash_password, verify_password
from webapp.services.dossier import log_event
from webapp.templating import templates

router = APIRouter()

HOME_BY_ROLE = {
    "enseignant": "/mon-dossier",
    "commission": "/commission/dossiers",
    "admin": "/admin/utilisateurs",
}


@router.get("/")
def home(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id and role in HOME_BY_ROLE:
        return RedirectResponse(HOME_BY_ROLE[role], status_code=303)
    return RedirectResponse("/connexion", status_code=303)


@router.get("/connexion")
def login_form(request: Request):
    return templates.TemplateResponse(request, "connexion.html", {"erreur": None})


@router.post("/connexion")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.actif or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "connexion.html",
            {"erreur": "Adresse électronique ou mot de passe incorrect."},
            status_code=401,
        )
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    return RedirectResponse(HOME_BY_ROLE.get(user.role, "/"), status_code=303)


@router.post("/deconnexion")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/connexion", status_code=303)


@router.get("/mon-mot-de-passe")
def password_form(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(
        request, "mot_de_passe.html", {"user": user, "erreur": None, "succes": False}
    )


@router.post("/mon-mot-de-passe")
def password_change(
    request: Request,
    actuel: str = Form(...),
    nouveau: str = Form(...),
    confirmation: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    erreur = None
    if not verify_password(actuel, user.password_hash):
        erreur = "Mot de passe actuel incorrect."
    elif len(nouveau) < 8:
        erreur = "Le nouveau mot de passe doit compter au moins 8 caractères."
    elif nouveau != confirmation:
        erreur = "La confirmation ne correspond pas au nouveau mot de passe."
    if erreur:
        return templates.TemplateResponse(
            request,
            "mot_de_passe.html",
            {"user": user, "erreur": erreur, "succes": False},
            status_code=422,
        )
    user.password_hash = hash_password(nouveau)
    log_event(db, user, "changement_mot_de_passe")
    db.commit()
    return templates.TemplateResponse(
        request, "mot_de_passe.html", {"user": user, "erreur": None, "succes": True}
    )


@router.get("/sante")
def health():
    return {"statut": "ok"}
