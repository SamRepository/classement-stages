"""Hachage et vérification des mots de passe (bcrypt)."""

from __future__ import annotations

import secrets

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def generate_password(length: int = 10) -> str:
    """Mot de passe initial lisible (sans caractères ambigus)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ2345679"
    return "".join(secrets.choice(alphabet) for _ in range(length))
