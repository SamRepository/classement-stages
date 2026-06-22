"""users.last_login_at (horodatage de la dernière connexion réussie)

Permet à l'admin de distinguer dans le tableau des comptes ceux qui se sont déjà
connectés de ceux qui ne l'ont jamais fait. Colonne nullable : les comptes
existants restent à NULL (« jamais connecté ») jusqu'à leur prochaine connexion.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-22 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
