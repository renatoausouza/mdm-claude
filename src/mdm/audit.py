import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mdm.auth import UserRole, get_current_user
from mdm.db import AuditLogEntry, User, get_session

router = APIRouter()

# solution-brief.md §16 lists GET /audit "scoped to auditor/admin" — this
# codebase has no separate "auditor" role (UserRole is submitter/approver/
# admin only, #3), so this is scoped to admin, the closest existing role
# with no domain-specific stake in what's being audited.
_AUDIT_LOG_LIMIT = 200


class AuditLogEntryResponse(BaseModel):
    id: str
    document_id: str
    action: str
    actor_user_id: str | None
    before_json: str | None
    after_json: str | None
    detail: str | None
    occurred_at: datetime.datetime


class AuditLogListResponse(BaseModel):
    entries: list[AuditLogEntryResponse]


@router.get("/audit", response_model=AuditLogListResponse)
def list_audit_log(
    document_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> AuditLogListResponse:
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Only admin accounts may view the audit log")

    with get_session() as session:
        query = session.query(AuditLogEntry)
        if document_id is not None:
            query = query.filter_by(document_id=document_id)
        entries = query.order_by(AuditLogEntry.occurred_at.desc()).limit(_AUDIT_LOG_LIMIT).all()

    return AuditLogListResponse(
        entries=[
            AuditLogEntryResponse(
                id=entry.id,
                document_id=entry.document_id,
                action=entry.action,
                actor_user_id=entry.actor_user_id,
                before_json=entry.before_json,
                after_json=entry.after_json,
                detail=entry.detail,
                occurred_at=entry.occurred_at,
            )
            for entry in entries
        ]
    )
