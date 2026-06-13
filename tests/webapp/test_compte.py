"""Changement de mot de passe, pages d'erreur HTML, bandeau expérimental."""

from tests.webapp.conftest import PASSWORD, login


def test_changement_mot_de_passe(client, db_session, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.post("/mon-mot-de-passe", data={
        "actuel": PASSWORD, "nouveau": "nouveau-secret", "confirmation": "nouveau-secret",
    })
    assert r.status_code == 200
    assert "Mot de passe modifié" in r.text
    # L'ancien mot de passe ne fonctionne plus, le nouveau oui.
    client.post("/deconnexion")
    assert login(client, "enseignant@test.dz", PASSWORD).status_code == 401
    assert login(client, "enseignant@test.dz", "nouveau-secret").status_code == 303


def test_changement_refus_actuel_incorrect(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.post("/mon-mot-de-passe", data={
        "actuel": "faux", "nouveau": "nouveau-secret", "confirmation": "nouveau-secret",
    })
    assert r.status_code == 422
    assert "actuel incorrect" in r.text


def test_changement_refus_trop_court(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.post("/mon-mot-de-passe", data={
        "actuel": PASSWORD, "nouveau": "court", "confirmation": "court",
    })
    assert r.status_code == 422
    assert "8 caractères" in r.text


def test_changement_refus_confirmation(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.post("/mon-mot-de-passe", data={
        "actuel": PASSWORD, "nouveau": "nouveau-secret", "confirmation": "autre-chose",
    })
    assert r.status_code == 422
    assert "confirmation ne correspond pas" in r.text


def test_mot_de_passe_exige_connexion(client):
    r = client.get("/mon-mot-de-passe")
    assert r.status_code == 303
    assert r.headers["location"] == "/connexion"


def test_page_erreur_404_html(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.get("/page-inexistante")
    assert r.status_code == 404
    assert "Erreur 404" in r.text
    assert "introuvable" in r.text


def test_page_erreur_403_html(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.get("/commission/dossiers")
    assert r.status_code == 403
    assert "Erreur 403" in r.text
    assert "refusé" in r.text


def test_erreur_htmx_en_texte_brut(client, enseignant, campaign):
    login(client, "enseignant@test.dz")
    r = client.get("/page-inexistante", headers={"HX-Request": "true"})
    assert r.status_code == 404
    assert "<html" not in r.text
    assert "introuvable" in r.text


def test_bandeau_experimental_connexion(client):
    r = client.get("/connexion")
    assert "phase expérimentale" in r.text
    assert "s.sellami@enset-skikda.dz" in r.text
