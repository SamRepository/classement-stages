"""Point d'entrée FastAPI : ``uvicorn webapp.main:app``."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from webapp.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Messages par défaut quand l'exception ne porte pas de détail en français.
MESSAGES_PAR_CODE = {
    401: "Connexion requise.",
    403: "Accès refusé.",
    404: "Page ou ressource introuvable.",
    405: "Action non autorisée sur cette adresse.",
    422: "Saisie invalide : vérifiez les champs du formulaire.",
    500: "Erreur interne de l'application — l'action n'a pas été enregistrée.",
}


def _register_error_pages(app: FastAPI) -> None:
    """Erreurs rendues en HTML français (page complète, ou texte brut pour HTMX).

    Les redirections (en-têtes Location / HX-Redirect posés par l'authentification)
    sont transmises telles quelles.
    """
    from webapp.templating import templates

    def render(request: Request, code: int, message: str) -> Response:
        if request.headers.get("HX-Request"):
            # HTMX : texte brut, affiché par l'écouteur htmx:responseError (base.html).
            return PlainTextResponse(message, status_code=code)
        return templates.TemplateResponse(
            request, "erreur.html", {"code": code, "message": message}, status_code=code
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        headers = exc.headers or {}
        if "Location" in headers or "HX-Redirect" in headers:
            return Response(status_code=exc.status_code, headers=headers)
        message = str(exc.detail or "")
        # Détails par défaut de Starlette (anglais) → message français du code.
        if not message or message == HTTPStatus(exc.status_code).phrase:
            message = MESSAGES_PAR_CODE.get(exc.status_code, "Erreur inattendue.")
        return render(request, exc.status_code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception(request: Request, exc: RequestValidationError) -> Response:
        return render(request, 422, MESSAGES_PAR_CODE[422])

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> Response:
        return render(request, 500, MESSAGES_PAR_CODE[500])


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Classement des mobilités — arrêté 345/2026", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    _register_error_pages(app)

    from webapp.routes import admin, auth, commission, enseignant, fichiers

    app.include_router(auth.router)
    app.include_router(enseignant.router)
    app.include_router(commission.router)
    app.include_router(admin.router)
    app.include_router(fichiers.router)
    return app


app = create_app()
