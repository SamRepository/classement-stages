"""Sauvegarde et restauration complètes (base + justificatifs) en archive ZIP.

Mécanisme **portable** (cf. docs/spec-backup-restauration.md) : toutes les tables
métier sont sérialisées en JSON via le mapping SQLAlchemy, accompagnées des PDF du
volume et d'un manifeste. Indépendant du moteur de base (SQLite en dev, PostgreSQL
en prod) et du binaire ``pg_dump`` (absent de l'image slim).

Structure de l'archive ::

    classement-backup-<institution>-<AAAAMMJJ-HHMMSS>.zip
    ├── manifest.json
    ├── data/<table>.json        (une liste d'objets par table, ID préservés)
    └── uploads/justificatifs/<dossier_id>/<entry_id>.pdf

La restauration est un **remplacement complet** : purge puis réinsertion à
identifiants constants, réalignement des séquences PostgreSQL, et remplacement des
fichiers. Verrou central : la révision Alembic du manifeste doit être celle de
l'instance courante (cf. ``_assert_compatible``).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import Date, DateTime, select, text
from sqlalchemy.orm import Session

from webapp.db import Base

FORMAT_VERSION = 1
CONFIRM_PHRASE = "REMPLACER TOUTES LES DONNÉES"
_JUSTIF_RE = re.compile(r"^justificatifs/\d+/\d+\.pdf$")


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------


def _serialize_value(value):
    if isinstance(value, datetime):  # avant date : datetime hérite de date
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _deserialize_row(table, row: dict) -> dict:
    """Reconvertit les chaînes ISO en date/datetime selon le type de colonne."""
    out: dict = {}
    for key, value in row.items():
        if value is not None and key in table.c:
            coltype = table.c[key].type
            if isinstance(coltype, DateTime):
                value = datetime.fromisoformat(value)
            elif isinstance(coltype, Date):
                value = date.fromisoformat(value)
        out[key] = value
    return out


def _sha256(blob: bytes) -> str:
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _current_revision(db: Session) -> str | None:
    """Révision Alembic appliquée (None si la table n'existe pas — ex. tests)."""
    try:
        row = db.execute(text("SELECT version_num FROM alembic_version")).first()
        return row[0] if row else None
    except Exception:
        db.rollback()
        return None


def _backend(db: Session) -> str:
    return db.get_bind().dialect.name


# ---------------------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------------------


def build_archive(db: Session, upload_dir: Path, *, institution_id: str | None = None) -> Path:
    """Écrit une sauvegarde complète dans un fichier temporaire et renvoie son chemin.

    Opération en lecture seule. L'appelant est responsable de supprimer le fichier
    (le téléchargement le fait via une tâche d'arrière-plan).
    """
    upload_dir = Path(upload_dir)
    justif_root = upload_dir / "justificatifs"
    fd = tempfile.NamedTemporaryFile(prefix="classement-backup-", suffix=".zip", delete=False)
    fd.close()
    archive_path = Path(fd.name)

    counts: dict[str, int] = {}
    checksums: dict[str, str] = {}

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in Base.metadata.sorted_tables:
            rows = [dict(m) for m in db.execute(select(table)).mappings()]
            serial = [{k: _serialize_value(v) for k, v in row.items()} for row in rows]
            blob = json.dumps(serial, ensure_ascii=False, indent=1).encode("utf-8")
            arcname = f"data/{table.name}.json"
            zf.writestr(arcname, blob)
            checksums[arcname] = _sha256(blob)
            counts[table.name] = len(rows)

        file_count = 0
        total_bytes = 0
        if justif_root.exists():
            for path in sorted(justif_root.rglob("*")):
                if not path.is_file():
                    continue
                arcname = "uploads/" + path.relative_to(upload_dir).as_posix()
                data = path.read_bytes()
                zf.writestr(arcname, data)
                checksums[arcname] = _sha256(data)
                file_count += 1
                total_bytes += len(data)

        manifest = {
            "format_version": FORMAT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "app": "classement-stages",
            "alembic_revision": _current_revision(db),
            "institution_id": institution_id,
            "database_backend": _backend(db),
            "counts": counts,
            "files": {"count": file_count, "total_bytes": total_bytes},
            "checksums": checksums,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))

    return archive_path


def archive_filename(institution_id: str | None) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    inst = (institution_id or "classement").replace("/", "-")
    return f"classement-backup-{inst}-{stamp}.zip"


# ---------------------------------------------------------------------------
# Restauration
# ---------------------------------------------------------------------------


@dataclass
class RestoreReport:
    counts: dict[str, int]
    files_restored: int
    warnings: list[str] = field(default_factory=list)
    pre_restore_backup: str | None = None


def read_manifest(archive_path: Path) -> dict:
    """Lit et renvoie le manifeste (sans rien restaurer). Lève 422 si illisible."""
    try:
        with zipfile.ZipFile(archive_path) as zf:
            return json.loads(zf.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Archive illisible ou manifeste absent.")


def validate_archive(db: Session, archive_path: Path) -> dict:
    """Valide une archive sans rien écrire et renvoie son manifeste (lève 422 sinon)."""
    manifest = read_manifest(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            _assert_compatible(zf, manifest, db)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="Archive illisible.")
    return manifest


def _assert_compatible(zf: zipfile.ZipFile, manifest: dict, db: Session) -> None:
    if manifest.get("format_version") != FORMAT_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"Format d'archive non pris en charge (version {manifest.get('format_version')}).",
        )
    archive_rev = manifest.get("alembic_revision")
    current_rev = _current_revision(db)
    if archive_rev != current_rev:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sauvegarde produite par une version différente de l'application "
                f"(schéma {archive_rev!r} vs {current_rev!r}). Déployez la version "
                "correspondante avant de restaurer."
            ),
        )
    names = set(zf.namelist())
    for table in Base.metadata.sorted_tables:
        if f"data/{table.name}.json" not in names:
            raise HTTPException(
                status_code=422, detail=f"Table absente de l'archive : {table.name}."
            )
    # Intégrité : sommes de contrôle des fichiers présents dans le manifeste.
    for arcname, expected in (manifest.get("checksums") or {}).items():
        if arcname not in names:
            raise HTTPException(status_code=422, detail=f"Fichier manquant : {arcname}.")
        if _sha256(zf.read(arcname)) != expected:
            raise HTTPException(status_code=422, detail=f"Somme de contrôle invalide : {arcname}.")


def _restore_files(zf: zipfile.ZipFile, upload_dir: Path, warnings: list[str]) -> int:
    """Remplace ``justificatifs/`` par le contenu de l'archive (anti zip-slip)."""
    dest_root = Path(upload_dir).resolve()
    justif_root = dest_root / "justificatifs"
    if justif_root.exists():
        shutil.rmtree(justif_root)

    restored = 0
    for name in zf.namelist():
        if not name.startswith("uploads/"):
            continue
        rel = name[len("uploads/"):]
        if not rel or name.endswith("/"):
            continue
        if not _JUSTIF_RE.match(rel):
            warnings.append(f"Fichier ignoré (chemin inattendu) : {name}.")
            continue
        target = (dest_root / rel).resolve()
        if dest_root not in target.parents:
            warnings.append(f"Fichier ignoré (hors du dossier d'upload) : {name}.")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(name))
        restored += 1
    return restored


def restore_archive(
    db: Session, upload_dir: Path, archive_path: Path, *, confirmed: bool
) -> RestoreReport:
    """Remplacement complet de l'état (base + fichiers) par l'archive donnée."""
    if not confirmed:
        raise HTTPException(status_code=422, detail="Restauration non confirmée.")

    upload_dir = Path(upload_dir)
    with zipfile.ZipFile(archive_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        _assert_compatible(zf, manifest, db)

        # Filet de sécurité : sauvegarde de l'état courant avant écrasement.
        pre = build_archive(db, upload_dir, institution_id=manifest.get("institution_id"))
        pre_dir = upload_dir / "_pre_restore"
        pre_dir.mkdir(parents=True, exist_ok=True)
        pre_dest = pre_dir / archive_filename(manifest.get("institution_id"))
        shutil.move(str(pre), str(pre_dest))

        tables = list(Base.metadata.sorted_tables)
        counts: dict[str, int] = {}
        # Purge (enfants d'abord), puis réinsertion (parents d'abord), ID préservés.
        for table in reversed(tables):
            db.execute(table.delete())
        for table in tables:
            payload = json.loads(zf.read(f"data/{table.name}.json"))
            rows = [_deserialize_row(table, row) for row in payload]
            if rows:
                db.execute(table.insert(), rows)
            counts[table.name] = len(rows)

        if _backend(db) == "postgresql":
            _reset_sequences(db, tables)
        db.commit()

        warnings: list[str] = []
        files_restored = _restore_files(zf, upload_dir, warnings)

    # Contrôle post-restauration : chaque justificatif référencé existe-t-il ?
    from webapp.models import Attachment

    for att in db.scalars(select(Attachment)):
        if not Path(att.stored_path).exists():
            warnings.append(
                f"Justificatif manquant après restauration : {att.stored_path} "
                f"(entrée {att.entry_id})."
            )

    return RestoreReport(
        counts=counts,
        files_restored=files_restored,
        warnings=warnings,
        pre_restore_backup=str(pre_dest),
    )


def _reset_sequences(db: Session, tables) -> None:
    """Réaligne les séquences d'``id`` après des insertions à identifiant explicite."""
    for table in tables:
        if "id" not in table.c:
            continue
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
                f"(SELECT MAX(id) FROM {table.name}) IS NOT NULL)"
            )
        )
