"""Stockage des justificatifs PDF (volume persistant en production)."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models import Attachment, Entry

_CHUNK = 64 * 1024
_PDF_MAGIC = b"%PDF-"


def _target_path(upload_dir: Path, entry: Entry) -> Path:
    # Chemins construits uniquement depuis des identifiants serveur (entiers) :
    # pas de traversée possible. Le nom d'origine n'est conservé qu'en base.
    return upload_dir / "justificatifs" / str(entry.dossier_id) / f"{entry.id}.pdf"


def save_justificatif(
    db: Session,
    entry: Entry,
    file: UploadFile,
    *,
    upload_dir: Path | None = None,
    max_mb: int | None = None,
) -> Attachment:
    """Écrit le PDF en streaming avec contrôle de taille et des octets magiques."""
    settings = get_settings()
    upload_dir = upload_dir or settings.upload_dir
    max_bytes = (max_mb or settings.max_upload_mb) * 1024 * 1024

    head = file.file.read(len(_PDF_MAGIC))
    if head != _PDF_MAGIC:
        raise HTTPException(status_code=422, detail="Le justificatif doit être un fichier PDF.")

    path = _target_path(upload_dir, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(path, "wb") as out:
            out.write(head)
            size = len(head)
            while chunk := file.file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Fichier trop volumineux (maximum {max_bytes // (1024 * 1024)} Mo).",
                    )
                out.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise

    attachment = entry.attachment
    if attachment is None:
        attachment = Attachment(entry_id=entry.id, dossier_id=entry.dossier_id,
                                filename_original=file.filename or "justificatif.pdf",
                                stored_path=str(path), size_bytes=size)
        # Affecte la relation (et pas seulement db.add) : la session conserve
        # sinon le None chargé avant la création (expire_on_commit=False).
        entry.attachment = attachment
    else:
        attachment.filename_original = file.filename or attachment.filename_original
        attachment.stored_path = str(path)
        attachment.size_bytes = size
    db.flush()
    return attachment


def delete_justificatif(db: Session, entry: Entry) -> None:
    attachment = entry.attachment
    if attachment is None:
        return
    Path(attachment.stored_path).unlink(missing_ok=True)
    # L'orphanisation laisse le cascade delete-orphan supprimer la ligne (évite
    # une double suppression quand l'entrée elle-même est ensuite supprimée).
    entry.attachment = None
    db.flush()
