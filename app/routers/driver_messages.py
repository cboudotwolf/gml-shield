from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.audit import record_audit
from app.dependencies import DatabaseSession, get_authenticated_user, require_csrf_token
from app.models import DriverMessage, User
from app.schemas import DriverMessageInput, DriverMessageView

router = APIRouter(prefix="/api/messages", tags=["messages chauffeur"])


def require_driver(user: User) -> None:
    if user.role != "DRIVER":
        raise HTTPException(403, "Réservé au chauffeur")


@router.post("", response_model=DriverMessageView, status_code=201)
async def create_driver_message(
    message_input: DriverMessageInput,
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(require_csrf_token)],
) -> DriverMessageView:
    """Derive ownership from the session so clients cannot write for another driver."""
    require_driver(user)
    driver_message = DriverMessage(driver_id=user.id, content=message_input.content)
    database_session.add(driver_message)
    await database_session.flush()
    await record_audit(
        database_session,
        request,
        "DRIVER_MESSAGE_CREATE",
        f"message:{driver_message.id}",
        user.id,
    )
    await database_session.commit()
    await database_session.refresh(driver_message)
    return DriverMessageView.model_validate(driver_message)


@router.get("", response_model=list[DriverMessageView])
async def list_driver_messages(
    request: Request,
    database_session: DatabaseSession,
    user: Annotated[User, Depends(get_authenticated_user)],
) -> list[DriverMessageView]:
    """Filter at query time to avoid loading or exposing another driver's messages."""
    require_driver(user)
    message_query = (
        select(DriverMessage)
        .where(DriverMessage.driver_id == user.id)
        .order_by(DriverMessage.created_at.desc(), DriverMessage.id.desc())
        .limit(100)
    )
    driver_messages = list((await database_session.scalars(message_query)).all())
    await record_audit(
        database_session, request, "DRIVER_MESSAGES_READ", "driver_messages", user.id
    )
    await database_session.commit()
    return [DriverMessageView.model_validate(message) for message in driver_messages]
