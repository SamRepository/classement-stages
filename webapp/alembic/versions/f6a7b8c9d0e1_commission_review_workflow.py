"""workflow commission à deux niveaux : relecteur affecté + avis par élément

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-22 10:00:00.000000

Ajoute :
- le rôle ``responsable_commission`` à la contrainte de rôle (le rôle
  ``commission`` existant devient « membre évaluateur ») ;
- ``dossiers.assigned_reviewer_id`` : le membre chargé de relire le dossier ;
- la table ``element_reviews`` : avis consultatif (flag + observation) d'un
  membre sur un élément déclaré, sans effet sur le score.

Les comptes ``commission`` existants restent valides (membres) ; aucun n'est
promu responsable automatiquement — l'admin désigne le responsable.
"""
from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

_ROLES_NEW = "role IN ('enseignant', 'commission', 'responsable_commission', 'admin')"
_ROLES_OLD = "role IN ('enseignant', 'commission', 'admin')"

# Modifier une contrainte CHECK sur SQLite impose le mode « batch » (recréation
# de table). On nomme l'unique en ligne (UNIQUE(email)) pour que la recréation
# réussisse ; surtout pas les CHECK, sinon `ck_user_role` serait renommée et
# introuvable au drop.
_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    with op.batch_alter_table("users", naming_convention=_NAMING) as batch:
        batch.drop_constraint("ck_user_role", type_="check")
        batch.create_check_constraint("ck_user_role", _ROLES_NEW)

    # Colonne simple (la clé étrangère reste portée par le modèle ORM) : évite le
    # mode batch sur `dossiers` et reste compatible SQLite comme PostgreSQL.
    op.add_column("dossiers", sa.Column("assigned_reviewer_id", sa.Integer(), nullable=True))

    op.create_table(
        "element_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("flag", sa.String(length=20), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "flag IN ('ok', 'pas_ok', 'explication')", name="ck_review_flag"
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "reviewer_id", name="uq_review_entry_reviewer"),
    )


def downgrade() -> None:
    op.drop_table("element_reviews")
    op.drop_column("dossiers", "assigned_reviewer_id")

    with op.batch_alter_table("users", naming_convention=_NAMING) as batch:
        batch.drop_constraint("ck_user_role", type_="check")
        batch.create_check_constraint("ck_user_role", _ROLES_OLD)
