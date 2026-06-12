"""Connexion / déconnexion / rôles."""

from tests.webapp.conftest import login


def test_login_trois_roles(client, enseignant, membre_commission, admin):
    cas = [
        ("enseignant@test.dz", "/mon-dossier"),
        ("commission@test.dz", "/commission/dossiers"),
        ("admin@test.dz", "/admin/utilisateurs"),
    ]
    for email, home in cas:
        r = login(client, email)
        assert r.status_code == 303, email
        assert r.headers["location"] == home
        client.post("/deconnexion")


def test_login_mauvais_mot_de_passe(client, enseignant):
    r = login(client, "enseignant@test.dz", "faux")
    assert r.status_code == 401
    assert "incorrect" in r.text


def test_login_compte_inactif(client, db_session, enseignant):
    enseignant.actif = False
    db_session.commit()
    r = login(client, "enseignant@test.dz")
    assert r.status_code == 401


def test_acces_anonyme_redirige(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/connexion"


def test_sante(client):
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json() == {"statut": "ok"}
