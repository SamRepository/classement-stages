"""Service des justificatifs PDF aux utilisateurs autorisés.

Jamais de montage statique sur le dossier d'uploads : chaque accès passe par
le contrôle propriétaire / commission / admin.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from webapp.auth import current_user
from webapp.db import get_db
from webapp.models import Entry, User

router = APIRouter(prefix="/fichiers")


@router.get("/justificatifs/{entry_id}")
def justificatif(
    entry_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    entry = db.get(Entry, entry_id)
    if entry is None or entry.attachment is None:
        raise HTTPException(status_code=404, detail="Justificatif introuvable.")
    if user.role not in ("commission", "admin") and entry.dossier.user_id != user.id:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    path = Path(entry.attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier absent du stockage.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=entry.attachment.filename_original,
        content_disposition_type="inline",
    )
