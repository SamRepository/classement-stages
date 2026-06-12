"""Authentification par session signée et contrôle des rôles."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.models import User


def _redirect_to_login(request: Request) -> HTTPException:
    # Les requêtes HTMX reçoivent un en-tête de redirection côté client.
    if request.headers.get("HX-Request"):
        return HTTPException(status_code=401, headers={"HX-Redirect": "/connexion"})
    return HTTPException(status_code=303, headers={"Location": "/connexion"})


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise _redirect_to_login(request)
    user = db.get(User, user_id)
    if user is None or not user.actif:
        request.session.clear()
        raise _redirect_to_login(request)
    return user


def require_role(*roles: str):
    """Dépendance FastAPI : l'utilisateur connecté doit avoir l'un des rôles."""

    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Accès refusé pour ce rôle.")
        return user

    return checker
