"""Fixtures communes des tests webapp : base SQLite en mémoire, client FastAPI."""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("SECRET_KEY", "secret-de-test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp import models  # noqa: F401 — enregistre les tables
from webapp.db import Base, get_db
from webapp.main import app
from webapp.models import Campaign, Dossier, User
from webapp.security import hash_password

PASSWORD = "motdepasse"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def campaign(db_session):
    c = Campaign(
        grid_id="u3-residences-scientifiques",
        institution_id="enset-skikda",
        campaign_date=date(2026, 6, 30),
        statut="ouverte",
    )
    db_session.add(c)
    db_session.commit()
    return c


def _make_user(db_session, email: str, role: str, nom: str = "Test") -> User:
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        nom=nom,
        prenom=role.capitalize(),
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def enseignant(db_session):
    return _make_user(db_session, "enseignant@test.dz", "enseignant", "Benali")


@pytest.fixture()
def membre_commission(db_session):
    return _make_user(db_session, "commission@test.dz", "commission", "Saidi")


@pytest.fixture()
def admin(db_session):
    return _make_user(db_session, "admin@test.dz", "admin", "Admin")


@pytest.fixture()
def dossier(db_session, campaign, enseignant):
    d = Dossier(
        campaign_id=campaign.id,
        user_id=enseignant.id,
        candidate_ref="DC-2026-001",
        departement="technologie",
    )
    db_session.add(d)
    db_session.commit()
    return d


def login(client, email: str, password: str = PASSWORD):
    return client.post("/connexion", data={"email": email, "password": password})
