"""dossiers.habilitation_exercice (déclaration habilitation dans l'exercice)

Déclaration de l'enseignant : habilitation universitaire obtenue durant
l'exercice budgétaire. Alerte la commission (documents pédagogiques du dossier
d'habilitation non comptés) ; sans effet automatique sur le score.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dossiers",
        sa.Column(
            "habilitation_exercice",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("dossiers", "habilitation_exercice")
