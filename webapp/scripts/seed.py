"""Initialisation : schéma, campagne (depuis CAMPAIGN_*) et premier admin.

Usage :
    python -m webapp.scripts.seed --admin-email admin@enset-skikda.dz [--admin-password ...]

Idempotent : ne recrée ni la campagne ni l'admin s'ils existent déjà.
"""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import select

from classement.grids import find_grid
from classement.institutions import load_institution
from webapp import models  # noqa: F401 — enregistre les tables sur Base.metadata
from webapp.config import get_settings
from webapp.db import Base, SessionLocal, engine
from webapp.models import Campaign, User
from webapp.security import generate_password, hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise la base (campagne + admin).")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", default=None,
                        help="Généré aléatoirement (et affiché) si omis.")
    args = parser.parse_args()

    settings = get_settings()
    # Échec immédiat si la grille ou le profil configurés n'existent pas.
    find_grid(settings.campaign_grid_id)
    load_institution(settings.campaign_institution_id)

    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        campaign = db.scalar(select(Campaign))
        if campaign is None:
            campaign = Campaign(
                grid_id=settings.campaign_grid_id,
                institution_id=settings.campaign_institution_id,
                campaign_date=date.fromisoformat(settings.campaign_date),
                window_reference=settings.campaign_window_reference,
                statut="ouverte",
            )
            db.add(campaign)
            print(f"Campagne créée : {settings.campaign_grid_id} / "
                  f"{settings.campaign_institution_id} / {settings.campaign_date}")
        else:
            print(f"Campagne existante conservée : {campaign.grid_id} ({campaign.statut})")

        email = args.admin_email.strip().lower()
        admin = db.scalar(select(User).where(User.email == email))
        if admin is None:
            password = args.admin_password or generate_password()
            db.add(User(email=email, password_hash=hash_password(password),
                        nom="Administrateur", prenom="", role="admin"))
            print(f"Admin créé : {email}")
            if args.admin_password is None:
                print(f"Mot de passe initial : {password}")
        else:
            print(f"Admin existant conservé : {email}")

        db.commit()


if __name__ == "__main__":
    main()
