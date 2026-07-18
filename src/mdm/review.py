import datetime
import json
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import CursorResult, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdm.auth import UserRole, get_current_user
from mdm.db import (
    ApprovalEvent,
    AuditLogEntry,
    Document,
    DuplicateReviewCase,
    ExtractionJob,
    MasterRecord,
    User,
    get_session,
)
from mdm.supplier_extraction import FieldValue, SupplierCandidateResult

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


def _normalized_field(field: FieldValue) -> str:
    # Single source of truth for "which representation of a field goes into
    # a MasterRecord/match key" — used for both record_key (this module) and
    # DuplicateReviewCase.match_key (duplicates.py), so the two can never
    # silently diverge (they're the same value by construction, not by two
    # independently-written expressions kept in sync by hand).
    return field.normalized_value or field.value


def _supplier_fields_dict(result: SupplierCandidateResult) -> dict[str, str]:
    return {
        name: _normalized_field(field)
        for name in _SUPPLIER_MASTER_FIELDS
        if (field := getattr(result, name)) is not None
    }


def _find_current_master_record(session: Session, domain: str, record_key: str) -> MasterRecord | None:
    return session.query(MasterRecord).filter_by(domain=domain, record_key=record_key, is_current=True).first()


def detect_supplier_duplicate(
    session: Session, job: ExtractionJob, result: SupplierCandidateResult
) -> DuplicateReviewCase | None:
    """Exact-match CNPJ dedup against already-registered current Supplier
    records (FR-09, #7). Never merges anything itself — only flags for a
    human (D4/D2); the caller is responsible for adding the returned case to
    the session (it isn't committed here).

    Called from two places: documents.py right after a candidate is scored
    (so the case exists alongside PendingReview, per the state machine in
    solution-brief.md §7), and approve_job below as a last-resort check —
    detection only runs once at upload time, so a second candidate for the
    same CNPJ uploaded *before* the first is approved would otherwise slip
    through with no case at all (neither upload could see the other yet)."""
    if result.cnpj is None:
        return None
    match_key = _normalized_field(result.cnpj)
    matched = _find_current_master_record(session, "supplier", match_key)
    if matched is None:
        return None
    return DuplicateReviewCase(
        id=str(uuid.uuid4()),
        extraction_job_id=job.id,
        matched_master_record_id=matched.id,
        match_key=match_key,
        status="pending",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )


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


def _reject_if_duplicate_pending(session: Session, job: ExtractionJob) -> None:
    """approve/reject/request-info (this module) must not touch a job that
    has an unresolved DuplicateReviewCase (#7) — that job's MasterRecord
    decision belongs to POST /duplicates/{case_id}/resolve instead, which
    calls _load_decidable_job directly and does NOT call this check (it IS
    the resolution path for that exact case)."""
    pending = session.query(DuplicateReviewCase).filter_by(extraction_job_id=job.id, status="pending").first()
    if pending is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Job has a pending duplicate review case ({pending.id}) — "
            "resolve it via POST /duplicates/{case_id}/resolve instead",
        )


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

        # Segregation-of-duties is checked before the duplicate-pending
        # check below: a submitter blocked from approving their own work
        # should always get a plain 403, not a 409 that incidentally
        # reveals duplicate-detection state to someone who can't act on it
        # either way.
        if domain in _SEGREGATION_REQUIRED_DOMAINS and current_user.id == document.uploaded_by:
            raise HTTPException(
                status_code=403,
                detail="Segregation of duties: you cannot approve your own submission for this domain",
            )

        _reject_if_duplicate_pending(session, job)

        assert job.result_json is not None, "a decidable job always has a scored result"
        result = SupplierCandidateResult.model_validate_json(job.result_json)
        fields = _supplier_fields_dict(result)

        # Last-resort duplicate check: detect_supplier_duplicate normally
        # runs once at upload time (documents.py), but a second candidate
        # for the same CNPJ uploaded *before* the first was approved has no
        # match to see yet — neither upload creates a case, and without this
        # check both could sail through this endpoint independently and
        # register two "current" MasterRecords for the same supplier.
        existing_match = _find_current_master_record(session, domain, fields["cnpj"]) if "cnpj" in fields else None
        if existing_match is not None:
            case = DuplicateReviewCase(
                id=str(uuid.uuid4()),
                extraction_job_id=job.id,
                matched_master_record_id=existing_match.id,
                match_key=fields["cnpj"],
                status="pending",
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(case)
            session.commit()
            raise HTTPException(
                status_code=409,
                detail=f"A matching Supplier record already exists — duplicate review case "
                f"{case.id} created; resolve it via POST /duplicates/{case.id}/resolve instead",
            )

        old_status = job.status
        if not _claim_decision(session, job, "approved"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")

        now = datetime.datetime.now(datetime.timezone.utc)
        master_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=domain,
            # normalized CNPJ when present — the same deterministic key #7's
            # dedup/link matching queries on, so a future approval of the
            # same supplier attaches a new version to this record_key
            # instead of needing a one-off backfill migration. Falls back to
            # a random key only when CNPJ is missing (a reviewer manually
            # approving an incomplete candidate) — there's nothing stable to
            # match on in that case either way.
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
        try:
            session.commit()
        except IntegrityError:
            # A concurrent approve_job/resolve_duplicate for the same
            # record_key committed in the narrow window between the
            # existing_match check above and this commit — the unique
            # index (db.py) is what actually stops two "current" rows for
            # the same supplier from ever landing, this check just gives a
            # clean error instead of a raw DB error.
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="A matching Supplier record was just registered by another request — retry to "
                "pick up the resulting duplicate review case",
            ) from None

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
        _reject_if_duplicate_pending(session, job)
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
        _reject_if_duplicate_pending(session, job)
        old_status = job.status
        if not _claim_decision(session, job, "needs_info"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")
        _record_decision(session, job, document, "needs_info", current_user.id, payload.notes, old_status)
        session.commit()

        return ReviewDecisionResponse(job_id=job.id, status=job.status)
