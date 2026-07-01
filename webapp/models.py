"""Modèles SQLAlchemy.

La table ``entries`` est unifiée : une ligne par élément déclaré, quel que soit
le type de critère. Le rattachement à la grille se fait par les identifiants
texte ``criterion_id``/``item_id`` (clés logiques, validées à l'écriture contre
``grid["criteria"]``) ; le ``payload`` JSON est le fragment d'entrée attendu par
le moteur (``classement.engine.score_candidate``).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from webapp.db import Base

# Statuts (valeurs en français : elles apparaissent dans l'UI et les exports)
CAMPAIGN_STATUTS = ("ouverte", "cloturee", "gelee")
DOSSIER_STATUTS = ("brouillon", "soumis", "gele")
ENTRY_STATUTS = ("en_attente", "valide", "rejete")
# « commission » = membre évaluateur (émet un avis par élément) ;
# « responsable_commission » = responsable (affecte les dossiers + décisions finales).
ROLES = ("enseignant", "commission", "responsable_commission", "admin")
# Avis du membre sur un élément : ok = conforme, pas_ok = non conforme,
# explication = besoin d'explication / justificatif. Sans effet sur le score
# (purement consultatif pour le responsable).
REVIEW_FLAGS = ("ok", "pas_ok", "explication")
# Recours de l'enseignant sur un élément (phase de contestation, après
# publication des résultats provisoires). ``ouvert`` = déposé, en attente ;
# ``accepte``/``rejete`` = tranché par le responsable (motivation obligatoire) ;
# ``irrecevable`` = hors délai / non motivé ; ``retire`` = retiré par l'enseignant.
RECOURS_STATUTS = ("ouvert", "accepte", "rejete", "irrecevable", "retire")
# Nature du recours (« liste de choix » présentée à l'enseignant).
RECOURS_MOTIFS = (
    "desaccord_rejet",       # je conteste le rejet de l'élément
    "sous_evaluation",       # l'élément vaut plus de points que retenu
    "erreur_appreciation",   # erreur d'appréciation / de calcul
    "erreur_saisie",         # erreur matérielle dans ma déclaration
    "autre",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_id: Mapped[str] = mapped_column(String(80))
    institution_id: Mapped[str] = mapped_column(String(80))
    campaign_date: Mapped[date] = mapped_column(Date)
    window_reference: Mapped[str] = mapped_column(String(20), default="cloture")
    # Fenêtre « après dernier bénéfice » uniforme : intervalle de l'exercice
    # budgétaire (ex. 01/01/2025 → 31/12/2025). Si l'une des bornes est renseignée,
    # seules les activités datées dans [début, fin] comptent — pour tous les
    # candidats —, au lieu des dates par bénéfice (repère `window_reference`).
    window_start_date: Mapped[date | None] = mapped_column(Date)
    window_end_date: Mapped[date | None] = mapped_column(Date)
    date_ouverture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_cloture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    statut: Mapped[str] = mapped_column(String(20), default="ouverte")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase de recours : ouverte manuellement par le responsable une fois les
    # résultats provisoires publiés (campagne « cloturee »). Tant qu'elle est
    # ouverte, l'enseignant voit le classement provisoire et peut contester ses
    # éléments, et le gel est bloqué. La date limite est purement indicative
    # (aucun délai réglementaire dans l'arrêté 345).
    recours_ouverts: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    recours_deadline: Mapped[date | None] = mapped_column(Date)

    dossiers: Mapped[list["Dossier"]] = relationship(back_populates="campaign")

    __table_args__ = (
        CheckConstraint(f"statut IN {CAMPAIGN_STATUTS}", name="ck_campaign_statut"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nom: Mapped[str] = mapped_column(String(120))
    prenom: Mapped[str] = mapped_column(String(120), default="")
    # 40 : « responsable_commission » fait 22 caractères ; VARCHAR(20) tronquait
    # (rejet PostgreSQL). On garde une marge pour d'éventuels rôles futurs.
    role: Mapped[str] = mapped_column(String(40), default="enseignant")
    actif: Mapped[bool] = mapped_column(default=True)
    # Vrai pour un compte dont le mot de passe est temporaire (généré par
    # l'admin et communiqué par e-mail) : la connexion force alors le changement.
    # Faux par défaut → les comptes existants ne sont jamais perturbés.
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Horodatage de la dernière connexion réussie (NULL = compte jamais utilisé) :
    # permet à l'admin de repérer les candidats qui ne se sont pas encore connectés.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    benefits: Mapped[list["Benefit"]] = relationship(
        back_populates="user", order_by="Benefit.date"
    )

    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="ck_user_role"),)


class Dossier(Base):
    __tablename__ = "dossiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    candidate_ref: Mapped[str] = mapped_column(String(40))  # ex. DC-2026-284
    population: Mapped[str] = mapped_column(String(60), default="enseignant_chercheur")
    departement: Mapped[str | None] = mapped_column(String(80))
    # Informations de mobilité (couche coûts)
    pays: Mapped[str | None] = mapped_column(String(80))
    duree_jours: Mapped[int | None] = mapped_column(Integer)
    billet_estime_da: Mapped[float | None] = mapped_column(Float)
    frais_divers_da: Mapped[float | None] = mapped_column(Float)
    # Déclaration de l'enseignant : habilitation universitaire obtenue durant
    # l'exercice budgétaire de la fenêtre. Sert d'alerte à la commission (les
    # documents pédagogiques déjà utilisés dans le dossier d'habilitation ne sont
    # pas comptés, cf. shared-rules) ; sans effet automatique sur le score.
    habilitation_exercice: Mapped[bool] = mapped_column(Boolean, default=False)
    statut: Mapped[str] = mapped_column(String(20), default="brouillon")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Membre de la commission chargé de relire ce dossier (avis par élément).
    # Affecté par le responsable ; NULL = non encore réparti. La décision finale
    # (validation/rejet, score) reste au responsable, quel que soit le relecteur.
    assigned_reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    campaign: Mapped[Campaign] = relationship(back_populates="dossiers")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    assigned_reviewer: Mapped["User | None"] = relationship(foreign_keys=[assigned_reviewer_id])
    entries: Mapped[list["Entry"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan", order_by="Entry.id"
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_dossier_campaign_user"),
        CheckConstraint(f"statut IN {DOSSIER_STATUTS}", name="ck_dossier_statut"),
    )


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id"))
    criterion_id: Mapped[str] = mapped_column(String(80))
    item_id: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Dénormalisée depuis payload["date"] pour tri/affichage.
    date_activite: Mapped[date | None] = mapped_column(Date)
    statut: Mapped[str] = mapped_column(String(20), default="en_attente")
    decision_motif: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    dossier: Mapped[Dossier] = relationship(back_populates="entries")
    attachment: Mapped["Attachment | None"] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False
    )
    decided_by_user: Mapped[User | None] = relationship(foreign_keys=[decided_by])
    reviews: Mapped[list["ElementReview"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    recours: Mapped[list["Recours"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="Recours.id"
    )

    __table_args__ = (
        CheckConstraint(f"statut IN {ENTRY_STATUTS}", name="ck_entry_statut"),
        # Exigence art. 14-15 : tout rejet est motivé.
        CheckConstraint(
            "statut <> 'rejete' OR decision_motif IS NOT NULL",
            name="ck_entry_rejet_motive",
        ),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), unique=True)
    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id"))
    filename_original: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    entry: Mapped[Entry] = relationship(back_populates="attachment")


class ElementReview(Base):
    """Avis d'un membre de commission sur un élément déclaré.

    Couche purement consultative, distincte de la décision (``Entry.statut``) :
    le membre signale un flag (``ok`` / ``pas_ok`` / ``explication``) et une
    observation libre pour éclairer le responsable, sans toucher au score. La
    décision finale qui agit sur le calcul reste au responsable (art. 14-15).
    """

    __tablename__ = "element_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    flag: Mapped[str] = mapped_column(String(20))
    observation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    entry: Mapped[Entry] = relationship(back_populates="reviews")
    reviewer: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("entry_id", "reviewer_id", name="uq_review_entry_reviewer"),
        CheckConstraint(f"flag IN {REVIEW_FLAGS}", name="ck_review_flag"),
    )


class Recours(Base):
    """Recours de l'enseignant contre une décision de la commission sur un élément.

    Déposé pendant la phase de recours (résultats provisoires publiés,
    ``campaign.recours_ouverts``). L'enseignant motive sa contestation d'un
    élément (``motif`` dans une liste de choix + ``message`` libre, sans pièce
    jointe). Le responsable tranche : ``accepte`` / ``rejete`` / ``irrecevable``,
    avec ``reponse_motif`` obligatoire (art. 14-15). Un recours accepté n'agit
    pas sur le score par lui-même : le responsable corrige alors l'élément avec
    les outils d'examen existants (re-validation / ajustement), et le moteur
    recalcule. L'enseignant peut ``retire`` un recours tant qu'il est ``ouvert``.
    """

    __tablename__ = "recours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    motif: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    statut: Mapped[str] = mapped_column(String(20), default="ouvert")
    reponse_motif: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    entry: Mapped[Entry] = relationship(back_populates="recours")
    created_by_user: Mapped[User] = relationship(foreign_keys=[created_by])
    decided_by_user: Mapped[User | None] = relationship(foreign_keys=[decided_by])

    __table_args__ = (
        CheckConstraint(f"statut IN {RECOURS_STATUTS}", name="ck_recours_statut"),
        CheckConstraint(f"motif IN {RECOURS_MOTIFS}", name="ck_recours_motif"),
        # Toute décision qui tranche le recours est motivée (art. 14-15).
        CheckConstraint(
            "statut NOT IN ('accepte', 'rejete', 'irrecevable') "
            "OR reponse_motif IS NOT NULL",
            name="ck_recours_reponse_motive",
        ),
    )


class Benefit(Base):
    """Historique des mobilités antérieures — géré par l'admin (donnée faisant foi).

    Alimente la pénalité ``3 - n`` et la fenêtre « après dernier bénéfice ».
    Rattaché à l'utilisateur : survit aux campagnes.
    """

    __tablename__ = "benefits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    date: Mapped[date] = mapped_column(Date)
    platform_close_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(40), default="admin")
    note: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="benefits")


class RankingSnapshot(Base):
    """Instantané du classement au gel (reproductibilité du PV)."""

    __tablename__ = "ranking_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payload: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    """Journal léger : soumissions, décisions, gels, réouvertures."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dossier_id: Mapped[int | None] = mapped_column(ForeignKey("dossiers.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
