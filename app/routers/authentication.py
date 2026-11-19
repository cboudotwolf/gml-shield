from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from app.audit import record_audit
from app.database import settings
from app.dependencies import (
    DatabaseSession,
    get_authenticated_user,
    require_csrf_token,
    validate_request_origin,
)
from app.models import LoginSession, User
from app.schemas import LoginInput, UserView
from app.security import (
    ACCESS_TOKEN_LIFETIME,
    create_access_token,
    create_csrf_token,
    hash_csrf_token,
    hash_password,
    password_hash_needs_update,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentification"])
login_attempts_by_ip: dict[str, tuple[float, int]] = {}


def set_authentication_cookies(
    response: Response, user_id: int, session_id: str, csrf_token: str
) -> None:
    """Keep the access token unreadable by JavaScript while exposing only the CSRF token."""
    cookie_options = {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "max_age": int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        "path": "/",
    }
    response.set_cookie(
        "gml_access",
        create_access_token(user_id, session_id),
        httponly=True,
        **cookie_options,
    )
    response.set_cookie("gml_csrf", csrf_token, httponly=False, **cookie_options)


@router.post("/login")
async def login(
    credentials: LoginInput,
    request: Request,
    response: Response,
    database_session: DatabaseSession,
):
    """Authenticate without revealing account existence and create a revocable session.

    The generic failure response limits account enumeration. The short-lived JWT is
    coupled to server-side state so logout can revoke it before its natural expiry.
    """
    validate_request_origin(request)
    client_ip = request.client.host if request.client else "unknown"
    current_timestamp = time.monotonic()
    window_started_at, failed_attempts = login_attempts_by_ip.get(client_ip, (current_timestamp, 0))
    if current_timestamp - window_started_at > 300:
        window_started_at, failed_attempts = current_timestamp, 0
    if failed_attempts >= 10:
        raise HTTPException(429, "Trop de tentatives. Réessayez dans quelques minutes.")
    login_attempts_by_ip[client_ip] = (window_started_at, failed_attempts + 1)

    user = await database_session.scalar(
        select(User).where(User.email == credentials.email.lower())
    )
    password_is_valid = (
        user is not None
        and user.is_active
        and verify_password(user.password_hash, credentials.password)
    )
    if not password_is_valid:
        await record_audit(
            database_session, request, "AUTH_LOGIN", "session", user.id if user else None, "FAILURE"
        )
        await database_session.commit()
        raise HTTPException(401, "Identifiants invalides")

    if password_hash_needs_update(user.password_hash):
        user.password_hash = hash_password(credentials.password)

    current_time = datetime.now(timezone.utc)
    csrf_token = create_csrf_token()
    login_session = LoginSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        expires_at=current_time + ACCESS_TOKEN_LIFETIME,
        csrf_hash=hash_csrf_token(csrf_token),
    )
    database_session.add(login_session)
    await record_audit(database_session, request, "AUTH_LOGIN", "session", user.id)
    await database_session.commit()
    login_attempts_by_ip.pop(client_ip, None)
    set_authentication_cookies(response, user.id, login_session.id, csrf_token)
    return {"user": UserView.model_validate(user)}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(require_csrf_token)],
):
    login_session: LoginSession = request.state.login_session
    login_session.revoked_at = datetime.now(timezone.utc)
    await record_audit(database_session, request, "AUTH_LOGOUT", "session", user.id)
    await database_session.commit()
    response.delete_cookie(
        "gml_access",
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        "gml_csrf",
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )
    return {"ok": True}


@router.get("/me", response_model=UserView)
async def get_current_user(user: Annotated[User, Depends(get_authenticated_user)]) -> UserView:
    return UserView.model_validate(user)
