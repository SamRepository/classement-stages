"""campaigns.window_global_close_date (repère de fenêtre uniforme)

Revision ID: a1b2c3d4e5f6
Revises: 2c2c05599f46
Create Date: 2026-06-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "2c2c05599f46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("window_global_close_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "window_global_close_date")
