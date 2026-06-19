"""ajoute users.must_change_password (mot de passe temporaire)

Revision ID: b7e1c4a9d2f3
Revises: a1b2c3d4e5f6
Create Date: 2026-06-19 09:00:00.000000

Les comptes déjà présents au moment de la migration sont explicitement marqués
``False`` (backfill) : ils gardent leur mot de passe et ne sont jamais forcés de
le changer. Seuls les comptes créés ensuite avec un mot de passe temporaire
(import / création / réinitialisation par l'admin) reçoivent ``True``.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e1c4a9d2f3'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'must_change_password',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill explicite : les comptes existants (testeurs, commission, admin)
    # restent à False même si une future valeur par défaut changeait.
    op.execute('UPDATE users SET must_change_password = false')


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
