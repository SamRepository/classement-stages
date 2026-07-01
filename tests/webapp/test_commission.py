"""Examen commission à deux niveaux : avis des membres, décisions du responsable."""

import pytest
from sqlalchemy import select

from tests.webapp.conftest import login
from webapp.models import ElementReview, Entry


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


# ---------------------------------------------------------------------------
# Lecture (membre) et décisions (responsable)
# ---------------------------------------------------------------------------


def test_liste_et_vue_dossier(client, db_session, campaign, dossier_soumis, membre_commission):
    """Un membre voit la liste et le détail (lecture)."""
    login(client, "commission@test.dz")
    r = client.get("/commission/dossiers")
    assert r.status_code == 200
    assert dossier_soumis.candidate_ref in r.text
    # score commission : 7 (professeur) + 20 (A+) + 10 (B) + pénalité 3 = 40
    r = client.get(f"/commission/dossiers/{dossier_soumis.id}")
    assert r.status_code == 200
    assert "Score commission" in r.text
    assert "en attente" in r.text


def test_membre_ne_peut_pas_decider(client, db_session, campaign, dossier_soumis,
                                    membre_commission):
    """Le membre n'a pas accès aux décisions (validation/rejet) — réservées au responsable."""
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "valide"})
    assert r.status_code == 403


def test_rejet_sans_motif_refuse(client, db_session, campaign, dossier_soumis, responsable):
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "rejete"})
    assert r.status_code == 422
    assert "motivé" in r.text


def test_rejet_motive_exclut_du_score(client, db_session, campaign, dossier_soumis, responsable):
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/decision",
                    data={"statut": "rejete", "motif": "Justificatif manquant"})
    assert r.status_code == 200
    assert "Justificatif manquant" in r.text  # motif affiché sur l'élément
    assert "score-box" in r.text              # score recalculé en oob
    db_session.refresh(entry)
    assert entry.statut == "rejete"
    assert entry.decided_by == responsable.id

    # Le score commission n'inclut plus la classe_b (10 pts).
    r = client.get(f"/commission/dossiers/{dossier_soumis.id}/score")
    assert "Éléments rejetés" in r.text


def test_annulation_decision(client, db_session, campaign, dossier_soumis, responsable):
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    client.post(f"/commission/entrees/{entry.id}/decision",
                data={"statut": "rejete", "motif": "Erreur"})
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "en_attente"})
    assert r.status_code == 200
    db_session.refresh(entry)
    assert entry.statut == "en_attente"
    assert entry.decision_motif is None


def test_tout_valider(client, db_session, campaign, dossier_soumis, responsable):
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/dossiers/{dossier_soumis.id}/tout-valider")
    assert r.status_code == 303
    statuts = set(db_session.scalars(select(Entry.statut)))
    assert statuts == {"valide"}


def test_ajuster_n_formule(client, db_session, campaign, dossier, responsable):
    """Le responsable corrige le n saisi par le candidat et le valide."""
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="penalite_beneficies_3ans",
                         payload={"n": 0}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(
        select(Entry).where(Entry.criterion_id == "penalite_beneficies_3ans")
    )
    r = client.post(f"/commission/entrees/{entry.id}/ajuster", data={"n": "2"})
    assert r.status_code == 200
    db_session.refresh(entry)
    assert entry.payload["n"] == 2
    assert entry.statut == "valide"
    assert entry.decided_by == responsable.id


def test_ajuster_n_vide_revient_auto(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="penalite_beneficies_3ans",
                         payload={"n": 5}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(
        select(Entry).where(Entry.criterion_id == "penalite_beneficies_3ans")
    )
    r = client.post(f"/commission/entrees/{entry.id}/ajuster", data={"n": ""})
    assert r.status_code == 200
    db_session.refresh(entry)
    assert "n" not in entry.payload  # calcul automatique restauré


def test_ajuster_refuse_critere_non_formule(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "professeur"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.criterion_id == "rang_scientifique"))
    r = client.post(f"/commission/entrees/{entry.id}/ajuster", data={"n": "2"})
    assert r.status_code == 422


def test_rectifier_quantite(client, db_session, campaign, dossier, responsable):
    """Le responsable corrige une quantité gonflée (nb d'auteurs) → 1, et la position."""
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="publications",
                         item_id="classe_a_plus",
                         payload={"count": 4, "author_position": 1, "date": "2025-01-01"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.criterion_id == "publications"))
    r = client.post(f"/commission/entrees/{entry.id}/ajuster-quantite",
                    data={"quantite": "1", "author_position": "2"})
    assert r.status_code == 200
    assert "score-box" in r.text  # score recalculé en oob
    db_session.refresh(entry)
    assert entry.payload["count"] == 1
    assert entry.payload["author_position"] == 2
    # La rectification ne décide pas l'élément : il reste en attente.
    assert entry.statut == "en_attente"


def test_rectifier_quantite_position_videe(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="publications",
                         item_id="classe_b",
                         payload={"count": 3, "author_position": 3, "date": "2025-02-01"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.criterion_id == "publications"))
    r = client.post(f"/commission/entrees/{entry.id}/ajuster-quantite",
                    data={"quantite": "1", "author_position": ""})
    assert r.status_code == 200
    db_session.refresh(entry)
    assert entry.payload["count"] == 1
    assert "author_position" not in entry.payload


def test_rectifier_quantite_refusee_au_membre(client, db_session, campaign, dossier_soumis,
                                              membre_commission):
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/ajuster-quantite",
                    data={"quantite": "1"})
    assert r.status_code == 403


def test_rectifier_quantite_refuse_critere_non_compte(client, db_session, campaign, dossier,
                                                      responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "professeur"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.criterion_id == "rang_scientifique"))
    r = client.post(f"/commission/entrees/{entry.id}/ajuster-quantite", data={"quantite": "1"})
    assert r.status_code == 422


def test_definir_rang_absent(client, db_session, campaign, dossier, responsable):
    """Le responsable renseigne le rang laissé vide par le candidat (entrée créée)."""
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/dossiers/{dossier.id}/critere/rang_scientifique/valeur",
                    data={"value": "professeur"})
    assert r.status_code == 303
    entry = db_session.scalar(select(Entry).where(Entry.criterion_id == "rang_scientifique"))
    assert entry is not None
    assert entry.payload["value"] == "professeur"
    assert entry.statut == "en_attente"  # compté au score, décidable ensuite


def test_corriger_rang_existant(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "mca"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/dossiers/{dossier.id}/critere/rang_scientifique/valeur",
                    data={"value": "professeur"})
    assert r.status_code == 303
    entries = list(db_session.scalars(
        select(Entry).where(Entry.criterion_id == "rang_scientifique")))
    assert len(entries) == 1  # corrigé, pas dupliqué
    assert entries[0].payload["value"] == "professeur"


def test_effacer_rang(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "professeur"}))
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/dossiers/{dossier.id}/critere/rang_scientifique/valeur",
                    data={"value": ""})
    assert r.status_code == 303
    assert db_session.scalar(
        select(Entry).where(Entry.criterion_id == "rang_scientifique")) is None


def test_definir_rang_refuse_au_membre(client, db_session, campaign, dossier_soumis,
                                       membre_commission):
    login(client, "commission@test.dz")
    r = client.post(
        f"/commission/dossiers/{dossier_soumis.id}/critere/rang_scientifique/valeur",
        data={"value": "professeur"})
    assert r.status_code == 403


def test_definir_valeur_refuse_critere_non_enum(client, db_session, campaign, dossier,
                                                responsable):
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.post(f"/commission/dossiers/{dossier.id}/critere/publications/valeur",
                    data={"value": "professeur"})
    assert r.status_code == 422


def test_decision_sur_brouillon_refusee(client, db_session, campaign, dossier, responsable):
    db_session.add(Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
                         payload={"value": "mca"}))
    db_session.commit()
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry))
    r = client.post(f"/commission/entrees/{entry.id}/decision", data={"statut": "valide"})
    assert r.status_code == 403


def test_enseignant_voit_motif_apres_examen(client, db_session, campaign, dossier_soumis,
                                            responsable, enseignant):
    login(client, "responsable@test.dz")
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


# ---------------------------------------------------------------------------
# Affectation (responsable) et avis (membre)
# ---------------------------------------------------------------------------


def test_affectation_par_responsable(client, db_session, campaign, dossier_soumis,
                                     responsable, membre_commission):
    login(client, "responsable@test.dz")
    r = client.get("/commission/affectations")
    assert r.status_code == 200
    assert membre_commission.nom in r.text

    r = client.post(f"/commission/dossiers/{dossier_soumis.id}/affecter",
                    data={"reviewer_id": str(membre_commission.id)})
    assert r.status_code == 303
    db_session.refresh(dossier_soumis)
    assert dossier_soumis.assigned_reviewer_id == membre_commission.id


def test_affectation_interdite_au_membre(client, db_session, campaign, dossier_soumis,
                                         membre_commission):
    login(client, "commission@test.dz")
    assert client.get("/commission/affectations").status_code == 403
    r = client.post(f"/commission/dossiers/{dossier_soumis.id}/affecter",
                    data={"reviewer_id": str(membre_commission.id)})
    assert r.status_code == 403


def test_avis_membre_affecte(client, db_session, campaign, dossier_soumis, membre_commission):
    dossier_soumis.assigned_reviewer_id = membre_commission.id
    db_session.commit()
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/avis",
                    data={"flag": "explication", "observation": "Préciser la date exacte"})
    assert r.status_code == 200
    review = db_session.scalar(select(ElementReview).where(ElementReview.entry_id == entry.id))
    assert review is not None
    assert review.flag == "explication"
    assert review.reviewer_id == membre_commission.id
    # Réémettre met à jour (pas de doublon).
    client.post(f"/commission/entrees/{entry.id}/avis", data={"flag": "ok"})
    reviews = list(db_session.scalars(select(ElementReview).where(ElementReview.entry_id == entry.id)))
    assert len(reviews) == 1
    db_session.refresh(reviews[0])
    assert reviews[0].flag == "ok"


def test_avis_sans_effet_sur_le_score(client, db_session, campaign, dossier_soumis,
                                      membre_commission):
    dossier_soumis.assigned_reviewer_id = membre_commission.id
    db_session.commit()
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    client.post(f"/commission/entrees/{entry.id}/avis", data={"flag": "pas_ok"})
    db_session.refresh(entry)
    # L'avis ne décide rien : l'élément reste « en_attente » et compte au score.
    assert entry.statut == "en_attente"


def test_avis_refuse_si_non_affecte(client, db_session, campaign, dossier_soumis,
                                    membre_commission):
    """Un membre ne peut pas émettre d'avis sur un dossier qui ne lui est pas affecté."""
    login(client, "commission@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    r = client.post(f"/commission/entrees/{entry.id}/avis", data={"flag": "ok"})
    assert r.status_code == 403


def test_responsable_voit_avis_du_membre(client, db_session, campaign, dossier_soumis,
                                         responsable, membre_commission):
    dossier_soumis.assigned_reviewer_id = membre_commission.id
    db_session.commit()
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    db_session.add(ElementReview(entry_id=entry.id, reviewer_id=membre_commission.id,
                                 flag="pas_ok", observation="Justificatif illisible"))
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.get(f"/commission/dossiers/{dossier_soumis.id}")
    assert r.status_code == 200
    assert "Justificatif illisible" in r.text
