"""Create an initial user interactively through environment variables."""
import asyncio
import os
from argon2 import PasswordHasher
from sqlalchemy import select
from app.main import SessionLocal, User

async def main():
    email = os.environ["GML_NEW_USER_EMAIL"].strip().lower()
    password = os.environ["GML_NEW_USER_PASSWORD"]
    role = os.environ["GML_NEW_USER_ROLE"].upper()
    if role not in {"ADMIN", "DISPATCHER", "DRIVER"} or len(password) < 14:
        raise SystemExit("Rôle invalide ou mot de passe de moins de 14 caractères")
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.email == email)):
            raise SystemExit("Cet e-mail existe déjà")
        db.add(User(email=email, password_hash=PasswordHasher().hash(password), role=role))
        await db.commit()
    print(f"Compte {role} créé : {email}")

asyncio.run(main())
