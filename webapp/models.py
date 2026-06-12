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
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from webapp.db import Base

# Statuts (valeurs en français : elles apparaissent dans l'UI et les exports)
CAMPAIGN_STATUTS = ("ouverte", "cloturee", "gelee")
DOSSIER_STATUTS = ("brouillon", "soumis", "gele")
ENTRY_STATUTS = ("en_attente", "valide", "rejete")
ROLES = ("enseignant", "commission", "admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_id: Mapped[str] = mapped_column(String(80))
    institution_id: Mapped[str] = mapped_column(String(80))
    campaign_date: Mapped[date] = mapped_column(Date)
    window_reference: Mapped[str] = mapped_column(String(20), default="cloture")
    date_ouverture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_cloture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    statut: Mapped[str] = mapped_column(String(20), default="ouverte")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    role: Mapped[str] = mapped_column(String(20), default="enseignant")
    actif: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

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
    statut: Mapped[str] = mapped_column(String(20), default="brouillon")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="dossiers")
    user: Mapped[User] = relationship()
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
