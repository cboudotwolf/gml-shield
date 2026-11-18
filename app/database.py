import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import load_settings

settings = load_settings()
engine_options: dict[str, object] = {"pool_pre_ping": True}
if os.getenv("GML_TEST_DATABASE_URL"):
    engine_options["poolclass"] = NullPool
engine = create_async_engine(settings.database_url, **engine_options)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
