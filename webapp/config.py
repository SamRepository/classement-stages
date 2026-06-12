"""Configuration de l'application, lue depuis les variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    upload_dir: Path
    max_upload_mb: int
    cookie_secure: bool
    session_max_age: int  # secondes

    # Valeurs consommées par webapp.scripts.seed pour créer la campagne initiale.
    campaign_grid_id: str
    campaign_institution_id: str
    campaign_date: str  # AAAA-MM-JJ
    campaign_window_reference: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./dev.db"),
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-a-remplacer"),
        upload_dir=Path(os.environ.get("UPLOAD_DIR", "./uploads")),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "10")),
        cookie_secure=os.environ.get("COOKIE_SECURE", "0") == "1",
        session_max_age=int(os.environ.get("SESSION_MAX_AGE", str(8 * 3600))),
        campaign_grid_id=os.environ.get("CAMPAIGN_GRID_ID", "u3-residences-scientifiques"),
        campaign_institution_id=os.environ.get("CAMPAIGN_INSTITUTION_ID", "enset-skikda"),
        campaign_date=os.environ.get("CAMPAIGN_DATE", "2026-06-30"),
        campaign_window_reference=os.environ.get("CAMPAIGN_WINDOW_REFERENCE", "cloture"),
    )
