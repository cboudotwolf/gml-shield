from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.audit import record_audit
from app.database import SessionLocal, engine, settings
from app.routers.authentication import router as authentication_router
from app.routers.driver_messages import router as driver_messages_router
from app.routers.operations import router as operations_router

logger = logging.getLogger(__name__)
frontend_directory = Path(__file__).resolve().parent.parent / "frontend_dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.private_upload_directory.mkdir(parents=True, exist_ok=True)
    yield
    await engine.dispose()


app = FastAPI(title="GML-SHIELD", version="1.0.0", lifespan=lifespan)
app.include_router(authentication_router)
app.include_router(driver_messages_router)
app.include_router(operations_router)

if frontend_directory.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend_directory / "assets"), name="assets")


@app.middleware("http")
async def audit_rejected_mutations(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and response.status_code >= 400:
        try:
            async with SessionLocal() as database_session:
                actor = getattr(request.state, "user", None)
                await record_audit(
                    database_session,
                    request,
                    f"{request.method}_REJECTED",
                    request.url.path[:200],
                    actor.id if actor else None,
                    "FAILURE",
                )
                await database_session.commit()
        except Exception:
            logger.exception(
                "Impossible d'enregistrer la tentative refusée dans le journal d'audit"
            )
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gml-shield"}


@app.get("/", response_model=None)
async def frontend() -> FileResponse | dict[str, str]:
    frontend_index = frontend_directory / "index.html"
    if not frontend_index.is_file():
        return {"service": "GML-SHIELD", "status": "frontend build missing"}
    return FileResponse(frontend_index)
