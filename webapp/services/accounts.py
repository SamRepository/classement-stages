"""Création et import des comptes enseignants (CSV ou Excel).

Colonnes reconnues (en-têtes insensibles à la casse, repérage par mot-clé) :
email (« mail »), nom, prénom, référence de candidature (« ref »), département
(« depart »). Source typique : l'export du module Odoo « Stages » retravaillé,
ou un CSV préparé par le service.
"""

from __future__ import annotations

import csv
import io
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models import Campaign, Dossier, User
from webapp.security import generate_password, hash_password


def _map_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, raw in enumerate(headers):
        h = unicodedata.normalize("NFKD", (raw or "").strip().lower())
        h = "".join(c for c in h if not unicodedata.combining(c))
        if "mail" in h and "email" not in mapping:
            mapping["email"] = i
        elif ("prenom" in h or "prénom" in h) and "prenom" not in mapping:
            mapping["prenom"] = i
        elif "nom" in h and "nom" not in mapping:
            mapping["nom"] = i
        elif ("ref" in h or h == "id") and "ref" not in mapping:
            mapping["ref"] = i
        elif "depart" in h and "departement" not in mapping:
            mapping["departement"] = i
    if "email" not in mapping or "nom" not in mapping:
        raise HTTPException(
            status_code=422,
            detail="Colonnes « email » et « nom » introuvables dans le fichier.",
        )
    return mapping


def _rows_from_file(filename: str, content: bytes) -> list[list[str]]:
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        return [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=";,\t")
        return [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    raise HTTPException(status_code=422, detail="Format attendu : .csv ou .xlsx.")


def import_accounts(
    db: Session, campaign: Campaign, filename: str, content: bytes
) -> tuple[list[dict], list[str]]:
    """Crée les comptes (rôle enseignant) et leur dossier brouillon.

    Retourne (créés : [{email, nom, prenom, password}], ignorés : messages).
    Les comptes existants sont conservés tels quels (import idempotent).
    """
    rows = _rows_from_file(filename, content)
    if not rows:
        raise HTTPException(status_code=422, detail="Fichier vide.")
    mapping = _map_headers(rows[0])

    created: list[dict] = []
    skipped: list[str] = []
    for index, row in enumerate(rows[1:], start=2):
        def cell(key: str) -> str:
            i = mapping.get(key)
            return (row[i] or "").strip() if i is not None and i < len(row) else ""

        email = cell("email").lower()
        nom = cell("nom")
        if not email or "@" not in email:
            if any((c or "").strip() for c in row):
                skipped.append(f"Ligne {index} : adresse électronique absente ou invalide.")
            continue
        if db.scalar(select(User).where(User.email == email)):
            skipped.append(f"Ligne {index} : {email} existe déjà (conservé).")
            continue
        password = generate_password()
        user = User(email=email, password_hash=hash_password(password),
                    nom=nom or email.split("@")[0], prenom=cell("prenom"), role="enseignant")
        db.add(user)
        db.flush()
        db.add(Dossier(
            campaign_id=campaign.id,
            user_id=user.id,
            candidate_ref=cell("ref") or f"WEB-{user.id:03d}",
            departement=cell("departement") or None,
        ))
        created.append({"email": email, "nom": user.nom, "prenom": user.prenom,
                        "password": password})
    db.commit()
    return created, skipped
