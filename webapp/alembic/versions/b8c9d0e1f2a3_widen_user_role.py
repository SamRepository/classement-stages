"""users.role élargi à VARCHAR(40)

Le rôle « responsable_commission » fait 22 caractères ; la colonne était en
VARCHAR(20), ce que PostgreSQL refuse (StringDataRightTruncation → 500 à la
création/modification d'un compte avec ce rôle). On élargit à 40.

SQLite n'applique pas la longueur des VARCHAR : la migration y est sans objet
(et `ALTER` de type y impose le mode batch), on la saute donc sur SQLite.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-30 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "users", "role",
        existing_type=sa.String(length=20),
        type_=sa.String(length=40),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "users", "role",
        existing_type=sa.String(length=40),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
