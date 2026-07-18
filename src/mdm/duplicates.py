import datetime
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdm.auth import get_current_user
from mdm.db import DuplicateReviewCase, ExtractionJob, MasterRecord, User, get_session
from mdm.review import (
    _SUPPLIER_MASTER_FIELDS,
    _claim_decision,
    _load_decidable_job,
    _normalized_field,
    _record_decision,
    _require_approver,
    _supplier_fields_dict,
)
from mdm.review import detect_supplier_duplicate as detect_supplier_duplicate  # explicit re-export, see below
from mdm.supplier_extraction import SupplierCandidateResult

# detect_supplier_duplicate's implementation lives in review.py (approve_job
# needs it too, and review.py must not import this module — that would be
# circular) but is imported by name above so documents.py's existing
# `from mdm.duplicates import detect_supplier_duplicate` keeps working
# unchanged: this module is the ticket-#7-facing home for "duplicate
# detection", even though review.py's own last-resort check shares the
# same implementation.

router = APIRouter()


class FieldComparison(BaseModel):
    field: str
    old_value: str | None
    new_value: str | None
    new_confidence: float | None
    differs: bool


class DuplicateCaseResponse(BaseModel):
    id: str
    extraction_job_id: str
    matched_master_record_id: str
    match_key: str
    status: str
    comparisons: list[FieldComparison]


def _load_case(session: Session, case_id: str) -> DuplicateReviewCase:
    case = session.query(DuplicateReviewCase).filter_by(id=case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Duplicate review case not found")
    return case


@router.get("/duplicates/{case_id}", response_model=DuplicateCaseResponse)
def get_duplicate_case(case_id: str, current_user: User = Depends(get_current_user)) -> DuplicateCaseResponse:
    with get_session() as session:
        case = _load_case(session, case_id)
        matched = session.query(MasterRecord).filter_by(id=case.matched_master_record_id).first()
        assert matched is not None, "a DuplicateReviewCase always references a real MasterRecord"
        job = session.query(ExtractionJob).filter_by(id=case.extraction_job_id).first()
        assert job is not None and job.result_json is not None

        result = SupplierCandidateResult.model_validate_json(job.result_json)
        old_fields = json.loads(matched.fields_json)

        comparisons = []
        for name in _SUPPLIER_MASTER_FIELDS:
            new_field = getattr(result, name)
            new_value = _normalized_field(new_field) if new_field is not None else None
            old_value = old_fields.get(name)
            comparisons.append(
                FieldComparison(
                    field=name,
                    old_value=old_value,
                    new_value=new_value,
                    new_confidence=new_field.confidence if new_field is not None else None,
                    differs=old_value != new_value,
                )
            )

        return DuplicateCaseResponse(
            id=case.id,
            extraction_job_id=case.extraction_job_id,
            matched_master_record_id=case.matched_master_record_id,
            match_key=case.match_key,
            status=case.status,
            comparisons=comparisons,
        )


class ResolveDuplicateRequest(BaseModel):
    decision: Literal["accept_all", "reject_all", "partial"]
    accepted_fields: list[str] | None = None
    notes: str | None = None


class ResolveDuplicateResponse(BaseModel):
    case_id: str
    status: str
    master_record_id: str | None = None


@router.post("/duplicates/{case_id}/resolve", response_model=ResolveDuplicateResponse)
def resolve_duplicate(
    case_id: str,
    payload: ResolveDuplicateRequest,
    current_user: User = Depends(get_current_user),
) -> ResolveDuplicateResponse:
    _require_approver(current_user)

    if payload.decision == "partial" and not payload.accepted_fields:
        raise HTTPException(status_code=422, detail="partial resolution requires accepted_fields")

    with get_session() as session:
        case = _load_case(session, case_id)
        if case.status != "pending":
            raise HTTPException(
                status_code=409, detail=f"Duplicate review case already resolved (status={case.status})"
            )

        # _load_decidable_job also blocks this job if it has a *different*
        # pending duplicate case, which can't happen (one case per job via
        # the unique extraction_job_id), and enforces the same
        # pending_review/needs_info status gate the normal approve/reject
        # path uses.
        job, document = _load_decidable_job(session, case.extraction_job_id)

        matched = session.query(MasterRecord).filter_by(id=case.matched_master_record_id).first()
        assert matched is not None, "a DuplicateReviewCase always references a real MasterRecord"

        # Resolving a duplicate always updates an existing Supplier record —
        # inherently sensitive (FR-13) regardless of exactly which fields
        # change, so segregation-of-duties applies to every accepting path
        # here. Stricter than FR-13's literal "contact/address/email/phone"
        # carve-out, but never looser, matching #6's same choice to treat
        # "supplier" as always-segregated rather than parsing which fields
        # changed. Rejecting isn't a fraud vector, same precedent as
        # review.py's reject_job.
        if payload.decision != "reject_all" and current_user.id == document.uploaded_by:
            raise HTTPException(
                status_code=403,
                detail="Segregation of duties: you cannot resolve a duplicate for your own submission",
            )

        if payload.decision != "reject_all" and not matched.is_current:
            # Another pending case against this same matched record was
            # resolved first (e.g. two candidates for the same CNPJ
            # uploaded before either was reviewed) — matched is now a
            # superseded version. Applying this case against it would
            # collide the version number with whatever superseded it and
            # silently discard that update. Rejecting is still safe (it
            # doesn't touch the record), so only accept_all/partial block.
            raise HTTPException(
                status_code=409,
                detail="The matched Supplier record has been superseded by another update since "
                "this case was created — re-check for a duplicate against the current version "
                "before resolving this case",
            )

        assert job.result_json is not None, "a decidable job always has a scored result"
        result = SupplierCandidateResult.model_validate_json(job.result_json)
        new_fields = _supplier_fields_dict(result)
        old_fields = json.loads(matched.fields_json)

        old_status = job.status
        now = datetime.datetime.now(datetime.timezone.utc)

        if payload.decision == "reject_all":
            if not _claim_decision(session, job, "rejected"):
                raise HTTPException(status_code=409, detail="Job was already decided by another request")
            case.status = "rejected"
            case.reviewed_by = current_user.id
            case.reviewed_at = now
            _record_decision(
                session,
                job,
                document,
                "rejected",
                current_user.id,
                payload.notes,
                old_status,
                after_extra={"duplicate_review_case_id": case.id},
            )
            session.commit()
            return ResolveDuplicateResponse(case_id=case.id, status=case.status)

        if payload.decision == "accept_all":
            merged = {**old_fields, **new_fields}
            accepted_names = sorted(new_fields.keys())
            resolved_status = "accepted"
        else:  # partial
            accepted = set(payload.accepted_fields or [])
            unknown = accepted - set(_SUPPLIER_MASTER_FIELDS)
            if unknown:
                raise HTTPException(
                    status_code=422, detail=f"Unknown field(s) in accepted_fields: {sorted(unknown)}"
                )
            merged = dict(old_fields)
            for name in accepted:
                if name in new_fields:
                    merged[name] = new_fields[name]
            # Only fields that were both requested AND actually present in
            # the new candidate — a requested field with no extracted value
            # is a no-op (merged keeps the old value), and the audit record
            # of "what was accepted" must reflect what was actually applied,
            # not just what was asked for.
            accepted_names = sorted(accepted & set(new_fields.keys()))
            resolved_status = "partially_accepted"

        if not _claim_decision(session, job, "approved"):
            raise HTTPException(status_code=409, detail="Job was already decided by another request")

        new_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=matched.domain,
            record_key=matched.record_key,
            version=matched.version + 1,
            is_current=True,
            fields_json=json.dumps(merged),
            source_job_id=job.id,
            first_registered_at=matched.first_registered_at,
            last_updated_at=now,
        )
        # Superseded, not deleted — prior versions stay queryable for
        # lineage (§6/§15 of the solution brief).
        matched.is_current = False
        session.add(new_record)

        case.status = resolved_status
        case.reviewed_by = current_user.id
        case.reviewed_at = now
        case.accepted_fields_json = json.dumps(accepted_names)

        _record_decision(
            session,
            job,
            document,
            "approved",
            current_user.id,
            payload.notes,
            old_status,
            new_record.id,
            after_extra={
                "duplicate_review_case_id": case.id,
                "duplicate_resolution": resolved_status,
                "master_record_id": new_record.id,
                "fields": merged,
            },
        )
        try:
            session.commit()
        except IntegrityError:
            # The is_current staleness check above closes the common
            # (sequential) version of this race; the unique index (db.py)
            # is the actual backstop for a genuinely concurrent resolution
            # of two cases against the same record landing at the same
            # instant. Either way, fail cleanly rather than corrupt the
            # versioning invariant.
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="The matched Supplier record was updated by another request just now — "
                "re-check for a duplicate against the current version before resolving this case",
            ) from None

        return ResolveDuplicateResponse(case_id=case.id, status=case.status, master_record_id=new_record.id)
