"""Espace admin : comptes, import, bénéfices, campagne, réouverture."""

import io

from openpyxl import Workbook
from sqlalchemy import select

from tests.webapp.conftest import login
from webapp.models import Benefit, Dossier, User


def test_creation_compte_et_connexion(client, db_session, campaign, admin):
    login(client, "admin@test.dz")
    r = client.post("/admin/utilisateurs",
                    data={"email": "nouveau@test.dz", "nom": "Mansouri", "prenom": "B",
                          "role": "enseignant"})
    assert r.status_code == 200
    assert "nouveau@test.dz" in r.text
    # Le mot de passe initial apparaît une seule fois dans la réponse.
    nouveau = db_session.scalar(select(User).where(User.email == "nouveau@test.dz"))
    assert nouveau.role == "enseignant"


def test_import_xlsx_cree_comptes_et_dossiers(client, db_session, campaign, admin):
    wb = Workbook()
    ws = wb.active
    ws.append(["Email", "Nom", "Prénom", "Référence", "Département"])
    ws.append(["a@test.dz", "Alpha", "A", "DC-2026-101", "technologie"])
    ws.append(["b@test.dz", "Beta", "B", "DC-2026-102", ""])
    ws.append(["a@test.dz", "Doublon", "", "", ""])  # déjà créé ligne 2
    buffer = io.BytesIO()
    wb.save(buffer)

    login(client, "admin@test.dz")
    r = client.post("/admin/utilisateurs/import",
                    files={"fichier": ("comptes.xlsx", buffer.getvalue(),
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert "a@test.dz" in r.text and "b@test.dz" in r.text
    assert "existe déjà" in r.text

    refs = set(db_session.scalars(select(Dossier.candidate_ref)))
    assert {"DC-2026-101", "DC-2026-102"} <= refs


def test_benefices_ajout_suppression(client, db_session, campaign, admin, enseignant):
    login(client, "admin@test.dz")
    r = client.post("/admin/benefices",
                    data={"user_id": str(enseignant.id), "date": "2024-09-15",
                          "platform_close_date": "2024-04-30", "note": "stage 2024"})
    assert r.status_code == 303
    benefit = db_session.scalar(select(Benefit))
    assert benefit.user_id == enseignant.id
    r = client.post(f"/admin/benefices/{benefit.id}/supprimer")
    assert r.status_code == 303
    assert db_session.scalar(select(Benefit)) is None


def test_cloture_campagne(client, db_session, campaign, admin):
    login(client, "admin@test.dz")
    r = client.post("/admin/campagne", data={"statut": "cloturee",
                                             "campaign_date": "2026-06-30"})
    assert r.status_code == 303
    db_session.expire_all()
    assert campaign.statut == "cloturee"


def test_reouverture_dossier(client, db_session, campaign, dossier, admin):
    dossier.statut = "soumis"
    db_session.commit()
    login(client, "admin@test.dz")
    r = client.post(f"/admin/dossiers/{dossier.id}/reouvrir")
    assert r.status_code == 303
    db_session.expire_all()
    assert dossier.statut == "brouillon"


def test_admin_interdit_aux_autres_roles(client, campaign, enseignant, membre_commission):
    login(client, "enseignant@test.dz")
    assert client.get("/admin/utilisateurs").status_code == 403
    client.post("/deconnexion")
    login(client, "commission@test.dz")
    assert client.get("/admin/campagne").status_code == 403
