"""#20: Supplier edit-request workflow — the second-approver-reviewed
counterpart to #19's direct edit, for domains where REQUIRES_SEGREGATION
is True (only Supplier today). Deliberately its own module and its own
DB table (MasterRecordEditRequest, db.py) rather than folded into
duplicates.py/DuplicateReviewCase — see that model's own docstring for
why conflating "system-detected duplicate" with "human-proposed
correction" would blur the audit trail's meaning."""

import datetime
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdm.auth import get_current_user
from mdm.db import AuditLogEntry, ExtractionJob, MasterRecord, MasterRecordEditRequest, User, get_session
from mdm.domains import DOMAIN_SPECS
from mdm.duplicates import FieldComparison
from mdm.i18n import t
from mdm.review import _require_approver, _require_approver_or_admin

router = APIRouter()


class MasterRecordEditRequestSubmission(BaseModel):
    field_overrides: dict[str, str]


class MasterRecordEditRequestResponse(BaseModel):
    id: str
    master_record_id: str
    domain: str
    status: str
    submitted_by: str
    reviewed_by: str | None
    comparisons: list[FieldComparison]
    created_at: datetime.datetime
    reviewed_at: datetime.datetime | None


def _build_response(session: Session, edit_request: MasterRecordEditRequest) -> MasterRecordEditRequestResponse:
    record = session.query(MasterRecord).filter_by(id=edit_request.master_record_id).first()
    assert record is not None, "a MasterRecordEditRequest always references a real MasterRecord"
    current_fields = json.loads(record.fields_json)
    proposed_fields = json.loads(edit_request.proposed_fields_json)

    comparisons = [
        FieldComparison(
            field=name,
            old_value=current_fields.get(name),
            new_value=proposed_fields.get(name, current_fields.get(name)),
            new_confidence=None,
            differs=name in proposed_fields and proposed_fields[name] != current_fields.get(name),
        )
        for name in DOMAIN_SPECS[record.domain].master_fields
    ]

    return MasterRecordEditRequestResponse(
        id=edit_request.id,
        master_record_id=edit_request.master_record_id,
        domain=record.domain,
        status=edit_request.status,
        submitted_by=edit_request.submitted_by,
        reviewed_by=edit_request.reviewed_by,
        comparisons=comparisons,
        created_at=edit_request.created_at,
        reviewed_at=edit_request.reviewed_at,
    )


@router.post("/master-records/{record_id}/edit-requests", response_model=MasterRecordEditRequestResponse, status_code=201)
def submit_edit_request(
    record_id: str, payload: MasterRecordEditRequestSubmission, current_user: User = Depends(get_current_user)
) -> MasterRecordEditRequestResponse:
    _require_approver(current_user)

    with get_session() as session:
        record = session.query(MasterRecord).filter_by(id=record_id, is_current=True).first()
        if record is None:
            raise HTTPException(status_code=404, detail=t("master_record_not_found"))

        spec = DOMAIN_SPECS[record.domain]
        if not spec.requires_segregation:
            raise HTTPException(status_code=400, detail=t("edit_request_not_allowed_for_domain"))

        key_field = spec.key_field
        if key_field is not None and key_field in payload.field_overrides:
            raise HTTPException(status_code=422, detail=t("key_field_not_editable", field=key_field))

        editable_fields = set(spec.master_fields) - ({key_field} if key_field is not None else set())
        unknown = set(payload.field_overrides) - editable_fields
        if unknown:
            raise HTTPException(status_code=422, detail=t("unknown_fields_overrides", fields=sorted(unknown)))

        existing_pending = (
            session.query(MasterRecordEditRequest)
            .filter_by(master_record_id=record_id, status="pending")
            .first()
        )
        if existing_pending is not None:
            raise HTTPException(status_code=409, detail=t("edit_request_already_pending"))

        now = datetime.datetime.now(datetime.timezone.utc)
        edit_request = MasterRecordEditRequest(
            id=str(uuid.uuid4()),
            master_record_id=record_id,
            proposed_fields_json=json.dumps(payload.field_overrides),
            submitted_by=current_user.id,
            status="pending",
            created_at=now,
        )
        session.add(edit_request)

        source_job = session.query(ExtractionJob).filter_by(id=record.source_job_id).first()
        assert source_job is not None, "a MasterRecord's source_job_id always references a real ExtractionJob"
        session.add(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                document_id=source_job.document_id,
                action="edit-requested",
                actor_user_id=current_user.id,
                after_json=json.dumps(payload.field_overrides),
                occurred_at=now,
                detail="Edit request submitted via the master data console; requires a different approver's review",
            )
        )

        try:
            session.commit()
        except IntegrityError:
            # The pre-check above is read-then-write, not a lock — two
            # concurrent submissions for the same record can both pass it;
            # the partial unique index (db.py) is the actual backstop.
            session.rollback()
            raise HTTPException(status_code=409, detail=t("edit_request_already_pending")) from None

        return _build_response(session, edit_request)


@router.get("/edit-requests/{request_id}", response_model=MasterRecordEditRequestResponse)
def get_edit_request(request_id: str, current_user: User = Depends(get_current_user)) -> MasterRecordEditRequestResponse:
    _require_approver_or_admin(current_user)

    with get_session() as session:
        edit_request = session.query(MasterRecordEditRequest).filter_by(id=request_id).first()
        if edit_request is None:
            raise HTTPException(status_code=404, detail=t("edit_request_not_found"))
        return _build_response(session, edit_request)


class ResolveEditRequestRequest(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str | None = None


@router.post("/edit-requests/{request_id}/resolve", response_model=MasterRecordEditRequestResponse)
def resolve_edit_request(
    request_id: str, payload: ResolveEditRequestRequest, current_user: User = Depends(get_current_user)
) -> MasterRecordEditRequestResponse:
    _require_approver(current_user)

    with get_session() as session:
        edit_request = session.query(MasterRecordEditRequest).filter_by(id=request_id).first()
        if edit_request is None:
            raise HTTPException(status_code=404, detail=t("edit_request_not_found"))
        if edit_request.status != "pending":
            raise HTTPException(
                status_code=409, detail=t("edit_request_already_decided", status=edit_request.status)
            )

        # Only approving is the fraud-relevant action (a real field change
        # takes effect) — same asymmetry as every other segregation check
        # in this app (e.g. resolve_duplicate's reject_all exemption).
        if payload.decision == "approve" and edit_request.submitted_by == current_user.id:
            raise HTTPException(status_code=403, detail=t("segregation_cannot_approve_own_edit_request"))

        record = session.query(MasterRecord).filter_by(id=edit_request.master_record_id).first()
        assert record is not None, "a MasterRecordEditRequest always references a real MasterRecord"

        now = datetime.datetime.now(datetime.timezone.utc)
        edit_request.reviewed_by = current_user.id
        edit_request.notes = payload.notes
        edit_request.reviewed_at = now

        if payload.decision == "reject":
            edit_request.status = "rejected"
            session.add(
                AuditLogEntry(
                    id=str(uuid.uuid4()),
                    document_id=_source_document_id(session, record),
                    action="rejected",
                    actor_user_id=current_user.id,
                    before_json=edit_request.proposed_fields_json,
                    occurred_at=now,
                    detail="Edit request rejected; the record is unchanged",
                )
            )
            session.commit()
            return _build_response(session, edit_request)

        if not record.is_current:
            raise HTTPException(status_code=409, detail=t("record_changed_concurrently"))

        old_fields = json.loads(record.fields_json)
        proposed = json.loads(edit_request.proposed_fields_json)
        merged = {**old_fields, **proposed}

        new_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=record.domain,
            record_key=record.record_key,
            version=record.version + 1,
            is_current=True,
            fields_json=json.dumps(merged),
            source_job_id=record.source_job_id,
            first_registered_at=record.first_registered_at,
            last_updated_at=now,
        )
        record.is_current = False
        session.add(new_record)
        edit_request.status = "approved"

        session.add(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                document_id=_source_document_id(session, record),
                action="approved",
                actor_user_id=current_user.id,
                before_json=json.dumps(old_fields),
                after_json=json.dumps(merged),
                occurred_at=now,
                detail="Edit request approved by a different approver than the one who submitted it",
            )
        )

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail=t("record_changed_concurrently")) from None

        return _build_response(session, edit_request)


def _source_document_id(session: Session, record: MasterRecord) -> str:
    source_job = session.query(ExtractionJob).filter_by(id=record.source_job_id).first()
    assert source_job is not None, "a MasterRecord's source_job_id always references a real ExtractionJob"
    return source_job.document_id
