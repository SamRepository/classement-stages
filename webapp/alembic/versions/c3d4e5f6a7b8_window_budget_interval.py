"""campaigns : fenêtre uniforme en intervalle d'exercice budgétaire

Remplace la date de clôture uniforme unique (`window_global_close_date`) par un
intervalle `[window_start_date, window_end_date]` (exercice budgétaire). Décision
des responsables : la fenêtre « après dernier bénéfice » est fixée entre deux dates
(ex. 01/01/2025 → 31/12/2025) plutôt qu'à un repère par bénéfice.

Revision ID: c3d4e5f6a7b8
Revises: b7e1c4a9d2f3
Create Date: 2026-06-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b7e1c4a9d2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("window_start_date", sa.Date(), nullable=True))
    op.add_column("campaigns", sa.Column("window_end_date", sa.Date(), nullable=True))
    # L'ancienne clôture uniforme était une borne *basse* (seules les activités
    # postérieures comptaient) : on la reporte en début d'intervalle pour ne pas
    # perdre le paramétrage existant.
    op.execute("UPDATE campaigns SET window_start_date = window_global_close_date")
    op.drop_column("campaigns", "window_global_close_date")


def downgrade() -> None:
    op.add_column(
        "campaigns", sa.Column("window_global_close_date", sa.Date(), nullable=True)
    )
    op.execute("UPDATE campaigns SET window_global_close_date = window_start_date")
    op.drop_column("campaigns", "window_end_date")
    op.drop_column("campaigns", "window_start_date")
