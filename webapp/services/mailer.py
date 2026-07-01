"""Envoi des identifiants par e-mail (SMTP, bibliothèque standard).

Aucune dépendance hors stdlib : ``smtplib`` + ``email.message``. Cible visée :
boîte Google Workspace ``stages@enset-skikda.dz`` via ``smtp.gmail.com:587`` en
STARTTLS, authentifiée par un **mot de passe d'application** (la connexion par
mot de passe de compte est refusée par Google).

Mode **hors-ligne** : si la config SMTP est incomplète (`Settings.mail_configure`
faux), aucun envoi n'a lieu — le mot de passe temporaire reste affiché dans
l'admin pour communication manuelle. Les tests et le dev fonctionnent ainsi sans
serveur de messagerie.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from webapp.config import Settings, get_settings

logger = logging.getLogger("webapp.mailer")


class MailError(Exception):
    """Échec d'envoi d'un e-mail (connexion, authentification, refus SMTP)."""


def _login_url(settings: Settings) -> str:
    return f"{settings.base_url}/connexion" if settings.base_url else ""


def _build_message(settings: Settings, to_email: str, nom: str, password: str) -> EmailMessage:
    url = _login_url(settings)
    acces = f"Accédez à l'application : {url}\n" if url else ""
    corps = (
        f"Bonjour {nom},\n\n"
        "Un compte vous a été créé sur la plateforme de classement des mobilités "
        "à l'étranger (arrêté n° 345/2026) de l'ENSET-Skikda.\n\n"
        f"{acces}"
        f"Identifiant : {to_email}\n"
        f"Mot de passe provisoire : {password}\n\n"
        "Pour des raisons de sécurité, ce mot de passe est temporaire : "
        "il vous sera demandé d'en choisir un nouveau dès votre première connexion.\n\n"
        "Si vous n'êtes pas concerné par cette campagne, ignorez ce message.\n\n"
        "— Service des stages, ENSET-Skikda"
    )
    message = EmailMessage()
    message["Subject"] = "Vos identifiants — plateforme de classement des mobilités (ENSET-Skikda)"
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(corps)
    return message


def _dispatch(settings: Settings, message: EmailMessage) -> None:
    """Envoi bas niveau (STARTTLS + login), transforme tout échec en ``MailError``."""
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:  # réseau, auth, refus serveur
        raise MailError(f"Échec de l'envoi à {message['To']} : {exc}") from exc


def send_credentials(
    to_email: str, nom: str, password: str, *, settings: Settings | None = None
) -> None:
    """Envoie un mot de passe provisoire. Lève ``MailError`` en cas d'échec.

    Lève également ``MailError`` si la config SMTP est incomplète : un appelant qui
    veut un comportement silencieux doit vérifier ``settings.mail_configure``.
    """
    settings = settings or get_settings()
    if not settings.mail_configure:
        raise MailError("Envoi SMTP non configuré (SMTP_HOST/SMTP_USER/SMTP_PASSWORD).")
    _dispatch(settings, _build_message(settings, to_email, nom, password))


def send_email(
    to_email: str, subject: str, body: str, *, settings: Settings | None = None
) -> None:
    """Envoie un e-mail texte simple. Lève ``MailError`` (config ou envoi)."""
    settings = settings or get_settings()
    if not settings.mail_configure:
        raise MailError("Envoi SMTP non configuré (SMTP_HOST/SMTP_USER/SMTP_PASSWORD).")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(body)
    _dispatch(settings, message)


def notify(
    to_email: str, subject: str, body: str, *, settings: Settings | None = None
) -> bool:
    """Notification « au mieux » : n'interrompt jamais le flux appelant.

    Retourne True si l'e-mail est parti, False si la config SMTP est absente (mode
    hors-ligne) ou si l'envoi a échoué (échec journalisé, non propagé).
    """
    settings = settings or get_settings()
    if not settings.mail_configure:
        return False
    try:
        send_email(to_email, subject, body, settings=settings)
        return True
    except MailError as exc:
        logger.warning("Notification e-mail échouée (%s) : %s", to_email, exc)
        return False


def notify_new_accounts(created: list[dict], *, settings: Settings | None = None) -> dict:
    """Envoie leurs identifiants aux comptes fraîchement créés (in place).

    Chaque entrée de ``created`` (``{email, nom, prenom, password}``) est annotée :
      - ``envoye`` : True si l'e-mail est parti, False sinon ;
      - ``erreur`` : message d'échec, ou None.
    En mode hors-ligne (SMTP non configuré), rien n'est envoyé et ``envoye`` reste
    False sans erreur : l'admin lit les mots de passe affichés et les communique.

    Retourne un récapitulatif ``{configure, envoyes, echecs}``.
    """
    settings = settings or get_settings()
    envoyes = echecs = 0
    for compte in created:
        compte["envoye"] = False
        compte["erreur"] = None
        if not settings.mail_configure:
            continue
        nom = " ".join(p for p in (compte.get("prenom"), compte.get("nom")) if p) or compte["email"]
        try:
            send_credentials(compte["email"], nom, compte["password"], settings=settings)
            compte["envoye"] = True
            envoyes += 1
        except MailError as exc:
            compte["erreur"] = str(exc)
            logger.warning("Envoi des identifiants échoué : %s", exc)
            echecs += 1
    return {"configure": settings.mail_configure, "envoyes": envoyes, "echecs": echecs}
