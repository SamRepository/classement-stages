"""Simulation budgétaire commission : ordre de financement, coupure, plafond billet."""

import pytest

from tests.webapp.conftest import PASSWORD, login
from webapp.models import Dossier, Entry, User
from webapp.security import hash_password

# Coût d'un dossier des fixtures : France (Zone I) 10 j → 120 000 × 1,2 (majoration
# enseignant chercheur) = 144 000 + billet 100 000 + frais 20 000 = 264 000 DA.
COUT_DOSSIER = 264_000


@pytest.fixture()
def deux_dossiers(db_session, campaign, enseignant):
    autre = User(
        email="autre@test.dz",
        password_hash=hash_password(PASSWORD),
        nom="Cherif",
        prenom="Ali",
        role="enseignant",
    )
    db_session.add(autre)
    db_session.commit()
    mobilite = dict(pays="France", duree_jours=10,
                    billet_estime_da=100_000, frais_divers_da=20_000)
    d1 = Dossier(campaign_id=campaign.id, user_id=enseignant.id,
                 candidate_ref="DC-2026-001", departement="technologie",
                 statut="soumis", **mobilite)
    d2 = Dossier(campaign_id=campaign.id, user_id=autre.id,
                 candidate_ref="DC-2026-002", departement="technologie",
                 statut="soumis", **mobilite)
    db_session.add_all([d1, d2])
    db_session.commit()
    # d1 mieux classé (professeur : 7 pts) ; d2 sans rang → rangs 1 et 2.
    db_session.add(Entry(dossier_id=d1.id, criterion_id="rang_scientifique",
                         payload={"value": "professeur"}))
    db_session.commit()
    return d1, d2


def test_acces_interdit_aux_enseignants(client, campaign, enseignant):
    login(client, "enseignant@test.dz")
    assert client.get("/commission/budget").status_code == 403


def test_formulaire_sans_simulation(client, campaign, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget")
    assert r.status_code == 200
    assert "Saisir l'enveloppe" in r.text


def test_budget_couvrant_toutes_les_demandes(client, db_session, deux_dossiers,
                                             membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget", params={"budget": "600000"})
    assert r.status_code == 200
    assert "badge non-financable" not in r.text
    assert "couvre toutes les demandes" in r.text
    # Reliquat : 600 000 − 2 × 264 000 = 72 000 DA (insécables dans l'affichage).
    assert "72\u00a0000\u00a0DA" in r.text


def test_coupure_stricte_au_rang(client, db_session, deux_dossiers, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget", params={"budget": "300000"})
    assert r.status_code == 200
    # Le rang 1 (DC-2026-001) est financé, le rang 2 ne tient plus dans le reliquat.
    assert "badge non-financable" in r.text
    assert "badge finance" in r.text
    assert r.text.index("DC-2026-001") < r.text.index("DC-2026-002")


def test_plafond_billet_applique(client, db_session, deux_dossiers, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget",
                   params={"budget": "600000", "plafond_billet": "50000"})
    assert r.status_code == 200
    assert "plafonné" in r.text
    # Totaux financés : 2 × (144 000 + 50 000 + 20 000) = 428 000 DA.
    assert "428\u00a0000\u00a0DA" in r.text


def test_montants_avec_espaces_et_virgule(client, db_session, deux_dossiers,
                                          membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget", params={"budget": "600 000,00"})
    assert r.status_code == 200
    assert "72\u00a0000\u00a0DA" in r.text


def test_budget_invalide(client, db_session, campaign, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/budget", params={"budget": "abc"})
    assert r.status_code == 200
    assert "Montant invalide" in r.text
    r = client.get("/commission/budget", params={"budget": "-5"})
    assert r.status_code == 200
    assert "strictement positive" in r.text
