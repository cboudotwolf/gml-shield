from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

import pytest
from sqlalchemy import func, select

from app.models import DriverMessage, User
from app.security import hash_password

ORIGIN = "https://testserver"
DRIVER_PASSWORD = secrets.token_urlsafe(24)


async def create_user(database_session, email, role="DRIVER"):
    user = User(
        email=email, password_hash=hash_password(DRIVER_PASSWORD), role=role, is_active=True
    )
    database_session.add(user)
    await database_session.commit()
    await database_session.refresh(user)
    return user


async def login(api_client, email):
    response = await api_client.post(
        "/api/auth/login",
        json={"email": email, "password": DRIVER_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return api_client.cookies.get("gml_csrf")


@pytest.mark.asyncio
async def test_driver_can_create_and_read_only_their_own_messages(api_client, database_session):
    driver_a = await create_user(database_session, "driver-a@example.test")
    driver_b = await create_user(database_session, "driver-b@example.test")
    csrf_for_driver_a = await login(api_client, driver_a.email)
    first_message_response = await api_client.post(
        "/api/messages",
        json={"content": "Message A"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_for_driver_a},
    )
    assert first_message_response.status_code == 201
    assert first_message_response.json()["driver_id"] == driver_a.id
    assert first_message_response.json()["content"] == "Message A"

    await api_client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_for_driver_a}
    )
    csrf_for_driver_b = await login(api_client, driver_b.email)
    second_message_response = await api_client.post(
        "/api/messages",
        json={"content": "Message B"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_for_driver_b},
    )
    assert second_message_response.status_code == 201
    assert second_message_response.json()["driver_id"] == driver_b.id

    messages_response = await api_client.get("/api/messages")

    assert messages_response.status_code == 200
    assert [message["content"] for message in messages_response.json()] == ["Message B"]
    assert all(message["driver_id"] == driver_b.id for message in messages_response.json())


@pytest.mark.asyncio
async def test_message_history_is_newest_first_and_limited_to_100(api_client, database_session):
    driver = await create_user(database_session, "driver@example.test")
    await login(api_client, driver.email)
    first_timestamp = datetime.now(timezone.utc) - timedelta(minutes=3)
    database_session.add_all(
        [
            DriverMessage(
                driver_id=driver.id,
                content=f"message-{message_number}",
                created_at=first_timestamp + timedelta(seconds=message_number),
            )
            for message_number in range(105)
        ]
    )
    await database_session.commit()

    response = await api_client.get("/api/messages")

    assert response.status_code == 200
    assert len(response.json()) == 100
    assert response.json()[0]["content"] == "message-104"
    assert response.json()[-1]["content"] == "message-5"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "csrf_headers,csrf_cookie,expected_status",
    [
        ({"Origin": ORIGIN}, False, 403),
        ({"Origin": ORIGIN}, True, 403),
        ({"Origin": ORIGIN, "X-CSRF-Token": "wrong-token"}, True, 403),
        ({"Origin": "https://attacker.example", "X-CSRF-Token": "valid"}, True, 403),
    ],
)
async def test_message_creation_rejects_invalid_csrf_or_origin(
    api_client,
    database_session,
    csrf_headers,
    csrf_cookie,
    expected_status,
):
    driver = await create_user(database_session, "driver@example.test")
    csrf_token = await login(api_client, driver.email)
    headers = dict(csrf_headers)
    if "X-CSRF-Token" in headers and headers["X-CSRF-Token"] == "valid":
        headers["X-CSRF-Token"] = csrf_token
    if not csrf_cookie:
        api_client.cookies.delete("gml_csrf")

    response = await api_client.post("/api/messages", json={"content": "message"}, headers=headers)

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_message_creation_rejects_other_roles_and_client_selected_owner(
    api_client, database_session
):
    dispatcher = await create_user(database_session, "dispatch@example.test", role="DISPATCHER")
    await create_user(database_session, "driver@example.test")
    csrf_token = await login(api_client, dispatcher.email)

    wrong_role_response = await api_client.post(
        "/api/messages",
        json={"content": "message"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert wrong_role_response.status_code == 403

    await api_client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
    )
    driver = await login(api_client, "driver@example.test")
    csrf_token = driver
    owner_override_response = await api_client.post(
        "/api/messages",
        json={"content": "message", "driver_id": 999},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert owner_override_response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_content", ["", "   ", "x" * 2001])
async def test_message_content_validation_rejects_empty_whitespace_and_oversize(
    api_client,
    database_session,
    invalid_content,
):
    driver = await create_user(database_session, "driver@example.test")
    csrf_token = await login(api_client, driver.email)

    response = await api_client.post(
        "/api/messages",
        json={"content": invalid_content},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "untrusted_content", ["' OR 1=1 --", "Robert'); DROP TABLE driver_messages;--"]
)
async def test_sql_injection_strings_are_stored_as_plain_text_and_do_not_drop_table(
    api_client,
    database_session,
    untrusted_content,
):
    driver = await create_user(database_session, "driver@example.test")
    csrf_token = await login(api_client, driver.email)

    create_response = await api_client.post(
        "/api/messages",
        json={"content": untrusted_content},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
    )
    messages_response = await api_client.get("/api/messages")
    message_count = await database_session.scalar(select(func.count()).select_from(DriverMessage))

    assert create_response.status_code == 201
    assert create_response.json()["content"] == untrusted_content
    assert [message["content"] for message in messages_response.json()] == [untrusted_content]
    assert message_count == 1


@pytest.mark.asyncio
async def test_login_injection_is_rejected_without_authenticating(api_client, database_session):
    await create_user(database_session, "driver@example.test")

    response = await api_client.post(
        "/api/auth/login",
        json={"email": "' OR 1=1 --", "password": DRIVER_PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Identifiants invalides"
