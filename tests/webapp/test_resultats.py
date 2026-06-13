"""Visibilité des résultats côté enseignant après le gel du classement."""

import pytest

from tests.webapp.conftest import login
from webapp.models import Entry


@pytest.fixture()
def dossier_soumis(db_session, dossier):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "professeur"}))
    dossier.statut = "soumis"
    db_session.commit()
    db_session.refresh(dossier)
    return dossier


def _geler(client, db_session, dossier_soumis):
    login(client, "commission@test.dz")
    client.post(f"/commission/dossiers/{dossier_soumis.id}/tout-valider")
    r = client.post("/commission/classement/geler")
    assert r.status_code == 303
    client.post("/deconnexion")


def test_rang_visible_apres_gel(client, db_session, campaign, dossier_soumis,
                                membre_commission, enseignant):
    _geler(client, db_session, dossier_soumis)
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 200
    assert "Résultat du classement" in r.text
    assert "sur 1" in r.text          # classé 1ᵉʳ sur 1
    assert "score retenu" in r.text


def test_pas_de_resultat_avant_gel(client, db_session, campaign, dossier_soumis,
                                   enseignant):
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 200
    assert "Résultat du classement" not in r.text
    assert "en cours d'examen" in r.text


def test_non_soumis_signale_apres_gel(client, db_session, campaign, dossier_soumis,
                                      membre_commission, admin):
    """Un agent dont le dossier n'a jamais été soumis voit qu'il n'est pas classé."""
    _geler(client, db_session, dossier_soumis)
    # L'admin a accès à /mon-dossier ? Non : créer un second enseignant en brouillon.
    from webapp.models import Dossier, User
    from webapp.security import hash_password
    from tests.webapp.conftest import PASSWORD

    autre = User(email="retard@test.dz", password_hash=hash_password(PASSWORD),
                 nom="Retard", prenom="", role="enseignant")
    db_session.add(autre)
    db_session.commit()
    db_session.add(Dossier(campaign_id=campaign.id, user_id=autre.id,
                           candidate_ref="DC-2026-099", statut="brouillon"))
    db_session.commit()
    login(client, "retard@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 200
    assert "n'y figure pas" in r.text
