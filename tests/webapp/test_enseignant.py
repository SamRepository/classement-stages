"""Parcours enseignant : saisie, justificatifs, score provisoire, soumission."""

from sqlalchemy import select

from tests.webapp.conftest import PDF_BYTES, login
from webapp.models import Attachment, Entry


def test_page_dossier_cree_brouillon(client, db_session, campaign, enseignant):
    login(client, "enseignant@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 200
    assert "Score provisoire" not in r.text  # chargé via HTMX
    assert "brouillon" in r.text
    dossiers = db_session.scalars(select(__import__("webapp.models", fromlist=["Dossier"]).Dossier)).all()
    assert len(dossiers) == 1


def test_saisie_enum_et_score(client, db_session, campaign, enseignant):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    r = client.post("/mon-dossier/entrees/rang_scientifique",
                    data={"value": "professeur"})
    assert r.status_code == 200
    assert "score-box" in r.text  # fragment oob du score recalculé
    assert "7" in r.text
    entry = db_session.scalar(select(Entry))
    assert entry.criterion_id == "rang_scientifique"
    assert entry.payload == {"value": "professeur"}

    # Le score provisoire reflète la saisie.
    r = client.get("/mon-dossier/score")
    assert "7" in r.text


def test_enum_valeur_inconnue(client, campaign, enseignant):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    r = client.post("/mon-dossier/entrees/rang_scientifique", data={"value": "recteur"})
    assert r.status_code == 422


def test_activite_date_obligatoire_si_fenetre(client, campaign, enseignant):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    r = client.post("/mon-dossier/activites",
                    data={"criterion_id": "publications", "item": "classe_a"})
    assert r.status_code == 422
    assert "Date obligatoire" in r.text


def test_activite_avec_pdf(client, db_session, campaign, enseignant, upload_dir):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    r = client.post(
        "/mon-dossier/activites",
        data={"criterion_id": "publications", "item": "classe_a",
              "date": "2025-03-10", "author_position": "2",
              "doi": "10.1/x", "intitule": "Article test"},
        files={"fichier": ("preuve.pdf", PDF_BYTES, "application/pdf")},
    )
    assert r.status_code == 200
    entry = db_session.scalar(select(Entry))
    assert entry.item_id == "classe_a"
    assert entry.payload["author_position"] == 2
    attachment = db_session.scalar(select(Attachment))
    assert attachment.entry_id == entry.id
    assert (upload_dir / "justificatifs" / str(entry.dossier_id) / f"{entry.id}.pdf").is_file()

    # Le propriétaire télécharge son justificatif.
    r = client.get(f"/fichiers/justificatifs/{entry.id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_justificatif_pdf_invalide(client, campaign, enseignant, upload_dir):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    r = client.post(
        "/mon-dossier/activites",
        data={"criterion_id": "publications", "item": "classe_a", "date": "2025-03-10"},
        files={"fichier": ("preuve.pdf", b"pas un pdf", "application/pdf")},
    )
    assert r.status_code == 422
    assert "PDF" in r.text


def test_suppression_activite(client, db_session, campaign, enseignant, upload_dir):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    client.post(
        "/mon-dossier/activites",
        data={"criterion_id": "projet_international", "item": "projet_intl"},
        files={"fichier": ("p.pdf", PDF_BYTES, "application/pdf")},
    )
    entry = db_session.scalar(select(Entry))
    path = upload_dir / "justificatifs" / str(entry.dossier_id) / f"{entry.id}.pdf"
    assert path.is_file()
    r = client.delete(f"/mon-dossier/activites/{entry.id}")
    assert r.status_code == 200
    assert db_session.scalar(select(Entry)) is None
    assert not path.exists()


def test_soumission_gele_les_ecritures(client, db_session, campaign, enseignant):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    client.post("/mon-dossier/entrees/rang_scientifique", data={"value": "mca"})
    r = client.post("/mon-dossier/soumettre")
    assert r.status_code == 303

    r = client.post("/mon-dossier/entrees/rang_scientifique", data={"value": "professeur"})
    assert r.status_code == 403
    r = client.post("/mon-dossier/activites",
                    data={"criterion_id": "projet_international", "item": "projet_intl"})
    assert r.status_code == 403


def test_campagne_fermee_bloque_la_saisie(client, db_session, campaign, enseignant):
    login(client, "enseignant@test.dz")
    client.get("/mon-dossier")
    campaign.statut = "cloturee"
    db_session.commit()
    r = client.post("/mon-dossier/entrees/rang_scientifique", data={"value": "mca"})
    assert r.status_code == 403


def test_acces_commission_refuse_a_enseignant(client, campaign, enseignant):
    login(client, "enseignant@test.dz")
    r = client.get("/commission/dossiers")
    assert r.status_code in (403, 404)  # 404 tant que la route n'existe pas, 403 ensuite
