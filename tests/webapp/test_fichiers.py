"""Contrôle d'accès au visualiseur de justificatifs PDF."""

from sqlalchemy import select

from tests.webapp.conftest import PASSWORD, PDF_BYTES, login
from webapp.models import Entry, User
from webapp.security import hash_password


def _depose_justificatif(client, db_session) -> int:
    """L'enseignant dépose un justificatif ; renvoie l'id de l'entrée créée."""
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    client.post(
        "/mon-dossier/activites",
        data={"criterion_id": "publications", "item": "classe_a",
              "date": "2025-03-10", "author_position": "1"},
        files={"fichier": ("p.pdf", PDF_BYTES, "application/pdf")},
    )
    entry = db_session.scalar(select(Entry))
    client.post("/deconnexion")
    return entry.id


def test_responsable_voit_justificatif(client, db_session, campaign, enseignant,
                                       responsable, upload_dir):
    """Régression : le responsable de commission peut consulter un justificatif."""
    entry_id = _depose_justificatif(client, db_session)
    login(client, "responsable@test.dz")
    r = client.get(f"/fichiers/justificatifs/{entry_id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_membre_commission_voit_justificatif(client, db_session, campaign, enseignant,
                                             membre_commission, upload_dir):
    entry_id = _depose_justificatif(client, db_session)
    login(client, "commission@test.dz")
    assert client.get(f"/fichiers/justificatifs/{entry_id}").status_code == 200


def test_enseignant_non_proprietaire_refuse(client, db_session, campaign, enseignant,
                                            upload_dir):
    entry_id = _depose_justificatif(client, db_session)
    db_session.add(User(email="autre@test.dz", password_hash=hash_password(PASSWORD),
                        nom="Autre", role="enseignant"))
    db_session.commit()
    login(client, "autre@test.dz")
    assert client.get(f"/fichiers/justificatifs/{entry_id}").status_code == 403
