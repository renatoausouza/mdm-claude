import datetime
import json
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import CursorResult, update
from sqlalchemy.orm import Session

from mdm.auth import UserRole, get_current_user
from mdm.db import ApprovalEvent, AuditLogEntry, Document, ExtractionJob, MasterRecord, User, get_session
from mdm.supplier_extraction import SupplierCandidateResult

router = APIRouter()

# Domains where the approver must be a different user than the submitter
# (D6/FR-13, supplier creation and sensitive-field updates). "supplier" is
# the only extraction domain that exists yet (#4); #8/#10 add client/product
# review reusing this same workflow with segregation left off.
_SEGREGATION_REQUIRED_DOMAINS = {"supplier"}

# A job can only be decided from these states — anything else (queued,
# extraction_failed, unsupported_format, or already approved/rejected) has
# no scored candidate to review or is already terminal.
_DECIDABLE_STATUSES = {"pending_review", "needs_info"}

_SUPPLIER_MASTER_FIELDS = ("cnpj", "legal_name", "email", "telephone", "address")


def _job_domain(job: ExtractionJob) -> str:
    # Every job with a scored result today came from supplier extraction
    # (#4) — there's no per-job domain field yet because no other domain's
    # extraction exists to disambiguate against (#8/#10 will need one).
    return "supplier"


class ReviewDecisionRequest(BaseModel):
    notes: str | None = None


class RequestInfoRequest(BaseModel):
    notes: str  # required — "needs info" is meaningless without saying what's needed


class ReviewDecisionResponse(BaseModel):
    job_id: str
    status: str
    master_record_id: str | None = None


def _require_approver(current_user: User) -> None:
    if current_user.role != UserRole.APPROVER.value:
        raise HTTPException(status_code=403, detail="Only approver accounts may make review decisions")


def _load_decidable_job(session: Session, job_id: str) -> tuple[ExtractionJob, Document]:
    job = session.query(ExtractionJob).filter_by(id=job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in _DECIDABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Job is not awaiting a review decision (status={job.status})"
        )
    document = session.query(Document).filter_by(id=job.document_id).first()
    assert document is not None, "every ExtractionJob row must have a matching Document"
    return job, document


def _claim_decision(session: Session, job: ExtractionJob, new_status: str) -> bool:
    """Atomic compare-and-swap on job.status, conditioned on the exact value
    just read by _load_decidable_job. Without this, two concurrent requests
    (two approvers, or a double-click) can both pass that status check and
    both proceed to create a MasterRecord/ApprovalEvent for the same job.
    Returns False if another request already decided the job in between —
    the caller must not write any MasterRecord/audit data in that case."""
    old_status = job.status
    result = cast(
        "CursorResult[object]",
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job.id, ExtractionJob.status == old_status)
            .values(status=new_status)
        ),
    )
    if result.rowcount == 0:
        return False
    job.status = new_status
    return True


def _record_decision(
    session: Session,
    job: ExtractionJob,
    document: Document,
    decision: str,
    decided_by: str,
    notes: str | None,
    old_status: str,
    master_record_id: str | None = None,
    after_extra: dict[str, object] | None = None,
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    session.add(
        ApprovalEvent(
            id=str(uuid.uuid4()),
            extraction_job_id=job.id,
            submitted_by=document.uploaded_by,
            decided_by=decided_by,
            decision=decision,
            notes=notes,
            decided_at=now,
            master_record_id=master_record_id,
        )
    )
    after: dict[str, object] = {"job_status": decision, "notes": notes}
    if after_extra:
        after.update(after_extra)
    session.add(
        AuditLogEntry(
            id=str(uuid.uuid4()),
            document_id=document.id,
            action=decision,
            actor_user_id=decided_by,
            before_json=json.dumps({"job_status": old_status}),
            after_json=json.dumps(after),
            occurred_at=now,
        )
    )


@router.post("/jobs/{job_id}/approve", response_model=ReviewDecisionResponse)
def approve_job(
    job_id: str,
    payload: ReviewDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> ReviewDecisionResponse:
    # MFA is enforced here transitively: get_current_user only accepts a
    # "full"-scope session, and login() (auth.py) never issues one to an
    # approver account without a verified TOTP code — there is no session
    # an approver can hold at this point that wasn't MFA-gated (D13).
    _require_approver(current_user)

    with get_session() as session:
        job, document = _load_decidable_job(session, job_id)
        domain = _job_domain(job)

        if domain in _SEGREGATION_REQUIRED_DOMAINS and current_user.id == document.uploaded_by:
            raise HTTPException(
                status_code=403,
                detail="Segregation of duties: you cannot approve your own submission for this domain",
            )

        assert job.result_json is not None, "a decidable job always has a scored result"
        result = SupplierCandidateResult.model_validate_json(job.result_json)
        fields = {
            name: field.normalized_value or field.value
            for name in _SUPPLIER_MASTER_FIELDS
            if (field := getattr(result, name)) is not None
        }

        old_status = job.status
        if not _claim_decision(session, job, "approved"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")

        now = datetime.datetime.now(datetime.timezone.utc)
        master_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=domain,
            # normalized CNPJ when present — the same deterministic key #7's
            # dedup/link matching will query on, so a future approval of the
            # same supplier can attach a new version to this record_key
            # instead of #7 needing a one-off migration to backfill it.
            # Falls back to a random key only when CNPJ is missing (a
            # reviewer manually approving an incomplete candidate) — there's
            # nothing stable to match on in that case either way.
            record_key=fields.get("cnpj") or str(uuid.uuid4()),
            version=1,
            is_current=True,
            fields_json=json.dumps(fields),
            source_job_id=job.id,
            first_registered_at=now,
            last_updated_at=now,
        )
        session.add(master_record)

        notes = payload.notes if payload is not None else None
        _record_decision(
            session,
            job,
            document,
            "approved",
            current_user.id,
            notes,
            old_status,
            master_record.id,
            after_extra={"master_record_id": master_record.id, "fields": fields},
        )
        session.commit()

        return ReviewDecisionResponse(job_id=job.id, status=job.status, master_record_id=master_record.id)


@router.post("/jobs/{job_id}/reject", response_model=ReviewDecisionResponse)
def reject_job(
    job_id: str,
    payload: ReviewDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> ReviewDecisionResponse:
    _require_approver(current_user)

    with get_session() as session:
        job, document = _load_decidable_job(session, job_id)
        old_status = job.status
        if not _claim_decision(session, job, "rejected"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")
        notes = payload.notes if payload is not None else None
        _record_decision(session, job, document, "rejected", current_user.id, notes, old_status)
        session.commit()

        return ReviewDecisionResponse(job_id=job.id, status=job.status)


@router.post("/jobs/{job_id}/request-info", response_model=ReviewDecisionResponse)
def request_info(
    job_id: str,
    payload: RequestInfoRequest,
    current_user: User = Depends(get_current_user),
) -> ReviewDecisionResponse:
    _require_approver(current_user)

    with get_session() as session:
        job, document = _load_decidable_job(session, job_id)
        old_status = job.status
        if not _claim_decision(session, job, "needs_info"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")
        _record_decision(session, job, document, "needs_info", current_user.id, payload.notes, old_status)
        session.commit()

        return ReviewDecisionResponse(job_id=job.id, status=job.status)
