from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, settings
from app.models import LoginSession, User
from app.security import decode_access_token, hash_csrf_token


async def get_database_session():
    async with SessionLocal() as database_session:
        yield database_session


DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]


async def get_authenticated_user(request: Request, database_session: DatabaseSession) -> User:
    access_token = request.cookies.get("gml_access")
    if not access_token:
        raise HTTPException(401, "Authentification requise")

    try:
        token_claims = decode_access_token(access_token)
        session_id = str(token_claims["sid"])
        user_id = int(token_claims["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(401, "Session invalide ou expirée") from None

    login_session = await database_session.get(LoginSession, session_id)
    user = await database_session.get(User, user_id)
    current_time = datetime.now(timezone.utc)
    if (
        not login_session
        or login_session.user_id != user_id
        or login_session.revoked_at
        or login_session.expires_at <= current_time
        or not user
        or not user.is_active
    ):
        raise HTTPException(401, "Session invalide ou expirée")

    request.state.user = user
    request.state.login_session = login_session
    return user


def validate_request_origin(request: Request) -> None:
    request_origin = request.headers.get("origin")
    if settings.cookie_secure and request_origin != settings.allowed_origin:
        raise HTTPException(403, "Origine non autorisée")
    if request_origin and request_origin != settings.allowed_origin:
        raise HTTPException(403, "Origine non autorisée")


async def require_csrf_token(
    request: Request,
    authenticated_user: Annotated[User, Depends(get_authenticated_user)],
) -> User:
    login_session: LoginSession = request.state.login_session
    csrf_cookie = request.cookies.get("gml_csrf", "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if (
        not csrf_cookie
        or not secrets.compare_digest(csrf_cookie, csrf_header)
        or not secrets.compare_digest(hash_csrf_token(csrf_cookie), login_session.csrf_hash)
    ):
        raise HTTPException(403, "Jeton CSRF invalide")
    validate_request_origin(request)
    return authenticated_user
