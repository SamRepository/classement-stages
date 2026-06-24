"""Archive ZIP du dossier d'un enseignant : récapitulatif HTML + justificatifs PDF.

Le récapitulatif est une page HTML autonome (imprimable en PDF par l'enseignant,
cohérent avec la « voie PDF » des exports officiels). Les justificatifs sont les
PDF déjà déposés, copiés tels quels sous ``justificatifs/`` et reliés au récap par
des liens relatifs.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from webapp.forms.grid_form import build_form_spec
from webapp.models import Dossier
from webapp.services.scoring import compute_score, grid_for_campaign
from webapp.templating import templates

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str) -> str:
    """Nom de fichier sûr pour l'archive (pas de séparateur, extension .pdf)."""
    base = Path(name or "").name  # retire tout séparateur de chemin
    base = _UNSAFE.sub("_", base).strip("._") or "justificatif"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base


def build_dossier_archive(db: Session, dossier: Dossier) -> str:
    """Construit l'archive ZIP du dossier ; renvoie le chemin du fichier temporaire.

    L'appelant est responsable de la suppression du fichier (BackgroundTask).
    """
    grid = grid_for_campaign(dossier.campaign)
    breakdown, _ = compute_score(db, dossier, mode="declare")

    rows_by_cid: dict[str, list] = {}
    for entry in dossier.entries:
        rows_by_cid.setdefault(entry.criterion_id, []).append(entry)

    # Sections ordonnées comme la grille ; chemin d'archive du justificatif présent.
    att_links: dict[int, str] = {}
    sections: list[dict] = []
    for spec in build_form_spec(grid):
        rows = rows_by_cid.get(spec["criterion_id"], [])
        for r in rows:
            att = r.attachment
            if att is not None and Path(att.stored_path).is_file():
                att_links[r.id] = f"justificatifs/{r.id}_{_safe_name(att.filename_original)}"
        sections.append({"label": spec["label"], "rows": rows})

    html = templates.get_template("enseignant/archive_recap.html").render(
        dossier=dossier,
        grid=grid,
        campaign=dossier.campaign,
        breakdown=breakdown,
        sections=sections,
        att_links=att_links,
        generated_at=datetime.now(timezone.utc),
    )

    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("recapitulatif.html", html)
            for entry in dossier.entries:
                arc = att_links.get(entry.id)
                if arc:
                    zf.write(entry.attachment.stored_path, arc)
    except Exception:
        os.unlink(path)
        raise
    return path
