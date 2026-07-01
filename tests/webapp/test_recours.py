"""Phase de recours : dépôt (enseignant), traitement (responsable), garde-fous."""

import pytest
from sqlalchemy import select

from tests.webapp.conftest import PASSWORD, login
from webapp.models import Dossier, Entry, Recours, User
from webapp.security import hash_password


@pytest.fixture()
def dossier_examine(db_session, campaign, dossier):
    """Dossier soumis + examiné, campagne en phase de recours (résultats provisoires).

    Deux éléments décidés : rang validé, une publication rejetée (motivée).
    """
    db_session.add_all([
        Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
              payload={"value": "professeur"}, statut="valide"),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_b",
              payload={"count": 1, "author_position": 1, "date": "2025-02-01",
                       "intitule": "Article B"},
              statut="rejete", decision_motif="Hors fenêtre"),
    ])
    dossier.statut = "soumis"
    campaign.statut = "cloturee"
    campaign.recours_ouverts = True
    db_session.commit()
    db_session.refresh(dossier)
    return dossier


def _entry(db_session, item_id="classe_b"):
    return db_session.scalar(select(Entry).where(Entry.item_id == item_id))


def _rang_entry(db_session):
    return db_session.scalar(select(Entry).where(Entry.criterion_id == "rang_scientifique"))


# ---------------------------------------------------------------------------
# Dépôt (enseignant)
# ---------------------------------------------------------------------------


def test_depot_recours(client, db_session, dossier_examine, enseignant):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    r = client.post(f"/mon-dossier/recours/{entry.id}",
                    data={"motif": "desaccord_rejet", "message": "La date est bien dans la fenêtre."})
    assert r.status_code == 200
    rec = db_session.scalar(select(Recours))
    assert rec is not None
    assert rec.entry_id == entry.id
    assert rec.statut == "ouvert"
    assert rec.created_by == enseignant.id


def test_depot_hors_fenetre_refuse(client, db_session, campaign, dossier_examine, enseignant):
    campaign.recours_ouverts = False
    db_session.commit()
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    r = client.post(f"/mon-dossier/recours/{entry.id}",
                    data={"motif": "autre", "message": "test"})
    assert r.status_code == 403


def test_depot_message_obligatoire(client, db_session, dossier_examine, enseignant):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    r = client.post(f"/mon-dossier/recours/{entry.id}",
                    data={"motif": "autre", "message": "   "})
    assert r.status_code == 422


def test_un_seul_recours_ouvert_par_element(client, db_session, dossier_examine, enseignant):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "premier"})
    r = client.post(f"/mon-dossier/recours/{entry.id}",
                    data={"motif": "autre", "message": "deuxième"})
    assert r.status_code == 409


def test_recours_sur_element_autrui_refuse(client, db_session, campaign, dossier_examine, enseignant):
    """Un enseignant ne peut pas contester un élément d'un autre dossier."""
    autre = User(email="autre@test.dz", password_hash=hash_password(PASSWORD),
                 nom="Autre", prenom="", role="enseignant")
    db_session.add(autre)
    db_session.commit()
    autre_dossier = Dossier(campaign_id=campaign.id, user_id=autre.id,
                            candidate_ref="DC-2026-050", statut="soumis")
    db_session.add(autre_dossier)
    db_session.commit()
    autre_entry = Entry(dossier_id=autre_dossier.id, criterion_id="rang_scientifique",
                        payload={"value": "mca"}, statut="valide")
    db_session.add(autre_entry)
    db_session.commit()
    login(client, "enseignant@test.dz")
    r = client.post(f"/mon-dossier/recours/{autre_entry.id}",
                    data={"motif": "autre", "message": "pas le mien"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Retrait (enseignant)
# ---------------------------------------------------------------------------


def test_retrait_recours_ouvert(client, db_session, dossier_examine, enseignant):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "autre", "message": "à retirer"})
    rec = db_session.scalar(select(Recours))
    r = client.request("DELETE", f"/mon-dossier/recours/{rec.id}")
    assert r.status_code == 200
    db_session.refresh(rec)
    assert rec.statut == "retire"
    # Un recours retiré libère la possibilité d'en redéposer un.
    r = client.post(f"/mon-dossier/recours/{entry.id}",
                    data={"motif": "autre", "message": "à nouveau"})
    assert r.status_code == 200


def test_retrait_apres_decision_refuse(client, db_session, dossier_examine, enseignant, responsable):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    rec = db_session.scalar(select(Recours))
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    client.post(f"/commission/recours/{rec.id}/decision",
                data={"decision": "rejete", "reponse_motif": "Décision maintenue."})
    client.post("/deconnexion")
    login(client, "enseignant@test.dz")
    r = client.request("DELETE", f"/mon-dossier/recours/{rec.id}")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Traitement (responsable)
# ---------------------------------------------------------------------------


def test_reponse_obligatoire(client, db_session, dossier_examine, enseignant, responsable):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    rec = db_session.scalar(select(Recours))
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/recours/{rec.id}/decision",
                    data={"decision": "accepte", "reponse_motif": "  "})
    assert r.status_code == 422


def test_accept_recours_ne_touche_pas_lelement(client, db_session, dossier_examine,
                                               enseignant, responsable):
    """Acceptation = marqueur d'issue ; l'élément n'est pas modifié par cette décision."""
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    rec = db_session.scalar(select(Recours))
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/recours/{rec.id}/decision",
                    data={"decision": "accepte", "reponse_motif": "Recours fondé."})
    assert r.status_code == 303
    db_session.refresh(rec)
    db_session.refresh(entry)
    assert rec.statut == "accepte"
    assert rec.decided_by == responsable.id
    # L'élément reste tel quel : la correction se fait ensuite via les décisions.
    assert entry.statut == "rejete"


def test_file_recours_interdite_au_membre(client, db_session, dossier_examine, membre_commission):
    login(client, "commission@test.dz")
    assert client.get("/commission/recours").status_code == 403


def test_file_recours_visible_au_responsable(client, db_session, dossier_examine,
                                             enseignant, responsable):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "argument du candidat"})
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    r = client.get("/commission/recours")
    assert r.status_code == 200
    assert dossier_examine.candidate_ref in r.text
    assert "argument du candidat" in r.text


# ---------------------------------------------------------------------------
# Fenêtre de recours (responsable)
# ---------------------------------------------------------------------------


def test_ouvrir_fermer_fenetre(client, db_session, campaign, dossier, responsable):
    campaign.statut = "cloturee"
    campaign.recours_ouverts = False
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.post("/commission/recours/fenetre",
                    data={"action": "ouvrir", "recours_deadline": "2026-07-15"})
    assert r.status_code == 303
    db_session.refresh(campaign)
    assert campaign.recours_ouverts is True
    assert campaign.recours_deadline.isoformat() == "2026-07-15"
    r = client.post("/commission/recours/fenetre", data={"action": "fermer"})
    assert r.status_code == 303
    db_session.refresh(campaign)
    assert campaign.recours_ouverts is False


def test_ouvrir_refuse_si_saisie_ouverte(client, db_session, campaign, responsable):
    login(client, "responsable@test.dz")  # campagne « ouverte » par défaut
    r = client.post("/commission/recours/fenetre", data={"action": "ouvrir"})
    assert r.status_code == 422


def test_admin_ouvre_ferme_fenetre(client, db_session, campaign, dossier, admin):
    campaign.statut = "cloturee"
    campaign.recours_ouverts = False
    db_session.commit()
    login(client, "admin@test.dz")
    r = client.post("/admin/campagne/recours",
                    data={"action": "ouvrir", "recours_deadline": "2026-07-20"})
    assert r.status_code == 303
    db_session.refresh(campaign)
    assert campaign.recours_ouverts is True
    assert campaign.recours_deadline.isoformat() == "2026-07-20"
    r = client.post("/admin/campagne/recours", data={"action": "fermer"})
    assert r.status_code == 303
    db_session.refresh(campaign)
    assert campaign.recours_ouverts is False


def test_admin_ouvre_refuse_si_non_cloturee(client, db_session, campaign, admin):
    login(client, "admin@test.dz")  # campagne « ouverte »
    r = client.post("/admin/campagne/recours", data={"action": "ouvrir"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Notifications e-mail
# ---------------------------------------------------------------------------


def test_depot_notifie_responsable(client, db_session, dossier_examine, enseignant,
                                   responsable, monkeypatch):
    from webapp.services import mailer

    envois = []
    monkeypatch.setattr(mailer, "notify",
                        lambda to, subject, body, **k: envois.append(to) or True)
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    assert responsable.email in envois


def test_decision_notifie_enseignant(client, db_session, dossier_examine, enseignant,
                                     responsable, monkeypatch):
    from webapp.services import mailer

    envois = []
    monkeypatch.setattr(mailer, "notify",
                        lambda to, subject, body, **k: envois.append(to) or True)
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    rec = db_session.scalar(select(Recours))
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    client.post(f"/commission/recours/{rec.id}/decision",
                data={"decision": "accepte", "reponse_motif": "Recours fondé."})
    assert enseignant.email in envois


# ---------------------------------------------------------------------------
# Garde-fou du gel
# ---------------------------------------------------------------------------


def test_gel_bloque_si_recours_ouvert(client, db_session, dossier_examine, enseignant, responsable):
    login(client, "enseignant@test.dz")
    entry = _entry(db_session)
    client.post(f"/mon-dossier/recours/{entry.id}",
                data={"motif": "desaccord_rejet", "message": "conteste"})
    rec = db_session.scalar(select(Recours))
    client.post("/deconnexion")
    login(client, "responsable@test.dz")
    r = client.post("/commission/classement/geler")
    assert r.status_code == 403
    assert "recours" in r.text.lower()
    # Après traitement du recours, le gel redevient possible.
    client.post(f"/commission/recours/{rec.id}/decision",
                data={"decision": "rejete", "reponse_motif": "Décision maintenue."})
    r = client.post("/commission/classement/geler")
    assert r.status_code == 303


# ---------------------------------------------------------------------------
# Classement provisoire côté enseignant
# ---------------------------------------------------------------------------


def test_classement_provisoire_visible(client, db_session, dossier_examine, enseignant):
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier/classement")
    assert r.status_code == 200
    assert "provisoire" in r.text.lower()
    assert dossier_examine.candidate_ref in r.text


def test_classement_masque_hors_phase(client, db_session, campaign, dossier_examine, enseignant):
    campaign.recours_ouverts = False
    db_session.commit()
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier/classement")
    assert r.status_code == 200
    assert "n'est pas encore publié" in r.text


def test_classement_cache_le_detail_dautrui(client, db_session, campaign, dossier_examine,
                                             enseignant):
    """La liste montre réf + score des autres, jamais le détail de leurs éléments."""
    autre = User(email="autre@test.dz", password_hash=hash_password(PASSWORD),
                 nom="Zorro", prenom="", role="enseignant")
    db_session.add(autre)
    db_session.commit()
    autre_dossier = Dossier(campaign_id=campaign.id, user_id=autre.id,
                            candidate_ref="DC-2026-050", population="enseignant_chercheur",
                            statut="soumis")
    db_session.add(autre_dossier)
    db_session.commit()
    db_session.add(Entry(dossier_id=autre_dossier.id, criterion_id="publications",
                         item_id="classe_a_plus",
                         payload={"count": 1, "author_position": 1, "date": "2025-01-01",
                                  "intitule": "INTITULE-SECRET"}, statut="valide"))
    db_session.commit()
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier/classement")
    assert r.status_code == 200
    assert "DC-2026-050" in r.text          # réf de l'autre candidat visible
    assert "Zorro" in r.text                # nom visible
    assert "INTITULE-SECRET" not in r.text  # détail de ses éléments masqué
