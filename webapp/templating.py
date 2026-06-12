"""Instance Jinja2 partagée par toutes les routes."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
