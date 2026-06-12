"""Workflow des dossiers : création, garde d'édition, soumission, gel, réouverture."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models import Campaign, Dossier, Event, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def log_event(
    db: Session, user: User, action: str, dossier: Dossier | None = None, detail: str | None = None
) -> None:
    db.add(Event(user_id=user.id, dossier_id=dossier.id if dossier else None,
                 action=action, detail=detail))


def get_campaign(db: Session) -> Campaign:
    """La campagne courante (une seule par déploiement dans le MVP)."""
    campaign = db.scalar(select(Campaign).order_by(Campaign.id.desc()))
    if campaign is None:
        raise HTTPException(status_code=503, detail="Aucune campagne configurée (lancer le seed).")
    return campaign


def campaign_is_open(campaign: Campaign) -> bool:
    if campaign.statut != "ouverte":
        return False
    now = _now()

    def _aware(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    ouverture = _aware(campaign.date_ouverture)
    cloture = _aware(campaign.date_cloture)
    if ouverture and now < ouverture:
        return False
    if cloture and now > cloture:
        return False
    return True


def ensure_dossier(db: Session, user: User, campaign: Campaign) -> Dossier:
    """Le dossier de l'enseignant pour la campagne (créé en brouillon au premier accès)."""
    dossier = db.scalar(
        select(Dossier).where(Dossier.campaign_id == campaign.id, Dossier.user_id == user.id)
    )
    if dossier is None:
        dossier = Dossier(
            campaign_id=campaign.id,
            user_id=user.id,
            candidate_ref=f"WEB-{user.id:03d}",
        )
        db.add(dossier)
        db.commit()
        db.refresh(dossier)
    return dossier


def assert_editable(dossier: Dossier) -> None:
    """Écriture enseignant : uniquement sur un brouillon, campagne ouverte."""
    if dossier.statut != "brouillon":
        raise HTTPException(
            status_code=403,
            detail="Dossier soumis : il ne peut plus être modifié. Contactez l'administration "
                   "pour une réouverture.",
        )
    if not campaign_is_open(dossier.campaign):
        raise HTTPException(status_code=403, detail="La campagne n'est pas ouverte à la saisie.")


def submit_dossier(db: Session, dossier: Dossier, user: User) -> None:
    assert_editable(dossier)
    dossier.statut = "soumis"
    dossier.submitted_at = _now()
    log_event(db, user, "soumission", dossier)
    db.commit()


def reopen_dossier(db: Session, dossier: Dossier, admin: User) -> None:
    """Réouverture par l'admin (dossier soumis → brouillon), refusée après gel."""
    if dossier.campaign.statut == "gelee":
        raise HTTPException(status_code=403, detail="Classement gelé : réouverture impossible.")
    if dossier.statut != "soumis":
        raise HTTPException(status_code=400, detail="Seul un dossier soumis peut être rouvert.")
    dossier.statut = "brouillon"
    dossier.submitted_at = None
    log_event(db, admin, "reouverture", dossier)
    db.commit()
