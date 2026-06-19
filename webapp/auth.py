"""Authentification par session signée et contrôle des rôles."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.models import User


# Pages accessibles malgré un mot de passe temporaire (sinon : boucle de
# redirection sur la page de changement, ou impossibilité de se déconnecter).
_EXEMPT_CHANGEMENT = {"/mon-mot-de-passe", "/deconnexion"}


def _redirect(request: Request, destination: str, *, status_code: int = 303) -> HTTPException:
    # Les requêtes HTMX reçoivent un en-tête de redirection côté client.
    if request.headers.get("HX-Request"):
        return HTTPException(status_code=401, headers={"HX-Redirect": destination})
    return HTTPException(status_code=status_code, headers={"Location": destination})


def _redirect_to_login(request: Request) -> HTTPException:
    return _redirect(request, "/connexion")


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
    # Mot de passe temporaire : tout est verrouillé tant qu'il n'est pas changé.
    if user.must_change_password and request.url.path not in _EXEMPT_CHANGEMENT:
        raise _redirect(request, "/mon-mot-de-passe")
    return user


def require_role(*roles: str):
    """Dépendance FastAPI : l'utilisateur connecté doit avoir l'un des rôles."""

    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Accès refusé pour ce rôle.")
        return user

    return checker
