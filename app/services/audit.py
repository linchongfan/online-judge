from typing import Any

from sqlalchemy.orm import Session

from app.models import AdminAuditLog


def record_audit(
    db: Session,
    actor_id: int | None,
    action: str,
    target_type: str,
    target_id: str | int,
    *,
    details: dict[str, Any] | None = None,
    result: str = "success",
    ip_address: str | None = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        result=result,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
