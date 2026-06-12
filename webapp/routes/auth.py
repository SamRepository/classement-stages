"""Connexion / déconnexion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.models import User
from webapp.security import verify_password
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


@router.get("/sante")
def health():
    return {"statut": "ok"}
