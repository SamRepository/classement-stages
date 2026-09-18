"""publication des résultats : campaigns.results_published_at

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-18 09:00:00.000000

Ajoute ``campaigns.results_published_at`` : l'horodatage de la publication des
résultats aux enseignants, posé à la première ouverture de la fenêtre de recours.

Jusqu'ici, la visibilité du classement côté enseignant était déduite de
``recours_ouverts`` : fermer la fenêtre de recours dépubliait le classement,
faisait réapparaître le score *déclaré* à la place du score *retenu* et masquait
les motifs de rejet (art. 14-15) — alors que la campagne n'était pas encore
gelée. La publication devient donc un fait horodaté qui ne se rétracte pas, et
la fenêtre de recours ne gouverne plus que le **dépôt**.

Backfill : toute campagne déjà publiée (fenêtre de recours ouverte, ou
classement gelé) reçoit une date de publication — ``frozen_at`` si elle est
gelée, à défaut sa date de clôture, à défaut maintenant — pour qu'aucun candidat
ne perde l'accès à ses résultats au passage de la migration.

Bi-compatible SQLite (dev) / PostgreSQL (prod Coolify) : add_column simple et
UPDATE avec COALESCE, sans mode batch.
"""
from alembic import op
import sqlalchemy as sa


revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("results_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE campaigns "
        "SET results_published_at = COALESCE(frozen_at, date_cloture, CURRENT_TIMESTAMP) "
        "WHERE results_published_at IS NULL "
        "AND (recours_ouverts <> false OR statut = 'gelee')"
    )


def downgrade() -> None:
    op.drop_column("campaigns", "results_published_at")
