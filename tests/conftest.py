from __future__ import annotations

import base64
import os
from urllib.parse import urlsplit

import pytest_asyncio
from sqlalchemy import delete

test_database_url = os.environ.get("GML_TEST_DATABASE_URL")
parsed_test_database_url = urlsplit(test_database_url or "")
if (
    not test_database_url
    or parsed_test_database_url.hostname not in {"localhost", "127.0.0.1", "::1"}
    or parsed_test_database_url.username != "gml_test"
    or parsed_test_database_url.path != "/gml_shield_test"
):
    raise RuntimeError(
        "Définis GML_TEST_DATABASE_URL vers gml_shield_test, l'instance locale dédiée aux tests."
    )

os.environ["DATABASE_URL"] = test_database_url
os.environ["GML_JWT_SECRET"] = "test-only-jwt-secret-never-use-in-production"
os.environ["GML_AES_KEY_B64"] = base64.b64encode(b"T" * 32).decode()
os.environ["GML_ALLOWED_ORIGIN"] = "https://testserver"
os.environ["GML_COOKIE_SECURE"] = "true"
os.environ["GML_PRIVATE_UPLOADS"] = "/tmp/gml-shield-test-uploads"

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditLog, Base, Document, DriverMessage, LoginSession, Mission, User  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def prepare_isolated_test_database():
    async with engine.begin() as database_connection:
        await database_connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as database_connection:
        for model in (AuditLog, Document, DriverMessage, Mission, LoginSession, User):
            await database_connection.execute(delete(model))


@pytest_asyncio.fixture
async def api_client():
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def database_session():
    async with SessionLocal() as session:
        yield session
