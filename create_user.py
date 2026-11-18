"""Create an application account from environment variables without echoing its password."""

import asyncio
import os

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


async def create_user_from_environment() -> None:
    email = os.environ["GML_NEW_USER_EMAIL"].strip().lower()
    password = os.environ["GML_NEW_USER_PASSWORD"]
    role = os.environ["GML_NEW_USER_ROLE"].upper()
    if role not in {"ADMIN", "DISPATCHER", "DRIVER"} or len(password) < 14:
        raise SystemExit("Rôle invalide ou mot de passe de moins de 14 caractères")

    async with SessionLocal() as database_session:
        existing_user = await database_session.scalar(select(User).where(User.email == email))
        if existing_user:
            raise SystemExit("Cet e-mail existe déjà")
        database_session.add(User(email=email, password_hash=hash_password(password), role=role))
        await database_session.commit()

    print(f"Compte {role} créé : {email}")


if __name__ == "__main__":
    asyncio.run(create_user_from_environment())
