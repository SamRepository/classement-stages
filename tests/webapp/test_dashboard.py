"""Tableau de bord commission : accès par rôle et agrégats (déclaré / retenu)."""

import pytest
from sqlalchemy import select

from tests.webapp.conftest import login
from webapp.models import Dossier, ElementReview, Entry, User
from webapp.security import hash_password


@pytest.fixture()
def dossier_soumis(db_session, dossier):
    """Un dossier soumis avec trois publications (A+, A, B) et un rang."""
    db_session.add_all([
        Entry(dossier_id=dossier.id, criterion_id="rang_scientifique",
              payload={"value": "professeur"}),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_a_plus",
              payload={"count": 1, "date": "2025-01-01"}),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_a",
              payload={"count": 2, "date": "2025-02-01"}),
        Entry(dossier_id=dossier.id, criterion_id="publications", item_id="classe_b",
              payload={"count": 1, "date": "2025-03-01"}),
        Entry(dossier_id=dossier.id, criterion_id="communications",
              item_id="intl_indexee_scopus_wos",
              payload={"count": 1, "date": "2025-04-01"}),
    ])
    dossier.statut = "soumis"
    db_session.commit()
    db_session.refresh(dossier)
    return dossier


def test_membre_voit_le_tableau(client, db_session, campaign, dossier_soumis,
                                membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/tableau-de-bord")
    assert r.status_code == 200
    assert "Avancement administratif" in r.text
    assert "Production scientifique" in r.text
    # Postes scientifiques dérivés de la grille (publications + communications).
    assert "Publications" in r.text
    assert "Revue classe A+" in r.text


def test_membre_ne_voit_pas_la_relecture(client, db_session, campaign, dossier_soumis,
                                         membre_commission):
    """La répartition de la relecture est réservée au responsable."""
    login(client, "commission@test.dz")
    r = client.get("/commission/tableau-de-bord")
    assert r.status_code == 200
    assert "réservé au responsable" not in r.text


def test_responsable_voit_la_relecture(client, db_session, campaign, dossier_soumis,
                                       responsable, membre_commission):
    dossier_soumis.assigned_reviewer_id = membre_commission.id
    db_session.commit()
    login(client, "responsable@test.dz")
    r = client.get("/commission/tableau-de-bord")
    assert r.status_code == 200
    assert "réservé au responsable" in r.text
    assert membre_commission.nom in r.text


def test_enseignant_interdit(client, campaign, dossier_soumis, enseignant):
    login(client, "enseignant@test.dz")
    assert client.get("/commission/tableau-de-bord").status_code == 403


def test_declare_vs_retenu_diverge_apres_rejet(client, db_session, campaign,
                                               dossier_soumis, responsable):
    """Rejeter une publication réduit « retenu » sans toucher « déclaré »."""
    from webapp.services.dashboard import build_dashboard

    campaign = db_session.get(type(campaign), campaign.id)
    data = build_dashboard(db_session, campaign)
    pubs = next(s for s in data["scientifique"] if s["criterion_id"] == "publications")
    assert pubs["declare"] == 4  # 1 (A+) + 2 (A) + 1 (B)
    assert pubs["retenu"] == 4   # rien de rejeté encore

    # Le responsable rejette la classe A+ (count 1).
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_a_plus"))
    client.post(f"/commission/entrees/{entry.id}/decision",
                data={"statut": "rejete", "motif": "Justificatif manquant"})

    data = build_dashboard(db_session, campaign)
    pubs = next(s for s in data["scientifique"] if s["criterion_id"] == "publications")
    assert pubs["declare"] == 4  # inchangé : l'élément reste déclaré
    assert pubs["retenu"] == 3   # A+ (1) exclu du retenu


def test_examen_ignore_les_brouillons(client, db_session, campaign, enseignant):
    """Un dossier en brouillon compte dans la participation mais pas dans l'examen."""
    from webapp.services.dashboard import build_dashboard

    brouillon = Dossier(campaign_id=campaign.id, user_id=enseignant.id,
                        candidate_ref="DC-2026-999", statut="brouillon")
    db_session.add(brouillon)
    db_session.flush()
    db_session.add(Entry(dossier_id=brouillon.id, criterion_id="publications",
                         item_id="classe_a", payload={"count": 3}))
    db_session.commit()

    data = build_dashboard(db_session, campaign)
    assert data["dossiers"]["brouillon"] == 1
    assert data["examen"]["total"] == 0          # rien d'examinable
    assert data["scientifique"] == []            # rien de soumis → aucun poste


def test_scientifique_masque_les_criteres_vides(client, db_session, campaign,
                                                dossier_soumis):
    """Seuls les critères ayant au moins un élément déclaré apparaissent."""
    from webapp.services.dashboard import build_dashboard

    campaign = db_session.get(type(campaign), campaign.id)
    data = build_dashboard(db_session, campaign)
    critere_ids = {s["criterion_id"] for s in data["scientifique"]}
    assert "publications" in critere_ids
    assert "communications" in critere_ids
    assert "encadrement_doctoral" not in critere_ids  # rien déclaré


def _autre_dossier(db_session, campaign, nb_pubs=1):
    """Second candidat soumis avec ``nb_pubs`` publications de classe C."""
    u = User(email=f"c{nb_pubs}@test.dz", password_hash=hash_password("x"),
             nom=f"Autre{nb_pubs}", prenom="X", role="enseignant")
    db_session.add(u)
    db_session.flush()
    d = Dossier(campaign_id=campaign.id, user_id=u.id,
                candidate_ref=f"DC-2026-{nb_pubs:03d}", statut="soumis",
                population="enseignant_chercheur")
    db_session.add(d)
    db_session.flush()
    db_session.add(Entry(dossier_id=d.id, criterion_id="publications",
                         item_id="classe_c", payload={"count": nb_pubs}))
    db_session.commit()
    return d


def test_top_contributeurs_ordonnes(client, db_session, campaign, dossier_soumis):
    """Les contributeurs sont classés par total d'éléments retenus décroissant."""
    from webapp.services.dashboard import build_dashboard

    _autre_dossier(db_session, campaign, nb_pubs=2)
    campaign = db_session.get(type(campaign), campaign.id)
    data = build_dashboard(db_session, campaign)
    top = data["top_contributeurs"]
    # dossier_soumis : 4 pubs + 1 comm = 5 ; l'autre : 2. Ordre décroissant.
    assert [c["ref"] for c in top] == [dossier_soumis.candidate_ref, "DC-2026-002"]
    assert top[0]["total"] == 5
    assert top[1]["total"] == 2


def test_histogramme_distribution(client, db_session, campaign, dossier_soumis):
    """L'histogramme des publications ventile les candidats par tranche."""
    from webapp.services.dashboard import build_dashboard

    _autre_dossier(db_session, campaign, nb_pubs=2)  # 2 pubs → tranche « 2 »
    campaign = db_session.get(type(campaign), campaign.id)
    data = build_dashboard(db_session, campaign)
    pubs = next(h for h in data["histogrammes"] if h["criterion_id"] == "publications")
    # dossier_soumis a 4 publications retenues → tranche « 4 » ; l'autre → « 2 ».
    assert pubs["buckets"]["4"] == 1
    assert pubs["buckets"]["2"] == 1
    assert pubs["buckets"]["0"] == 0


def test_export_csv(client, db_session, campaign, dossier_soumis, membre_commission):
    login(client, "commission@test.dz")
    r = client.get("/commission/tableau-de-bord/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    corps = r.content.decode("utf-8-sig")
    assert "Indicateurs administratifs" in corps
    assert "Production scientifique" in corps
    assert "Détail par candidat" in corps
    assert dossier_soumis.candidate_ref in corps
    assert "Revue classe A+" in corps


def test_export_csv_retenu_apres_rejet(client, db_session, campaign, dossier_soumis,
                                       responsable):
    """Le CSV reflète le retenu (élément rejeté retiré de la colonne retenu)."""
    login(client, "responsable@test.dz")
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_a_plus"))
    client.post(f"/commission/entrees/{entry.id}/decision",
                data={"statut": "rejete", "motif": "Justificatif manquant"})
    r = client.get("/commission/tableau-de-bord/export.csv")
    corps = r.content.decode("utf-8-sig")
    # Ligne « <critère publications>;Total;<declare>;<retenu> » : 4 déclaré, 3 retenu.
    assert ";Total;4;3" in corps


def test_export_csv_interdit_enseignant(client, campaign, dossier_soumis, enseignant):
    login(client, "enseignant@test.dz")
    assert client.get("/commission/tableau-de-bord/export.csv").status_code == 403


def test_avis_agreges_par_conformite(client, db_session, campaign, dossier_soumis,
                                     membre_commission):
    """Les avis des relecteurs sont ventilés conforme / non conforme / à expliquer."""
    from webapp.services.dashboard import build_dashboard

    entries = list(db_session.scalars(
        select(Entry).where(Entry.criterion_id == "publications")))
    db_session.add_all([
        ElementReview(entry_id=entries[0].id, reviewer_id=membre_commission.id, flag="ok"),
        ElementReview(entry_id=entries[1].id, reviewer_id=membre_commission.id, flag="pas_ok"),
        ElementReview(entry_id=entries[2].id, reviewer_id=membre_commission.id,
                      flag="explication"),
    ])
    db_session.commit()

    campaign = db_session.get(type(campaign), campaign.id)
    avis = build_dashboard(db_session, campaign)["avis"]
    assert avis["ok"] == 1
    assert avis["pas_ok"] == 1
    assert avis["explication"] == 1
    assert avis["total"] == 3


def test_avis_dans_le_dashboard(client, db_session, campaign, dossier_soumis,
                                membre_commission):
    """La page rend la section « Avis des relecteurs »."""
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    db_session.add(ElementReview(entry_id=entry.id, reviewer_id=membre_commission.id,
                                 flag="ok"))
    db_session.commit()
    login(client, "commission@test.dz")
    r = client.get("/commission/tableau-de-bord")
    assert r.status_code == 200
    assert "Avis des relecteurs" in r.text
    assert "non conformes" in r.text


def test_avis_dans_le_csv(client, db_session, campaign, dossier_soumis, membre_commission):
    entry = db_session.scalar(select(Entry).where(Entry.item_id == "classe_b"))
    db_session.add(ElementReview(entry_id=entry.id, reviewer_id=membre_commission.id,
                                 flag="pas_ok"))
    db_session.commit()
    login(client, "commission@test.dz")
    corps = client.get("/commission/tableau-de-bord/export.csv").content.decode("utf-8-sig")
    assert "Avis non conformes;1" in corps


def test_destinations_camembert(client, db_session, campaign, enseignant):
    """Les pays de destination sont agrégés en parts (soumis/gelés, pays renseigné)."""
    from webapp.services.dashboard import build_dashboard

    def _dossier(ref, pays, statut="soumis"):
        u = User(email=f"{ref}@test.dz", password_hash=hash_password("x"),
                 nom=ref, prenom="X", role="enseignant")
        db_session.add(u)
        db_session.flush()
        db_session.add(Dossier(campaign_id=campaign.id, user_id=u.id,
                               candidate_ref=ref, statut=statut, pays=pays))

    _dossier("A", "France")
    _dossier("B", "France")
    _dossier("C", "Canada")
    _dossier("D", None)                 # pays non renseigné → ignoré
    _dossier("E", "Italie", "brouillon")  # brouillon → ignoré
    db_session.commit()

    data = build_dashboard(db_session, campaign)
    dest = data["destinations"]
    assert dest["total"] == 3  # France×2 + Canada×1
    assert dest["full"] is None
    parts = {s["pays"]: s["count"] for s in dest["slices"]}
    assert parts == {"France": 2, "Canada": 1}
    # France en tête (tri décroissant) et chemin SVG présent.
    assert dest["slices"][0]["pays"] == "France"
    assert dest["slices"][0]["path"].startswith("M")


def test_destinations_pays_unique_cercle_plein(client, db_session, campaign, enseignant):
    """Une seule destination → cercle plein (pas d'arc dégénéré)."""
    from webapp.services.dashboard import build_dashboard

    db_session.add(Dossier(campaign_id=campaign.id, user_id=enseignant.id,
                           candidate_ref="Z", statut="soumis", pays="Tunisie"))
    db_session.commit()
    dest = build_dashboard(db_session, campaign)["destinations"]
    assert dest["full"] is not None
    assert dest["full"]["pays"] == "Tunisie"


def test_destinations_regroupe_en_autres(client, db_session, campaign):
    """Au-delà de 7 pays, le reste est regroupé en « Autres »."""
    from webapp.services.dashboard import build_dashboard

    for i in range(9):
        u = User(email=f"p{i}@test.dz", password_hash=hash_password("x"),
                 nom=f"P{i}", prenom="X", role="enseignant")
        db_session.add(u)
        db_session.flush()
        db_session.add(Dossier(campaign_id=campaign.id, user_id=u.id,
                               candidate_ref=f"P{i}", statut="soumis", pays=f"Pays{i}"))
    db_session.commit()
    dest = build_dashboard(db_session, campaign)["destinations"]
    assert len(dest["slices"]) == 8  # 7 pays + « Autres »
    assert dest["slices"][-1]["pays"] == "Autres"
    assert dest["total"] == 9


def test_dashboard_affiche_camembert(client, db_session, campaign, dossier_soumis,
                                     membre_commission):
    """La page rend la section pays de destination."""
    dossier_soumis.pays = "France"
    db_session.commit()
    login(client, "commission@test.dz")
    r = client.get("/commission/tableau-de-bord")
    assert r.status_code == 200
    assert "Pays de destination" in r.text
    assert "dest-pie" in r.text


def test_jamais_connectes(client, db_session, campaign, enseignant):
    """Compte les enseignants actifs jamais connectés (last_login_at NULL)."""
    from webapp.services.dashboard import build_dashboard

    # enseignant fixture : last_login_at NULL par défaut.
    connecte = User(email="vu@test.dz", password_hash=hash_password("x"),
                    nom="Vu", prenom="Deja", role="enseignant")
    from datetime import datetime, timezone
    connecte.last_login_at = datetime.now(timezone.utc)
    db_session.add(connecte)
    db_session.commit()

    data = build_dashboard(db_session, campaign)
    assert data["jamais_connectes"] == 1  # seul « enseignant » n'a jamais ouvert
