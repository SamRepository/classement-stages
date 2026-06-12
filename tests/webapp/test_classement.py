"""Classement, gel et exports officiels."""

import pytest
from sqlalchemy import select

from tests.webapp.conftest import login
from webapp.models import Dossier, Entry, RankingSnapshot, User
from webapp.security import hash_password


@pytest.fixture()
def deux_dossiers_soumis(db_session, campaign, dossier, enseignant):
    autre = User(email="autre@test.dz", password_hash=hash_password("x"),
                 nom="Cherif", prenom="Amine", role="enseignant")
    db_session.add(autre)
    db_session.commit()
    d2 = Dossier(campaign_id=campaign.id, user_id=autre.id,
                 candidate_ref="DC-2026-002", departement="technologie")
    db_session.add(d2)
    db_session.flush()
    db_session.add_all([
        Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
              payload={"value": "professeur"}, statut="valide"),
        Entry(dossier_id=d2.id, criterion_id="rang_scientifique",
              payload={"value": "mca"}, statut="valide"),
    ])
    dossier.statut = "soumis"
    d2.statut = "soumis"
    db_session.commit()
    db_session.refresh(dossier)
    return dossier, d2


def test_page_classement(client, db_session, campaign, deux_dossiers_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/classement")
    assert r.status_code == 200
    assert "DC-2026-001" in r.text and "DC-2026-002" in r.text
    assert "Geler le classement" in r.text


def test_gel_refuse_si_en_attente(client, db_session, campaign, deux_dossiers_soumis,
                                  membre_commission):
    d1, _ = deux_dossiers_soumis
    db_session.add(Entry(dossier_id=d1.id, criterion_id="projet_international",
                         item_id="projet_intl", payload={"count": 1}))  # en_attente
    db_session.commit()
    login(client, "commission@test.dz")
    r = client.post("/commission/classement/geler")
    assert r.status_code == 403
    assert "en attente" in r.text


def test_gel_et_snapshot(client, db_session, campaign, deux_dossiers_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.post("/commission/classement/geler")
    assert r.status_code == 303
    db_session.expire_all()
    assert campaign.statut == "gelee"
    statuts = set(db_session.scalars(select(Dossier.statut)))
    assert statuts == {"gele"}
    snapshot = db_session.scalar(select(RankingSnapshot))
    assert snapshot is not None
    cle = next(iter(snapshot.payload["groups"]))
    ranked = snapshot.payload["groups"][cle]
    assert [r["candidate_id"] for r in ranked] == ["DC-2026-001", "DC-2026-002"]

    # Après gel : plus de décision possible.
    entry = db_session.scalar(select(Entry))
    r = client.post(f"/commission/entrees/{entry.id}/decision",
                    data={"statut": "rejete", "motif": "x"})
    assert r.status_code == 403
    # Et pas de second gel.
    r = client.post("/commission/classement/geler")
    assert r.status_code == 400


def test_exports(client, db_session, campaign, deux_dossiers_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/exports/pv.xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(r.content) > 1000  # classeur non vide

    r = client.get("/commission/exports/fiches.xlsx")
    assert r.status_code == 200

    r = client.get("/commission/exports/classement.html")
    assert r.status_code == 200
    assert "DC-2026-001" in r.text

    r = client.get("/commission/exports/inconnu.zip")
    assert r.status_code == 404
