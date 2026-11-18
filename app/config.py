from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    jwt_secret: str
    aes_key: bytes
    allowed_origin: str
    cookie_secure: bool
    private_upload_directory: Path
    max_upload_bytes: int = 10_000_000


def load_settings() -> Settings:
    required_values = {
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "GML_JWT_SECRET": os.getenv("GML_JWT_SECRET"),
        "GML_AES_KEY_B64": os.getenv("GML_AES_KEY_B64"),
        "GML_ALLOWED_ORIGIN": os.getenv("GML_ALLOWED_ORIGIN"),
    }
    missing_values = [name for name, value in required_values.items() if not value]
    if missing_values:
        raise RuntimeError(f"Variables d'environnement manquantes : {', '.join(missing_values)}")

    jwt_secret = required_values["GML_JWT_SECRET"]
    if len(jwt_secret) < 32:
        raise RuntimeError("GML_JWT_SECRET doit contenir au moins 32 caractères")

    try:
        aes_key = base64.b64decode(required_values["GML_AES_KEY_B64"], validate=True)
    except (binascii.Error, ValueError):
        raise RuntimeError("GML_AES_KEY_B64 doit encoder une clé valide de 32 octets") from None
    if len(aes_key) != 32:
        raise RuntimeError("GML_AES_KEY_B64 doit encoder une clé de 32 octets")

    cookie_secure_value = os.getenv("GML_COOKIE_SECURE", "true").lower()
    if cookie_secure_value not in {"true", "false"}:
        raise RuntimeError("GML_COOKIE_SECURE doit valoir true ou false")
    cookie_secure = cookie_secure_value == "true"

    allowed_origin = required_values["GML_ALLOWED_ORIGIN"].rstrip("/")
    parsed_origin = urlsplit(allowed_origin)
    if (
        parsed_origin.scheme not in {"http", "https"}
        or not parsed_origin.netloc
        or parsed_origin.path
    ):
        raise RuntimeError("GML_ALLOWED_ORIGIN doit être une origine HTTP(S) sans chemin")
    if cookie_secure and parsed_origin.scheme != "https":
        raise RuntimeError("GML_ALLOWED_ORIGIN doit utiliser HTTPS lorsque GML_COOKIE_SECURE=true")

    return Settings(
        database_url=required_values["DATABASE_URL"],
        jwt_secret=jwt_secret,
        aes_key=aes_key,
        allowed_origin=allowed_origin,
        cookie_secure=cookie_secure,
        private_upload_directory=Path(os.getenv("GML_PRIVATE_UPLOADS", "/data/private_uploads")),
    )
