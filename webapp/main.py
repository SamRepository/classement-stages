"""Point d'entrée FastAPI : ``uvicorn webapp.main:app``."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from webapp.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


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

    from webapp.routes import admin, auth, commission, enseignant, fichiers

    app.include_router(auth.router)
    app.include_router(enseignant.router)
    app.include_router(commission.router)
    app.include_router(admin.router)
    app.include_router(fichiers.router)
    return app


app = create_app()
