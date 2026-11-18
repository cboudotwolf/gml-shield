from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    database_session: AsyncSession,
    request: Request | None,
    action: str,
    resource: str,
    user_id: int | None,
    result: str = "SUCCESS",
) -> None:
    client_ip = request.client.host if request and request.client else "unknown"
    database_session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            result=result,
            ip_address=client_ip,
        )
    )
    await database_session.flush()
