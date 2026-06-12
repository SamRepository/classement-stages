"""Examen commission : décisions motivées, recalcul, garde-fous."""

import pytest
from sqlalchemy import select

from tests.webapp.conftest import login
from webapp.models import Entry


@pytest.fixture()
def dossier_soumis(db_session, dossier):
    db_session.add_all([
        Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
              payload={"value": "professeur"}),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_a_plus",
              payload={"count": 1, "author_position": 1, "date": "2025-01-01", "doi": "10.1/a"}),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_b",
              payload={"count": 1, "author_position": 1, "date": "2025-02-01"}),
    ])
    dossier.statut = "soumis"
    db_session.commit()
    db_session.refresh(dossier)
    return dossier


def test_liste_et_vue_dossier(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/dossiers")
    assert r.status_code == 200
    assert dossier_soumis.candidate_ref in r.text
    # score commission affiché : 7 (professeur) + 20 (A+) + 10 (B) + pénalité 3 = 40
    r = client.get(f"/commission/dossiers/{dossier_soumis.id}")
    assert r.status_code == 200
    assert "Score commission" in r.text
    assert "en attente" in r.text


def test_rejet_sans_motif_refuse(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "rejete"})
    assert r.status_code == 422
    assert "motivé" in r.text


def test_rejet_motive_exclut_du_score(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/decision",
                    data={"statut": "rejete", "motif": "Justificatif manquant"})
    assert r.status_code == 200
    assert "Justificatif manquant" in r.text  # motif affiché sur l'élément
    assert "score-box" in r.text              # score recalculé en oob
    db_session.refresh(entry)
    assert entry.statut == "rejete"
    assert entry.decided_by == membre_commission.id

    # Le score commission n'inclut plus la classe_b (10 pts).
    r = client.get(f"/commission/dossiers/{dossier_soumis.id}/score")
    assert "Éléments rejetés" in r.text


def test_annulation_decision(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    client.post(f"/commission/entrees/{entry.id}/decision",
                data={"statut": "rejete", "motif": "Erreur"})
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "en_attente"})
    assert r.status_code == 200
    db_session.refresh(entry)
    assert entry.statut == "en_attente"
    assert entry.decision_motif is None


def test_tout_valider(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.post(f"/commission/dossiers/{dossier_soumis.id}/tout-valider")
    assert r.status_code == 303
    statuts = set(db_session.scalars(select(Entry.statut)))
    assert statuts == {"valide"}


def test_decision_sur_brouillon_refusee(client, db_session, campaign, dossier, membre_commission):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "mca"}))
    db_session.commit()
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry))
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "valide"})
    assert r.status_code == 403


def test_enseignant_voit_motif_apres_examen(client, db_session, campaign, dossier_soumis,
                                            membre_commission, enseignant):
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    client.post(f"/commission/entrees/{entry.id}/decision",
                data={"statut": "rejete", "motif": "Hors fenêtre"})
    client.post("/deconnexion")
    # L'espace enseignant reste accessible en lecture (dossier soumis).
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 200


def test_commission_interdite_aux_enseignants(client, campaign, dossier_soumis, enseignant):
    login(client, "enseignant@test.dz")
    assert client.get("/commission/dossiers").status_code == 403
    entry_id = 1
    assert client.post(f"/commission/entrees/{entry_id}/decision",
                       data={"statut": "valide"}).status_code == 403
