"""renomme l'item editeur -> editeur_ou_membre (critère responsabilites_scientifiques)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-24 10:00:00.000000

Migration de données pure (aucun changement de schéma) : l'id de l'élément a été
renommé dans les grilles u1/u3 (« editeur » → « editeur_ou_membre »). On aligne
les dossiers déjà déposés pour qu'ils continuent de correspondre à la grille et
de marquer leurs points. Le rattachement se fait par (criterion_id, item_id),
indépendant de la grille : seules les entrées de « responsabilites_scientifiques »
sont touchées.
"""
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE entries SET item_id = 'editeur_ou_membre' "
        "WHERE item_id = 'editeur' AND criterion_id = 'responsabilites_scientifiques'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE entries SET item_id = 'editeur' "
        "WHERE item_id = 'editeur_ou_membre' AND criterion_id = 'responsabilites_scientifiques'"
    )
