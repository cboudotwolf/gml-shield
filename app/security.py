from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.database import settings

PASSWORD_HASHER = PasswordHasher()
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, supplied_password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, supplied_password)
    except (InvalidHashError, VerificationError):
        return False


def password_hash_needs_update(password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return False


def create_access_token(user_id: int, session_id: str) -> str:
    issued_at = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "sid": session_id,
        "iss": "gml-shield",
        "aud": "gml-shield-client",
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_LIFETIME,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_access_token(access_token: str) -> dict[str, Any]:
    return jwt.decode(
        access_token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer="gml-shield",
        audience="gml-shield-client",
        options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"]},
    )


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_csrf_token(csrf_token: str) -> str:
    return hashlib.sha256(csrf_token.encode()).hexdigest()
