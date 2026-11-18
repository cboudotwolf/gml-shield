from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
import uuid

import jwt
import pytest
from sqlalchemy import select

from app.database import settings
from app.models import LoginSession, User
from app.security import hash_csrf_token, hash_password

ORIGIN = "https://testserver"
DRIVER_PASSWORD = secrets.token_urlsafe(24)


async def create_user(database_session, *, email="driver@example.test", role="DRIVER", active=True):
    user = User(
        email=email,
        password_hash=hash_password(DRIVER_PASSWORD),
        role=role,
        is_active=active,
    )
    database_session.add(user)
    await database_session.commit()
    await database_session.refresh(user)
    return user


async def login(api_client, email="driver@example.test", password=DRIVER_PASSWORD, origin=ORIGIN):
    return await api_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": origin},
    )


@pytest.mark.asyncio
async def test_active_driver_login_sets_secure_cookies_and_database_session(
    api_client, database_session
):
    driver = await create_user(database_session)

    response = await login(api_client)

    assert response.status_code == 200
    assert response.json()["user"]["id"] == driver.id
    access_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith("gml_access=")
    )
    csrf_cookie = next(
        value for value in response.headers.get_list("set-cookie") if value.startswith("gml_csrf=")
    )
    assert "httponly" in access_cookie.lower()
    assert "secure" in access_cookie.lower()
    assert "samesite=strict" in access_cookie.lower()
    assert "path=/" in access_cookie.lower()
    assert "max-age=900" in access_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert "secure" in csrf_cookie.lower()
    assert "samesite=strict" in csrf_cookie.lower()

    login_session = await database_session.scalar(
        select(LoginSession).where(LoginSession.user_id == driver.id)
    )
    assert login_session is not None
    assert login_session.revoked_at is None
    assert login_session.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_wrong_password_and_unknown_account_have_same_generic_error(
    api_client, database_session
):
    await create_user(database_session)

    wrong_password_response = await login(api_client, password="a-different-password-value")
    unknown_user_response = await login(api_client, email="unknown@example.test")

    assert wrong_password_response.status_code == 401
    assert unknown_user_response.status_code == 401
    assert wrong_password_response.json() == unknown_user_response.json()
    assert wrong_password_response.json()["detail"] == "Identifiants invalides"


@pytest.mark.asyncio
async def test_inactive_account_cannot_login(api_client, database_session):
    await create_user(database_session, active=False)

    response = await login(api_client)

    assert response.status_code == 401
    assert response.json()["detail"] == "Identifiants invalides"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims_override",
    [
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"aud": "another-client"},
        {"iss": "another-service"},
    ],
)
async def test_expired_or_wrong_claim_access_token_is_rejected(
    api_client, database_session, claims_override
):
    user = await create_user(database_session)
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user.id),
        "sid": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": "gml-shield",
        "aud": "gml-shield-client",
    }
    claims.update(claims_override)
    access_token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")

    response = await api_client.get(
        "/api/auth/me",
        cookies={"gml_access": access_token},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bad_signature_access_token_is_rejected(api_client, database_session):
    user = await create_user(database_session)
    now = datetime.now(timezone.utc)
    access_token = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "iss": "gml-shield",
            "aud": "gml-shield-client",
        },
        "an-unrelated-signing-key-that-is-not-used-by-the-application",
        algorithm="HS256",
    )

    response = await api_client.get("/api/auth/me", cookies={"gml_access": access_token})

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("session_state", ["missing", "revoked", "wrong_owner", "expired"])
async def test_invalid_server_session_is_rejected(api_client, database_session, session_state):
    driver = await create_user(database_session)
    other_user = await create_user(database_session, email="other@example.test")
    session_id = str(uuid.uuid4())
    session_user_id = other_user.id if session_state == "wrong_owner" else driver.id
    login_session = None
    if session_state != "missing":
        login_session = LoginSession(
            id=session_id,
            user_id=session_user_id,
            expires_at=(
                datetime.now(timezone.utc) - timedelta(minutes=1)
                if session_state == "expired"
                else datetime.now(timezone.utc) + timedelta(minutes=15)
            ),
            revoked_at=datetime.now(timezone.utc) if session_state == "revoked" else None,
            csrf_hash=hash_csrf_token("csrf-token-value"),
        )
        database_session.add(login_session)
        await database_session.commit()
    now = datetime.now(timezone.utc)
    access_token = jwt.encode(
        {
            "sub": str(driver.id),
            "sid": session_id,
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "iss": "gml-shield",
            "aud": "gml-shield-client",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    response = await api_client.get("/api/auth/me", cookies={"gml_access": access_token})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session_and_old_token_cannot_be_reused(api_client, database_session):
    driver = await create_user(database_session)
    login_response = await login(api_client)
    assert login_response.status_code == 200
    csrf_token = api_client.cookies.get("gml_csrf")
    access_token = api_client.cookies.get("gml_access")

    logout_response = await api_client.post(
        "/api/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert logout_response.status_code == 200
    assert "gml_access" not in api_client.cookies
    login_session = await database_session.scalar(
        select(LoginSession).where(LoginSession.user_id == driver.id)
    )
    assert login_session and login_session.revoked_at is not None

    old_token_response = await api_client.get(
        "/api/auth/me",
        cookies={"gml_access": access_token},
    )
    assert old_token_response.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_an_unapproved_origin(api_client, database_session):
    await create_user(database_session)

    response = await login(api_client, origin="https://attacker.example")

    assert response.status_code == 403
    assert response.json()["detail"] == "Origine non autorisée"
