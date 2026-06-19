"""Instance Jinja2 partagée par toutes les routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def static_version() -> str:
    """Empreinte des fichiers statiques (date de modif la plus récente).

    Sert de paramètre ``?v=`` sur les liens CSS/JS : à chaque déploiement, l'URL
    change et le navigateur recharge la version à jour au lieu d'un cache périmé.
    """
    try:
        latest = max(f.stat().st_mtime for f in STATIC_DIR.glob("*") if f.is_file())
        return str(int(latest))
    except ValueError:
        return "0"


templates.env.globals["static_version"] = static_version()
templates.env.globals["current_year"] = lambda: datetime.now().year


def fmt_points(value: float | int | None) -> str:
    """Affichage français des points : 12, 7,5, 0,25…"""
    if value is None:
        return "—"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") or "0"


def fmt_da(value: float | int | None) -> str:
    """Affichage français des montants en dinars : 1 234 567 DA."""
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", "\u00a0") + "\u00a0DA"


templates.env.filters["points"] = fmt_points
templates.env.filters["da"] = fmt_da
