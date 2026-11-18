from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.audit import record_audit
from app.database import SessionLocal, settings
from app.dependencies import DatabaseSession, get_authenticated_user, require_csrf_token
from app.models import AuditLog, Document, LoginSession, Mission, User
from app.schemas import MissionInput, MissionView, StatusInput, UserView
from app.security import decode_access_token

router = APIRouter()


class DriverNotificationHub:
    def __init__(self) -> None:
        self.driver_sockets: dict[int, set[WebSocket]] = {}

    async def connect_driver(self, driver_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.driver_sockets.setdefault(driver_id, set()).add(websocket)

    def disconnect_driver(self, driver_id: int, websocket: WebSocket) -> None:
        self.driver_sockets.get(driver_id, set()).discard(websocket)

    async def notify_driver(self, driver_id: int, mission_id: int) -> None:
        notification = {"event": "NEW_MISSION", "mission_id": mission_id}
        for websocket in tuple(self.driver_sockets.get(driver_id, set())):
            try:
                await websocket.send_json(notification)
            except Exception:
                self.disconnect_driver(driver_id, websocket)


driver_notification_hub = DriverNotificationHub()


def encrypt_warehouse_code(warehouse_code: str) -> bytes:
    nonce = secrets.token_bytes(12)
    encrypted_value = AESGCM(settings.aes_key).encrypt(
        nonce,
        warehouse_code.encode(),
        b"gml-shield:warehouse-code:v1",
    )
    return b"\x01" + nonce + encrypted_value


def decrypt_warehouse_code(encrypted_code: bytes) -> str:
    if not encrypted_code or encrypted_code[0] != 1:
        raise ValueError("Version de clé de chiffrement inconnue")
    decrypted_value = AESGCM(settings.aes_key).decrypt(
        encrypted_code[1:13],
        encrypted_code[13:],
        b"gml-shield:warehouse-code:v1",
    )
    return decrypted_value.decode()


def serialize_mission(
    mission: Mission,
    document_ids: list[str],
    reveal_secret_to_driver: bool = False,
) -> MissionView:
    warehouse_code = decrypt_warehouse_code(mission.secret_code) if reveal_secret_to_driver else ""
    return MissionView(
        id=mission.id,
        title=mission.title,
        destination=mission.destination,
        secret_code=warehouse_code,
        status=mission.status,
        driver_id=mission.driver_id,
        dispatcher_id=mission.dispatcher_id,
        created_at=mission.created_at,
        documents=document_ids,
    )


@router.get("/api/drivers", response_model=list[UserView])
async def list_drivers(
    request: Request,
    database_session: DatabaseSession,
) -> list[UserView]:
    user = await get_authenticated_user(request, database_session)
    if user.role not in {"DISPATCHER", "ADMIN"}:
        raise HTTPException(403, "Rôle insuffisant")
    drivers = list(
        (
            await database_session.scalars(
                select(User)
                .where(User.role == "DRIVER", User.is_active.is_(True))
                .order_by(User.email)
            )
        ).all()
    )
    return [UserView.model_validate(driver) for driver in drivers]


@router.post("/api/missions", response_model=MissionView, status_code=201)
async def create_mission(
    payload: MissionInput,
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(require_csrf_token)],
) -> MissionView:
    if user.role != "DISPATCHER":
        raise HTTPException(403, "Réservé au répartiteur")
    driver = await database_session.get(User, payload.driver_id)
    if not driver or driver.role != "DRIVER" or not driver.is_active:
        raise HTTPException(422, "Chauffeur invalide")

    mission = Mission(
        title=payload.title,
        destination=payload.destination,
        secret_code=encrypt_warehouse_code(payload.secret_code),
        status="PENDING",
        driver_id=driver.id,
        dispatcher_id=user.id,
    )
    database_session.add(mission)
    await database_session.flush()
    await record_audit(
        database_session, request, "MISSION_CREATE", f"mission:{mission.id}", user.id
    )
    await database_session.commit()
    await database_session.refresh(mission)
    await driver_notification_hub.notify_driver(driver.id, mission.id)
    return serialize_mission(mission, [])


@router.get("/api/missions", response_model=list[MissionView])
async def list_missions(
    request: Request,
    database_session: DatabaseSession,
) -> list[MissionView]:
    user = await get_authenticated_user(request, database_session)
    if user.role == "DRIVER":
        mission_query = select(Mission).where(Mission.driver_id == user.id)
    elif user.role == "DISPATCHER":
        mission_query = select(Mission).where(Mission.dispatcher_id == user.id)
    else:
        raise HTTPException(403, "Le rôle ADMIN ne donne pas accès au contenu des missions")

    missions = list(
        (
            await database_session.scalars(
                mission_query.order_by(Mission.created_at.desc()).limit(100)
            )
        ).all()
    )
    serialized_missions = []
    for mission in missions:
        document_ids = list(
            (
                await database_session.scalars(
                    select(Document.id).where(Document.mission_id == mission.id)
                )
            ).all()
        )
        serialized_missions.append(
            serialize_mission(
                mission,
                document_ids,
                reveal_secret_to_driver=user.role == "DRIVER",
            )
        )
    if user.role == "DRIVER":
        await record_audit(
            database_session, request, "MISSION_LIST_READ_SECRET", "missions", user.id
        )
        await database_session.commit()
    return serialized_missions


@router.patch("/api/missions/{mission_id}/status")
async def change_mission_status(
    mission_id: int,
    payload: StatusInput,
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(require_csrf_token)],
) -> dict[str, int | str]:
    if user.role != "DRIVER":
        raise HTTPException(403, "Réservé au chauffeur")
    mission = await database_session.get(Mission, mission_id)
    if not mission or mission.driver_id != user.id:
        raise HTTPException(404, "Mission introuvable")
    allowed_transitions = {"PENDING": "IN_PROGRESS", "IN_PROGRESS": "COMPLETED"}
    if allowed_transitions.get(mission.status) != payload.status:
        raise HTTPException(409, "Transition de statut non autorisée")
    if payload.status == "COMPLETED" and not await database_session.scalar(
        select(Document.id).where(Document.mission_id == mission.id).limit(1)
    ):
        raise HTTPException(409, "Une preuve de livraison est requise")
    mission.status = payload.status
    await record_audit(
        database_session, request, "MISSION_STATUS_CHANGE", f"mission:{mission.id}", user.id
    )
    await database_session.commit()
    return {"id": mission.id, "status": mission.status}


def detect_uploaded_file_mime_type(file_content: bytes) -> str | None:
    if file_content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if file_content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if file_content.startswith(b"%PDF-"):
        return "application/pdf"
    return None


async def scan_uploaded_file(file_content: bytes) -> None:
    clamav_host = os.getenv("CLAMAV_HOST", "clamav")
    clamav_port = int(os.getenv("CLAMAV_PORT", "3310"))
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(clamav_host, clamav_port),
        timeout=5,
    )
    try:
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(file_content), 64 * 1024):
            chunk = file_content[offset : offset + 64 * 1024]
            writer.write(len(chunk).to_bytes(4, "big") + chunk)
        writer.write(b"\\0\\0\\0\\0")
        await writer.drain()
        scanner_response = await asyncio.wait_for(reader.readline(), timeout=20)
        if b"OK" not in scanner_response or b"FOUND" in scanner_response:
            raise HTTPException(422, "Le document est infecté ou n'a pas pu être analysé")
    finally:
        writer.close()
        await writer.wait_closed()


@router.post("/api/missions/{mission_id}/documents", status_code=201)
async def upload_document(
    mission_id: int,
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(require_csrf_token)],
    upload: UploadFile = File(...),
) -> dict[str, str]:
    if user.role != "DRIVER":
        raise HTTPException(403, "Réservé au chauffeur")
    mission = await database_session.get(Mission, mission_id)
    if not mission or mission.driver_id != user.id or mission.status != "IN_PROGRESS":
        raise HTTPException(404, "Mission introuvable ou non modifiable")
    file_content = await upload.read(settings.max_upload_bytes + 1)
    if len(file_content) > settings.max_upload_bytes:
        raise HTTPException(413, "Taille maximale : 10 Mo")
    mime_type = detect_uploaded_file_mime_type(file_content)
    if not mime_type:
        raise HTTPException(415, "Formats acceptés : JPEG, PNG et PDF")
    try:
        await scan_uploaded_file(file_content)
    except (OSError, asyncio.TimeoutError):
        raise HTTPException(503, "Analyse antivirus indisponible, réessayez plus tard") from None

    document_id = str(uuid.uuid4())
    file_extension_by_mime_type = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
    }
    upload_path = (
        settings.private_upload_directory
        / f"{document_id}.{file_extension_by_mime_type[mime_type]}"
    )
    upload_path.write_bytes(file_content)
    document = Document(
        id=document_id,
        mission_id=mission.id,
        file_path=str(upload_path),
        mime_type=mime_type,
        original_name=Path(upload.filename or "preuve").name[:255],
    )
    database_session.add(document)
    await record_audit(
        database_session,
        request,
        "DOCUMENT_UPLOAD",
        f"mission:{mission.id}/document:{document.id}",
        user.id,
    )
    await database_session.commit()
    return {"id": document.id, "mime_type": mime_type}


@router.get("/api/missions/{mission_id}/documents/{document_id}")
async def download_document(
    mission_id: int,
    document_id: str,
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(get_authenticated_user)],
) -> FileResponse:
    mission = await database_session.get(Mission, mission_id)
    document = await database_session.get(Document, document_id)
    if (
        user.role != "DISPATCHER"
        or not mission
        or mission.dispatcher_id != user.id
        or not document
        or document.mission_id != mission_id
    ):
        raise HTTPException(404, "Document introuvable")
    await record_audit(
        database_session,
        request,
        "DOCUMENT_DOWNLOAD",
        f"mission:{mission_id}/document:{document_id}",
        user.id,
    )
    await database_session.commit()
    return FileResponse(
        document.file_path, media_type=document.mime_type, filename=document.original_name
    )


@router.get("/api/audit")
async def list_audit_entries(
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(get_authenticated_user)],
) -> list[dict[str, object]]:
    if user.role != "ADMIN":
        raise HTTPException(403, "Réservé à l'administration de sécurité")
    audit_entries = list(
        (
            await database_session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
            )
        ).all()
    )
    return [
        {
            "id": audit_entry.id,
            "user_id": audit_entry.user_id,
            "action": audit_entry.action,
            "resource": audit_entry.resource,
            "result": audit_entry.result,
            "ip_address": audit_entry.ip_address,
            "created_at": audit_entry.created_at,
        }
        for audit_entry in audit_entries
    ]


@router.websocket("/api/ws")
async def driver_notifications(websocket: WebSocket) -> None:
    access_token = websocket.cookies.get("gml_access")
    request_origin = websocket.headers.get("origin")
    if not access_token or request_origin != settings.allowed_origin:
        await websocket.close(code=1008)
        return
    try:
        token_claims = decode_access_token(access_token)
        user_id = int(token_claims["sub"])
        session_id = str(token_claims["sid"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        await websocket.close(code=1008)
        return

    async with SessionLocal() as database_session:
        login_session = await database_session.get(LoginSession, session_id)
        user = await database_session.get(User, user_id)
        if (
            not login_session
            or login_session.user_id != user_id
            or login_session.revoked_at
            or login_session.expires_at <= datetime.now(timezone.utc)
            or not user
            or user.role != "DRIVER"
            or not user.is_active
        ):
            await websocket.close(code=1008)
            return

    await driver_notification_hub.connect_driver(user_id, websocket)
    try:
        while True:
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
            async with SessionLocal() as database_session:
                login_session = await database_session.get(LoginSession, session_id)
                if (
                    not login_session
                    or login_session.revoked_at
                    or login_session.expires_at <= datetime.now(timezone.utc)
                ):
                    await websocket.close(code=1008)
                    return
            await websocket.send_json({"event": "HEARTBEAT"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        driver_notification_hub.disconnect_driver(user_id, websocket)
