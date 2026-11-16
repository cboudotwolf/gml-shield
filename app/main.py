from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ["GML_JWT_SECRET"]
AES_KEY = base64.b64decode(os.environ["GML_AES_KEY_B64"])
if len(JWT_SECRET) < 32 or len(AES_KEY) != 32:
    raise RuntimeError("GML_JWT_SECRET (32 caractères minimum) et une clé AES de 32 octets sont requis")
COOKIE_SECURE = os.getenv("GML_COOKIE_SECURE", "true").lower() == "true"
UPLOAD_DIR = Path(os.getenv("GML_PRIVATE_UPLOADS", "/data/private_uploads"))
MAX_UPLOAD_BYTES = 10_000_000
PASSWORDS = PasswordHasher()
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(500))
    secret_code: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dispatcher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    original_name: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    resource: Mapped[str] = mapped_column(String(200))
    result: Mapped[str] = mapped_column(String(20))
    ip_address: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=200)


class MissionInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=500)
    secret_code: str = Field(min_length=1, max_length=200)
    driver_id: int = Field(gt=0)


class StatusInput(BaseModel):
    status: str


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str


class MissionView(BaseModel):
    id: int
    title: str
    destination: str
    secret_code: str
    status: str
    driver_id: int
    dispatcher_id: int
    created_at: datetime
    documents: list[str] = []


class Hub:
    def __init__(self) -> None:
        self.driver_sockets: dict[int, set[WebSocket]] = {}

    async def add(self, driver_id: int, socket: WebSocket) -> None:
        await socket.accept()
        self.driver_sockets.setdefault(driver_id, set()).add(socket)

    def remove(self, driver_id: int, socket: WebSocket) -> None:
        self.driver_sockets.get(driver_id, set()).discard(socket)

    async def notify_driver(self, driver_id: int, mission_id: int) -> None:
        message = {"event": "NEW_MISSION", "mission_id": mission_id}
        for socket in tuple(self.driver_sockets.get(driver_id, set())):
            try:
                await socket.send_json(message)
            except Exception:
                self.remove(driver_id, socket)


hub = Hub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield
    await engine.dispose()


app = FastAPI(title="GML-SHIELD", version="1.0.0", lifespan=lifespan)
login_windows: dict[str, tuple[float, int]] = {}
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend_dist"
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.middleware("http")
async def audit_rejected_mutations(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and response.status_code >= 400:
        try:
            async with SessionLocal() as db:
                actor = getattr(request.state, "user", None)
                await record_audit(db, request, f"{request.method}_REJECTED", request.url.path[:200], actor.id if actor else None, "FAILURE")
                await db.commit()
        except Exception:
            # A rejected request stays rejected; application logs report audit-store outages.
            pass
    return response


@app.get("/")
async def frontend():
    if not (FRONTEND_DIR / "index.html").is_file():
        return {"service": "GML-SHIELD", "status": "frontend build missing"}
    return FileResponse(FRONTEND_DIR / "index.html")


async def get_db():
    async with SessionLocal() as db:
        yield db


Db = Annotated[AsyncSession, Depends(get_db)]


def encrypt_code(code: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return b"\x01" + nonce + AESGCM(AES_KEY).encrypt(nonce, code.encode(), b"gml-shield:warehouse-code:v1")


def decrypt_code(ciphertext: bytes) -> str:
    if not ciphertext or ciphertext[0] != 1:
        raise ValueError("Version de clé de chiffrement inconnue")
    return AESGCM(AES_KEY).decrypt(ciphertext[1:13], ciphertext[13:], b"gml-shield:warehouse-code:v1").decode()


async def record_audit(db: AsyncSession, request: Request | None, action: str, resource: str, user_id: int | None, result: str = "SUCCESS") -> None:
    ip = request.client.host if request and request.client else "unknown"
    db.add(AuditLog(user_id=user_id, action=action, resource=resource, result=result, ip_address=ip))
    await db.flush()


def make_jwt(user_id: int, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "sid": session_id, "iss": "gml-shield", "aud": "gml-shield-client", "iat": now, "exp": now + timedelta(minutes=15)}, JWT_SECRET, algorithm="HS256")


async def authenticated_user(request: Request, db: Db) -> User:
    token = request.cookies.get("gml_access")
    if not token:
        raise HTTPException(401, "Authentification requise")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer="gml-shield", audience="gml-shield-client")
        session_id = str(payload["sid"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Session invalide ou expirée") from None
    session = await db.get(LoginSession, session_id)
    user = await db.get(User, user_id)
    now = datetime.now(timezone.utc)
    if not session or session.user_id != user_id or session.revoked_at or session.expires_at <= now or not user or not user.is_active:
        raise HTTPException(401, "Session invalide ou expirée")
    request.state.user = user
    request.state.login_session = session
    return user


async def require_csrf(request: Request, user: User = Depends(authenticated_user)) -> User:
    # Read the CSRF cookie and matching header; authentication alone is not enough for mutations.
    session: LoginSession = request.state.login_session
    cookie_value = request.cookies.get("gml_csrf", "")
    header_value = request.headers.get("x-csrf-token", "")
    supplied_hash = hashlib.sha256(cookie_value.encode()).hexdigest()
    if not cookie_value or not secrets.compare_digest(cookie_value, header_value) or not secrets.compare_digest(supplied_hash, session.csrf_hash):
        raise HTTPException(403, "Jeton CSRF invalide")
    origin = request.headers.get("origin")
    allowed = os.getenv("GML_ALLOWED_ORIGIN")
    if origin and allowed and origin != allowed:
        raise HTTPException(403, "Origine non autorisée")
    return user


def serialize_mission(mission: Mission, document_ids: list[str], reveal_secret_to_driver: bool = False) -> MissionView:
    secret_code = decrypt_code(mission.secret_code) if reveal_secret_to_driver else ""
    return MissionView(id=mission.id, title=mission.title, destination=mission.destination, secret_code=secret_code, status=mission.status, driver_id=mission.driver_id, dispatcher_id=mission.dispatcher_id, created_at=mission.created_at, documents=document_ids)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gml-shield"}


@app.post("/api/auth/login")
async def login(payload: LoginInput, request: Request, response: Response, db: Db):
    ip = request.client.host if request.client else "unknown"
    now_epoch = time.monotonic()
    start, attempts = login_windows.get(ip, (now_epoch, 0))
    if now_epoch - start > 300:
        start, attempts = now_epoch, 0
    if attempts >= 10:
        raise HTTPException(429, "Trop de tentatives. Réessayez dans quelques minutes.")
    login_windows[ip] = (start, attempts + 1)
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    try:
        password_ok = bool(user and user.is_active and PASSWORDS.verify(user.password_hash, payload.password))
    except VerificationError:
        password_ok = False
    if not password_ok:
        await record_audit(db, request, "AUTH_LOGIN", "session", user.id if user else None, "FAILURE")
        await db.commit()
        raise HTTPException(401, "Identifiants invalides")
    now = datetime.now(timezone.utc)
    csrf = secrets.token_urlsafe(32)
    session = LoginSession(id=str(uuid.uuid4()), user_id=user.id, expires_at=now + timedelta(minutes=15), csrf_hash=hashlib.sha256(csrf.encode()).hexdigest())
    db.add(session)
    await record_audit(db, request, "AUTH_LOGIN", "session", user.id)
    await db.commit()
    login_windows.pop(ip, None)
    response.set_cookie("gml_access", make_jwt(user.id, session.id), httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=900, path="/")
    response.set_cookie("gml_csrf", csrf, httponly=False, secure=COOKIE_SECURE, samesite="strict", max_age=900, path="/")
    return {"user": UserView.model_validate(user)}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response, db: Db, user: User = Depends(require_csrf)):
    session: LoginSession = request.state.login_session
    session.revoked_at = datetime.now(timezone.utc)
    await record_audit(db, request, "AUTH_LOGOUT", "session", user.id)
    await db.commit()
    response.delete_cookie("gml_access", path="/")
    response.delete_cookie("gml_csrf", path="/")
    return {"ok": True}


@app.get("/api/auth/me", response_model=UserView)
async def me(request: Request, db: Db):
    return await authenticated_user(request, db)


@app.get("/api/drivers", response_model=list[UserView])
async def list_drivers(request: Request, db: Db):
    user = await authenticated_user(request, db)
    if user.role not in {"DISPATCHER", "ADMIN"}:
        raise HTTPException(403, "Rôle insuffisant")
    return list((await db.scalars(select(User).where(User.role == "DRIVER", User.is_active.is_(True)).order_by(User.email))).all())


@app.post("/api/missions", response_model=MissionView, status_code=201)
async def create_mission(payload: MissionInput, request: Request, db: Db, user: User = Depends(require_csrf)):
    if user.role != "DISPATCHER":
        raise HTTPException(403, "Réservé au répartiteur")
    driver = await db.get(User, payload.driver_id)
    if not driver or driver.role != "DRIVER" or not driver.is_active:
        raise HTTPException(422, "Chauffeur invalide")
    mission = Mission(title=payload.title, destination=payload.destination, secret_code=encrypt_code(payload.secret_code), status="PENDING", driver_id=driver.id, dispatcher_id=user.id)
    db.add(mission)
    await db.flush()
    await record_audit(db, request, "MISSION_CREATE", f"mission:{mission.id}", user.id)
    await db.commit()
    await db.refresh(mission)
    await hub.notify_driver(driver.id, mission.id)
    return serialize_mission(mission, [])


@app.get("/api/missions", response_model=list[MissionView])
async def list_missions(request: Request, db: Db):
    user = await authenticated_user(request, db)
    if user.role == "DRIVER":
        query = select(Mission).where(Mission.driver_id == user.id)
    elif user.role == "DISPATCHER":
        query = select(Mission).where(Mission.dispatcher_id == user.id)
    else:
        raise HTTPException(403, "Le rôle ADMIN ne donne pas accès au contenu des missions")
    missions = list((await db.scalars(query.order_by(Mission.created_at.desc()).limit(100))).all())
    result = []
    for mission in missions:
        documents = list((await db.scalars(select(Document.id).where(Document.mission_id == mission.id))).all())
        result.append(serialize_mission(mission, documents, reveal_secret_to_driver=user.role == "DRIVER"))
    if user.role == "DRIVER":
        await record_audit(db, request, "MISSION_LIST_READ_SECRET", "missions", user.id)
        await db.commit()
    return result


@app.patch("/api/missions/{mission_id}/status")
async def change_status(mission_id: int, payload: StatusInput, request: Request, db: Db, user: User = Depends(require_csrf)):
    if user.role != "DRIVER":
        raise HTTPException(403, "Réservé au chauffeur")
    mission = await db.get(Mission, mission_id)
    if not mission or mission.driver_id != user.id:
        raise HTTPException(404, "Mission introuvable")
    allowed = {"PENDING": "IN_PROGRESS", "IN_PROGRESS": "COMPLETED"}
    if allowed.get(mission.status) != payload.status:
        raise HTTPException(409, "Transition de statut non autorisée")
    if payload.status == "COMPLETED" and not await db.scalar(select(Document.id).where(Document.mission_id == mission.id).limit(1)):
        raise HTTPException(409, "Une preuve de livraison est requise")
    mission.status = payload.status
    await record_audit(db, request, "MISSION_STATUS_CHANGE", f"mission:{mission.id}", user.id)
    await db.commit()
    return {"id": mission.id, "status": mission.status}


def detect_file(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


async def scan_with_clamav(data: bytes) -> None:
    host = os.getenv("CLAMAV_HOST", "clamav")
    port = int(os.getenv("CLAMAV_PORT", "3310"))
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
    try:
        writer.write(b"zINSTREAM\\0")
        for offset in range(0, len(data), 64 * 1024):
            chunk = data[offset:offset + 64 * 1024]
            writer.write(len(chunk).to_bytes(4, "big") + chunk)
        writer.write(b"\\0\\0\\0\\0")
        await writer.drain()
        answer = await asyncio.wait_for(reader.readline(), timeout=20)
        if b"OK" not in answer or b"FOUND" in answer:
            raise HTTPException(422, "Le document est infecté ou n'a pas pu être analysé")
    finally:
        writer.close()
        await writer.wait_closed()


@app.post("/api/missions/{mission_id}/documents", status_code=201)
async def upload_document(mission_id: int, request: Request, db: Db, upload: UploadFile = File(...), user: User = Depends(require_csrf)):
    if user.role != "DRIVER":
        raise HTTPException(403, "Réservé au chauffeur")
    mission = await db.get(Mission, mission_id)
    if not mission or mission.driver_id != user.id or mission.status != "IN_PROGRESS":
        raise HTTPException(404, "Mission introuvable ou non modifiable")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Taille maximale : 10 Mo")
    mime_type = detect_file(data)
    if not mime_type:
        raise HTTPException(415, "Formats acceptés : JPEG, PNG et PDF")
    try:
        await scan_with_clamav(data)
    except (OSError, asyncio.TimeoutError):
        raise HTTPException(503, "Analyse antivirus indisponible, réessayez plus tard") from None
    document_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{document_id}.{ {'image/jpeg': 'jpg', 'image/png': 'png', 'application/pdf': 'pdf'}[mime_type] }"
    file_path.write_bytes(data)
    document = Document(id=document_id, mission_id=mission.id, file_path=str(file_path), mime_type=mime_type, original_name=Path(upload.filename or "preuve").name[:255])
    db.add(document)
    await record_audit(db, request, "DOCUMENT_UPLOAD", f"mission:{mission.id}/document:{document.id}", user.id)
    await db.commit()
    return {"id": document.id, "mime_type": mime_type}


@app.get("/api/missions/{mission_id}/documents/{document_id}")
async def download_document(mission_id: int, document_id: str, request: Request, db: Db):
    user = await authenticated_user(request, db)
    mission = await db.get(Mission, mission_id)
    document = await db.get(Document, document_id)
    if user.role != "DISPATCHER" or not mission or mission.dispatcher_id != user.id or not document or document.mission_id != mission_id:
        raise HTTPException(404, "Document introuvable")
    await record_audit(db, request, "DOCUMENT_DOWNLOAD", f"mission:{mission_id}/document:{document_id}", user.id)
    await db.commit()
    return FileResponse(document.file_path, media_type=document.mime_type, filename=document.original_name)


@app.get("/api/audit")
async def audit_entries(request: Request, db: Db):
    user = await authenticated_user(request, db)
    if user.role != "ADMIN":
        raise HTTPException(403, "Réservé à l'administration de sécurité")
    entries = list((await db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200))).all())
    return [{"id": e.id, "user_id": e.user_id, "action": e.action, "resource": e.resource, "result": e.result, "ip_address": e.ip_address, "created_at": e.created_at} for e in entries]


@app.websocket("/api/ws")
async def notifications(socket: WebSocket):
    token = socket.cookies.get("gml_access")
    origin = socket.headers.get("origin")
    allowed = os.getenv("GML_ALLOWED_ORIGIN")
    if not token or (allowed and origin != allowed):
        await socket.close(code=1008)
        return
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer="gml-shield", audience="gml-shield-client")
        user_id = int(payload["sub"])
        session_id = str(payload["sid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await socket.close(code=1008)
        return
    async with SessionLocal() as db:
        session = await db.get(LoginSession, session_id)
        user = await db.get(User, user_id)
        if not session or session.revoked_at or session.expires_at <= datetime.now(timezone.utc) or not user or user.role != "DRIVER" or not user.is_active:
            await socket.close(code=1008)
            return
    await hub.add(user_id, socket)
    try:
        while True:
            await asyncio.wait_for(socket.receive_text(), timeout=30)
            async with SessionLocal() as db:
                session = await db.get(LoginSession, session_id)
                if not session or session.revoked_at or session.expires_at <= datetime.now(timezone.utc):
                    await socket.close(code=1008)
                    return
            await socket.send_json({"event": "HEARTBEAT"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        hub.remove(user_id, socket)

