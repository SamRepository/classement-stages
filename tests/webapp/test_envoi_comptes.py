"""Envoi des identifiants par e-mail et changement de mot de passe forcé."""

from __future__ import annotations

import pytest

from webapp.config import get_settings
from webapp.models import User
from webapp.security import hash_password
from webapp.services import mailer
from tests.webapp.conftest import PASSWORD, login


@pytest.fixture()
def smtp_configure(monkeypatch):
    """Active une config SMTP factice et capture les messages « envoyés »."""
    envois: list = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            self.tls = True

        def login(self, user, password):
            self.user = user

        def send_message(self, message):
            envois.append(message)

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    for key, value in {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_USER": "stages@enset-skikda.dz",
        "SMTP_PASSWORD": "app-password",
        "BASE_URL": "https://stages.enset-skikda.dz",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield envois
    get_settings.cache_clear()


# --- mailer -----------------------------------------------------------------


def test_notify_hors_ligne_n_envoie_rien():
    """Sans config SMTP : pas d'envoi, pas d'erreur, mots de passe à communiquer."""
    get_settings.cache_clear()
    created = [{"email": "a@x.dz", "nom": "A", "prenom": "", "password": "secret123"}]
    resume = mailer.notify_new_accounts(created)
    assert resume == {"configure": False, "envoyes": 0, "echecs": 0}
    assert created[0]["envoye"] is False
    assert created[0]["erreur"] is None


def test_notify_envoie_et_annote(smtp_configure):
    created = [
        {"email": "benali@x.dz", "nom": "Benali", "prenom": "Sara", "password": "secret123"},
        {"email": "saidi@x.dz", "nom": "Saidi", "prenom": "", "password": "autre456"},
    ]
    resume = mailer.notify_new_accounts(created)
    assert resume == {"configure": True, "envoyes": 2, "echecs": 0}
    assert all(c["envoye"] and c["erreur"] is None for c in created)
    # Le corps porte l'identifiant, le mot de passe provisoire et le lien.
    corps = smtp_configure[0].get_content()
    assert "benali@x.dz" in corps
    assert "secret123" in corps
    assert "https://stages.enset-skikda.dz/connexion" in corps
    assert smtp_configure[0]["To"] == "benali@x.dz"


def test_notify_capture_echec_et_continue(smtp_configure, monkeypatch):
    def boom(*args, **kwargs):
        raise mailer.MailError("serveur injoignable")

    monkeypatch.setattr(mailer, "send_credentials", boom)
    created = [{"email": "z@x.dz", "nom": "Z", "prenom": "", "password": "secret123"}]
    resume = mailer.notify_new_accounts(created)
    assert resume["echecs"] == 1 and resume["envoyes"] == 0
    assert created[0]["envoye"] is False
    assert "injoignable" in created[0]["erreur"]


# --- changement de mot de passe forcé ---------------------------------------


def _force_user(db_session, email="force@test.dz", role="enseignant"):
    user = User(email=email, password_hash=hash_password(PASSWORD), nom="Forcé",
                prenom="T", role=role, must_change_password=True)
    db_session.add(user)
    db_session.commit()
    return user


def test_compte_temporaire_redirige_vers_changement(client, db_session, campaign):
    _force_user(db_session)
    login(client, "force@test.dz")
    r = client.get("/mon-dossier")
    assert r.status_code == 303
    assert r.headers["location"] == "/mon-mot-de-passe"


def test_page_changement_reste_accessible_et_affiche_bandeau(client, db_session, campaign):
    _force_user(db_session)
    login(client, "force@test.dz")
    r = client.get("/mon-mot-de-passe")
    assert r.status_code == 200
    assert "provisoire" in r.text


def test_changement_leve_le_verrou(client, db_session, dossier):
    """Après changement, le flag tombe et l'accès normal est rétabli."""
    enseignant = dossier.user
    enseignant.must_change_password = True
    db_session.commit()
    login(client, enseignant.email)
    r = client.post("/mon-mot-de-passe", data={
        "actuel": PASSWORD, "nouveau": "nouveau-secret", "confirmation": "nouveau-secret",
    })
    assert r.status_code == 200
    db_session.refresh(enseignant)
    assert enseignant.must_change_password is False
    # L'accès au dossier n'est plus intercepté.
    assert client.get("/mon-dossier").status_code == 200


def test_compte_existant_non_perturbe(client, db_session, dossier):
    """Un compte sans mot de passe temporaire accède directement (régression)."""
    assert dossier.user.must_change_password is False
    login(client, dossier.user.email)
    assert client.get("/mon-dossier").status_code == 200


# --- intégration import -----------------------------------------------------


def test_import_marque_must_change_password(client, db_session, campaign, admin, monkeypatch):
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    login(client, "admin@test.dz")
    csv = b"email,nom\nnouveau@enset-skikda.dz,Nouveau\n"
    r = client.post(
        "/admin/utilisateurs/import",
        files={"fichier": ("comptes.csv", csv, "text/csv")},
    )
    assert r.status_code == 200
    cree = db_session.query(User).filter(User.email == "nouveau@enset-skikda.dz").one()
    assert cree.must_change_password is True
    # SMTP non configuré en test : la page invite à communiquer manuellement.
    assert "non configuré" in r.text
