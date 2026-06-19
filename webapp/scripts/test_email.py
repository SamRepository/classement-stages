"""Envoi d'un e-mail de test pour valider la configuration SMTP.

Usage (dans le conteneur Coolify ou en local avec les variables SMTP_*) :

    python -m webapp.scripts.test_email destinataire@exemple.dz

N'écrit rien en base : appelle directement le mailer avec un mot de passe
factice. Affiche un diagnostic clair en cas d'échec (auth, connexion, config).
"""

from __future__ import annotations

import argparse
import sys

from webapp.config import get_settings
from webapp.services.mailer import MailError, send_credentials


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste l'envoi d'identifiants par e-mail.")
    parser.add_argument("destinataire", help="Adresse de test (la vôtre).")
    parser.add_argument("--nom", default="Test", help="Nom affiché dans le message.")
    args = parser.parse_args()

    settings = get_settings()
    print(f"SMTP_HOST   = {settings.smtp_host or '(vide)'}")
    print(f"SMTP_PORT   = {settings.smtp_port}")
    print(f"SMTP_USER   = {settings.smtp_user or '(vide)'}")
    print(f"SMTP_FROM   = {settings.smtp_from or '(vide)'}")
    print(f"STARTTLS    = {settings.smtp_starttls}")
    print(f"Configuré   = {settings.mail_configure}")
    print(f"BASE_URL    = {settings.base_url or '(vide)'}")
    print("-" * 50)

    if not settings.mail_configure:
        print("[ECHEC] SMTP non configuré : renseignez SMTP_HOST, SMTP_USER et SMTP_PASSWORD.")
        return 1

    try:
        send_credentials(args.destinataire, args.nom, "MotDePasseTest123", settings=settings)
    except MailError as exc:
        print(f"[ECHEC] {exc}")
        return 1
    print(f"[OK] E-mail de test envoyé à {args.destinataire}. Vérifiez la boîte (et les spams).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
