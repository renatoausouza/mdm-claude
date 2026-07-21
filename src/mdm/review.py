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
from mdm.db import ApprovalEvent, AuditLogEntry, Document, DuplicateReviewCase, ExtractionJob, MasterRecord, User, get_session
from mdm.domains import DOMAIN_SPECS, fields_dict, find_current_master_record, job_domain
from mdm.i18n import t

router = APIRouter()

# A job can only be decided from these states — anything else (queued,
# extraction_failed, unsupported_format, or already approved/rejected) has
# no scored candidate to review or is already terminal.
_DECIDABLE_STATUSES = {"pending_review", "needs_info"}


class ReviewDecisionRequest(BaseModel):
    notes: str | None = None
    # Lets a reviewer supply/override a master field the candidate itself
    # didn't extract — e.g. assigning a SKU to a no-SKU Product before
    # approving it as new (#11's "assigning a SKU during review if
    # desired"). Validated against the domain's master_fields in
    # approve_job; ignored by reject_job/request_info (this request shape
    # is shared across all three, but only approve creates/updates a
    # MasterRecord).
    field_overrides: dict[str, str] | None = None


class RequestInfoRequest(BaseModel):
    notes: str  # required — "needs info" is meaningless without saying what's needed


class ReviewDecisionResponse(BaseModel):
    job_id: str
    status: str
    master_record_id: str | None = None


def _require_approver(current_user: User) -> None:
    if current_user.role != UserRole.APPROVER.value:
        raise HTTPException(status_code=403, detail=t("approver_only_decisions"))


def _require_approver_or_admin(current_user: User) -> None:
    """For *viewing* master data (#17) — deliberately wider than
    _require_approver, which stays strict for anything that actually
    changes a record (resolve_duplicate, link_duplicate, approve/reject).
    Admin has never had record-decision authority anywhere in this app and
    this doesn't grant it — view-only."""
    if current_user.role not in (UserRole.APPROVER.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail=t("approver_or_admin_only"))


def _load_decidable_job(session: Session, job_id: str) -> tuple[ExtractionJob, Document]:
    job = session.query(ExtractionJob).filter_by(id=job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=t("job_not_found"))
    if job.status not in _DECIDABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=t("job_not_awaiting_decision", status=job.status)
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
            detail=t("job_has_pending_duplicate", case_id=pending.id),
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
        domain = job_domain(job)
        spec = DOMAIN_SPECS[domain]

        # Segregation-of-duties is checked before the duplicate-pending
        # check below: a submitter blocked from approving their own work
        # should always get a plain 403, not a 409 that incidentally
        # reveals duplicate-detection state to someone who can't act on it
        # either way. Domain-driven (#8: Client is self-approvable).
        if spec.requires_segregation and current_user.id == document.uploaded_by:
            raise HTTPException(
                status_code=403,
                detail=t("segregation_cannot_approve_own"),
            )

        _reject_if_duplicate_pending(session, job)

        assert job.result_json is not None, "a decidable job always has a scored result"
        result = spec.result_model.model_validate_json(job.result_json)
        fields = fields_dict(result, spec.master_fields)

        if payload is not None and payload.field_overrides:
            unknown = set(payload.field_overrides) - set(spec.master_fields)
            if unknown:
                raise HTTPException(
                    status_code=422, detail=t("unknown_fields_overrides", fields=sorted(unknown))
                )
            # Applied before the duplicate check below, on purpose: a
            # reviewer manually assigning a SKU that happens to already be
            # registered must still be routed into the normal duplicate
            # flow, not silently create a second record for it.
            fields.update(payload.field_overrides)

        # Last-resort duplicate check: detect_duplicate (where the domain
        # has one) normally runs once at upload time (documents.py), but a
        # second candidate for the same key uploaded *before* the first was
        # approved has no match to see yet — neither upload creates a case,
        # and without this check both could sail through this endpoint
        # independently and register two "current" MasterRecords.
        existing_match = None
        if spec.detect_duplicate is not None and spec.key_field is not None and spec.key_field in fields:
            existing_match = find_current_master_record(session, domain, fields[spec.key_field])
        if existing_match is not None:
            case = DuplicateReviewCase(
                id=str(uuid.uuid4()),
                extraction_job_id=job.id,
                matched_master_record_id=existing_match.id,
                match_key=fields[spec.key_field],  # type: ignore[index]
                status="pending",
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(case)
            session.commit()
            raise HTTPException(
                status_code=409,
                detail=t("matching_record_found", domain=domain.capitalize(), case_id=case.id),
            )

        old_status = job.status
        if not _claim_decision(session, job, "approved"):
            raise HTTPException(status_code=409, detail=t("job_already_decided"))

        now = datetime.datetime.now(datetime.timezone.utc)
        # The domain's natural key (normalized CNPJ/CPF/SKU) only when the
        # domain actually HAS duplicate detection wired up (detect_duplicate
        # is not None) — true for all three domains today (#7 Supplier, #9
        # Client, #11 Product all register detect_duplicate_by_key). The
        # guard stays here (rather than assuming it's always set) because a
        # future domain could still be registered with key_field set but
        # detect_duplicate=None before its dedup ships, same as Client/
        # Product briefly were: the DB enforces at most one is_current row
        # per (domain, record_key) (db.py's unique index), so using the
        # natural key for a domain with no detect_duplicate/resolve path
        # would let a second approval of the "same" record hit that
        # constraint and get stuck in an unresolvable 409, with no case to
        # point it at. A fresh random key sidesteps that until dedup exists.
        natural_key = None
        if spec.key_field is not None and spec.detect_duplicate is not None:
            natural_key = fields.get(spec.key_field)
        master_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=domain,
            record_key=natural_key or str(uuid.uuid4()),
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
            # the same domain+key from ever landing, this check just gives
            # a clean error instead of a raw DB error.
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=t("record_registered_concurrently"),
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
            raise HTTPException(status_code=409, detail=t("job_already_decided"))
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
            raise HTTPException(status_code=409, detail=t("job_already_decided"))
        _record_decision(session, job, document, "needs_info", current_user.id, payload.notes, old_status)
        session.commit()

        return ReviewDecisionResponse(job_id=job.id, status=job.status)
