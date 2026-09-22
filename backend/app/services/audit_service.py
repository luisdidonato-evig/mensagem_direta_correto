from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import AuditLog


def add_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor: str = "system",
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )
