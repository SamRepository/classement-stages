"""phase de recours : table recours + fenêtre de recours sur la campagne

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-01 10:00:00.000000

Ajoute :
- ``campaigns.recours_ouverts`` (bool) et ``campaigns.recours_deadline`` (date
  indicative) : la fenêtre de recours, ouverte manuellement par le responsable
  une fois les résultats provisoires publiés ;
- la table ``recours`` : contestation par l'enseignant d'une décision de la
  commission sur un élément (``motif`` + ``message`` libre, sans pièce jointe),
  tranchée par le responsable (``reponse_motif`` obligatoire, art. 14-15).

Migration bi-compatible SQLite (dev) / PostgreSQL (prod Coolify) : create_table
+ add_column simples, sans mode batch. L'unicité « un seul recours ouvert par
élément » est garantie en applicatif (portable), pas par un index partiel.
"""
from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

_STATUTS = "('ouvert', 'accepte', 'rejete', 'irrecevable', 'retire')"
_MOTIFS = (
    "('desaccord_rejet', 'sous_evaluation', 'erreur_appreciation', "
    "'erreur_saisie', 'autre')"
)


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "recours_ouverts", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("campaigns", sa.Column("recours_deadline", sa.Date(), nullable=True))
    # Backfill explicite : les campagnes existantes démarrent recours fermés.
    op.execute("UPDATE campaigns SET recours_ouverts = false")

    op.create_table(
        "recours",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("motif", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False),
        sa.Column("reponse_motif", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"statut IN {_STATUTS}", name="ck_recours_statut"),
        sa.CheckConstraint(f"motif IN {_MOTIFS}", name="ck_recours_motif"),
        sa.CheckConstraint(
            "statut NOT IN ('accepte', 'rejete', 'irrecevable') "
            "OR reponse_motif IS NOT NULL",
            name="ck_recours_reponse_motive",
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recours_entry_id", "recours", ["entry_id"])


def downgrade() -> None:
    op.drop_index("ix_recours_entry_id", table_name="recours")
    op.drop_table("recours")
    op.drop_column("campaigns", "recours_deadline")
    op.drop_column("campaigns", "recours_ouverts")
