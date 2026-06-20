"""Sauvegarde / restauration complètes (base + justificatifs).

Couvre l'aller-retour (build → restore sur base vierge), la préservation des
identifiants et des fichiers, et les garde-fous (confirmation, archive corrompue,
contrôle d'accès).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from sqlalchemy import select

from tests.webapp.conftest import PDF_BYTES, login
from webapp.models import Attachment, Benefit, Dossier, Entry, User
from webapp.services import backup


@pytest.fixture()
def etat_rempli(db_session, campaign, enseignant, dossier, upload_dir):
    """Un dossier avec un élément déclaré, un justificatif PDF et un bénéfice."""
    entry = Entry(
        dossier_id=dossier.id,
        criterion_id="publications",
        item_id="article_revue_a",
        payload={"date": "2025-03-01", "doi": "10.1/x"},
        date_activite=date(2025, 3, 1),
    )
    db_session.add(entry)
    db_session.flush()
    justif = upload_dir / "justificatifs" / str(dossier.id) / f"{entry.id}.pdf"
    justif.parent.mkdir(parents=True, exist_ok=True)
    justif.write_bytes(PDF_BYTES)
    db_session.add(Attachment(
        entry_id=entry.id, dossier_id=dossier.id, filename_original="article.pdf",
        stored_path=str(justif), size_bytes=len(PDF_BYTES),
    ))
    db_session.add(Benefit(user_id=enseignant.id, date=date(2024, 9, 15)))
    db_session.commit()
    return {"dossier_id": dossier.id, "entry_id": entry.id, "justif": justif}


def test_aller_retour_restaure_tout(db_session, upload_dir, etat_rempli):
    archive = backup.build_archive(db_session, upload_dir, institution_id="enset-skikda")
    try:
        # Purge totale puis suppression du justificatif sur disque.
        for model in (Attachment, Entry, Benefit, Dossier, User):
            for obj in db_session.scalars(select(model)):
                db_session.delete(obj)
        db_session.commit()
        etat_rempli["justif"].unlink()
        assert db_session.scalars(select(Entry)).first() is None

        rapport = backup.restore_archive(db_session, upload_dir, archive, confirmed=True)
        db_session.expire_all()
    finally:
        archive.unlink(missing_ok=True)

    assert rapport.warnings == []
    # Identifiants préservés.
    entry = db_session.get(Entry, etat_rempli["entry_id"])
    assert entry is not None and entry.criterion_id == "publications"
    assert entry.date_activite == date(2025, 3, 1)
    att = db_session.scalar(select(Attachment))
    assert att.filename_original == "article.pdf"
    # Fichier restauré à l'identique.
    assert etat_rempli["justif"].read_bytes() == PDF_BYTES
    assert db_session.scalar(select(Benefit)).date == date(2024, 9, 15)
    assert rapport.pre_restore_backup is not None


def test_restore_refuse_sans_confirmation(db_session, upload_dir, etat_rempli):
    archive = backup.build_archive(db_session, upload_dir)
    try:
        with pytest.raises(Exception):
            backup.restore_archive(db_session, upload_dir, archive, confirmed=False)
    finally:
        archive.unlink(missing_ok=True)


def test_archive_corrompue_refusee(db_session, upload_dir, campaign):
    """Une somme de contrôle altérée fait échouer la validation (aucune écriture)."""
    archive = backup.build_archive(db_session, upload_dir)
    try:
        # Réécrit l'archive avec un data/campaigns.json modifié (checksum cassé).
        buf = io.BytesIO()
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(buf, "w") as dst:
            for item in src.namelist():
                data = src.read(item)
                if item == "data/campaigns.json":
                    data = data.replace(b"enset-skikda", b"falsifie----")
                dst.writestr(item, data)
        archive.write_bytes(buf.getvalue())
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            backup.validate_archive(db_session, archive)
        assert "ontrôle" in exc.value.detail or "Somme" in exc.value.detail
    finally:
        archive.unlink(missing_ok=True)


# --- via HTTP (portail admin) ---------------------------------------------


def test_telechargement_admin(client, db_session, campaign, admin, upload_dir):
    login(client, "admin@test.dz")
    r = client.get("/admin/backup")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "manifest.json" in zf.namelist()
        assert "data/users.json" in zf.namelist()


def test_restore_http_deux_temps(client, db_session, campaign, admin, upload_dir):
    login(client, "admin@test.dz")
    archive_bytes = client.get("/admin/backup").content

    # Étape 1 : prévisualisation (validation, aucune écriture).
    r = client.post("/admin/restore/preview",
                    files={"fichier": ("backup.zip", archive_bytes, "application/zip")})
    assert r.status_code == 200
    assert "Remplacer toutes les données" in r.text

    # Étape 2 : confirmation avec la phrase exacte.
    import re

    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r = client.post("/admin/restore/confirm",
                    data={"token": token, "phrase": backup.CONFIRM_PHRASE})
    assert r.status_code == 200
    assert "Restauration effectuée" in r.text


def test_restore_phrase_incorrecte_refusee(client, db_session, campaign, admin, upload_dir):
    login(client, "admin@test.dz")
    archive_bytes = client.get("/admin/backup").content
    r = client.post("/admin/restore/preview",
                    files={"fichier": ("backup.zip", archive_bytes, "application/zip")})
    import re

    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r = client.post("/admin/restore/confirm", data={"token": token, "phrase": "oui"})
    assert r.status_code == 422


def test_sauvegarde_interdite_aux_autres_roles(client, campaign, enseignant):
    login(client, "enseignant@test.dz")
    assert client.get("/admin/sauvegarde").status_code == 403
    assert client.get("/admin/backup").status_code == 403
