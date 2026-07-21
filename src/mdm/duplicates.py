import datetime
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdm.auth import get_current_user
from mdm.db import (
    AuditLogEntry,
    Document,
    DuplicateReviewCase,
    ExtractionJob,
    MasterRecord,
    MasterRecordEditRequest,
    User,
    get_session,
)
from mdm.domains import DOMAIN_SPECS, fields_dict, job_domain, normalized_field
from mdm.i18n import t
from mdm.review import (
    _claim_decision,
    _load_decidable_job,
    _record_decision,
    _reject_if_duplicate_pending,
    _require_approver,
    _require_approver_or_admin,
)

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
    domain: str
    uploaded_by: str | None = None


def _load_case(session: Session, case_id: str) -> DuplicateReviewCase:
    case = session.query(DuplicateReviewCase).filter_by(id=case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail=t("duplicate_case_not_found"))
    return case


@router.get("/duplicates/{case_id}", response_model=DuplicateCaseResponse)
def get_duplicate_case(case_id: str, current_user: User = Depends(get_current_user)) -> DuplicateCaseResponse:
    with get_session() as session:
        case = _load_case(session, case_id)
        matched = session.query(MasterRecord).filter_by(id=case.matched_master_record_id).first()
        assert matched is not None, "a DuplicateReviewCase always references a real MasterRecord"
        job = session.query(ExtractionJob).filter_by(id=case.extraction_job_id).first()
        assert job is not None and job.result_json is not None
        document = session.query(Document).filter_by(id=job.document_id).first()

        spec = DOMAIN_SPECS[matched.domain]
        result = spec.result_model.model_validate_json(job.result_json)
        old_fields = json.loads(matched.fields_json)

        comparisons = []
        for name in spec.master_fields:
            new_field = getattr(result, name, None)
            new_value = normalized_field(new_field) if new_field is not None else None
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
            domain=matched.domain,
            uploaded_by=document.uploaded_by if document is not None else None,
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
        raise HTTPException(status_code=422, detail=t("partial_requires_accepted_fields"))

    with get_session() as session:
        case = _load_case(session, case_id)
        if case.status != "pending":
            raise HTTPException(
                status_code=409, detail=t("duplicate_case_already_resolved", status=case.status)
            )

        # _load_decidable_job also blocks this job if it has a *different*
        # pending duplicate case, which can't happen (one case per job via
        # the unique extraction_job_id), and enforces the same
        # pending_review/needs_info status gate the normal approve/reject
        # path uses.
        job, document = _load_decidable_job(session, case.extraction_job_id)

        matched = session.query(MasterRecord).filter_by(id=case.matched_master_record_id).first()
        assert matched is not None, "a DuplicateReviewCase always references a real MasterRecord"
        spec = DOMAIN_SPECS[matched.domain]

        # Resolving a duplicate always updates an existing record — for any
        # domain with segregation-of-duties enabled (only Supplier today,
        # #8's Client is explicitly self-approvable), that applies to every
        # accepting path here regardless of exactly which fields change,
        # matching #6's same choice for creation. Rejecting isn't a fraud
        # vector, same precedent as review.py's reject_job.
        if payload.decision != "reject_all" and spec.requires_segregation and current_user.id == document.uploaded_by:
            raise HTTPException(
                status_code=403,
                detail=t("segregation_cannot_resolve_own"),
            )

        if payload.decision != "reject_all" and not matched.is_current:
            # Another pending case against this same matched record was
            # resolved first (e.g. two candidates for the same key uploaded
            # before either was reviewed) — matched is now a superseded
            # version. Applying this case against it would collide the
            # version number with whatever superseded it and silently
            # discard that update. Rejecting is still safe (it doesn't
            # touch the record), so only accept_all/partial block.
            raise HTTPException(
                status_code=409,
                detail=t("matched_record_superseded"),
            )

        assert job.result_json is not None, "a decidable job always has a scored result"
        result = spec.result_model.model_validate_json(job.result_json)
        new_fields = fields_dict(result, spec.master_fields)
        old_fields = json.loads(matched.fields_json)

        old_status = job.status
        now = datetime.datetime.now(datetime.timezone.utc)

        if payload.decision == "reject_all":
            if not _claim_decision(session, job, "rejected"):
                raise HTTPException(status_code=409, detail=t("job_already_decided"))
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
            unknown = accepted - set(spec.master_fields)
            if unknown:
                raise HTTPException(
                    status_code=422, detail=t("unknown_fields_accepted", fields=sorted(unknown))
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
            raise HTTPException(status_code=409, detail=t("job_already_decided"))

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
                detail=t("matched_record_updated_concurrently"),
            ) from None

        return ResolveDuplicateResponse(case_id=case.id, status=case.status, master_record_id=new_record.id)


class MasterRecordSearchResult(BaseModel):
    id: str
    domain: str
    record_key: str
    version: int
    fields: dict[str, str]


class MasterRecordSearchResponse(BaseModel):
    results: list[MasterRecordSearchResult]
    has_more: bool = False


_SEARCH_DEFAULT_LIMIT = 50


def search_records(session: Session, domain: str, q: str, offset: int, limit: int) -> MasterRecordSearchResponse:
    """The actual substring-search mechanism — factored out of the HTTP
    endpoint below so #21's chat feature can execute an LLM-proposed
    filter through this exact same safe, parameterized path instead of a
    second query mechanism. Assumes `domain` is already validated; auth
    and domain-validity checks stay in each caller (they differ: the HTTP
    endpoint 400s on a bad domain, the chat feature just treats an invalid
    LLM-proposed domain as "no filter produced")."""
    query = q.strip().lower()
    # Ordered explicitly (not relying on incidental insertion order) so
    # offset-based paging returns a stable, non-overlapping sequence of
    # pages across requests — most-recently-updated first, matching the
    # "recent first" convention list_jobs/list_audit_log already use.
    records = (
        session.query(MasterRecord)
        .filter_by(domain=domain, is_current=True)
        .order_by(MasterRecord.last_updated_at.desc())
        .all()
    )

    matches: list[MasterRecordSearchResult] = []
    for record in records:
        fields = json.loads(record.fields_json)
        haystack = " ".join(str(v) for v in fields.values()).lower()
        if query and query not in haystack:
            continue
        matches.append(
            MasterRecordSearchResult(
                id=record.id, domain=record.domain, record_key=record.record_key, version=record.version, fields=fields
            )
        )

    page = matches[offset : offset + limit]
    has_more = len(matches) > offset + limit
    return MasterRecordSearchResponse(results=page, has_more=has_more)


@router.get("/master-records/search", response_model=MasterRecordSearchResponse)
def search_master_records(
    domain: str,
    q: str = "",
    offset: int = 0,
    limit: int = _SEARCH_DEFAULT_LIMIT,
    current_user: User = Depends(get_current_user),
) -> MasterRecordSearchResponse:
    """Two callers: the reviewer-driven "find a record to link a candidate
    against" tool (#11 — e.g. a no-SKU Product candidate, which
    detect_duplicate_by_key in domains.py never auto-matches per FR-11's no
    NCM+name fallback, no fuzzy matching, ever), and #17's browse/search
    master-data console. This endpoint itself does no matching or linking —
    it's plain substring search over current records' field values for a
    human to browse; an actual link only happens if a reviewer explicitly
    calls POST /jobs/{job_id}/link-duplicate with a specific
    master_record_id picked from these results. Approver-or-admin (like the
    detail endpoint below, but stricter than plain view elsewhere — every
    current record's full field set, including PII (CPF/CNPJ, email,
    phone, address), is returned unfiltered, so this is not a
    submitter-safe browse surface)."""
    _require_approver_or_admin(current_user)

    if domain not in DOMAIN_SPECS:
        raise HTTPException(
            status_code=400, detail=t("unknown_domain", domain=repr(domain), choices=sorted(DOMAIN_SPECS))
        )

    with get_session() as session:
        return search_records(session, domain, q, offset, limit)


class MasterRecordDetailResponse(BaseModel):
    id: str
    domain: str
    record_key: str
    version: int
    fields: dict[str, str]
    first_registered_at: datetime.datetime
    last_updated_at: datetime.datetime
    # Set when a #20 edit request (Supplier's second-approver-reviewed
    # correction) is awaiting review for this record — lets the detail
    # page surface "there's a pending proposal" the same way job results
    # already surface duplicate_review_case_id.
    pending_edit_request_id: str | None = None


@router.get("/master-records/{record_id}", response_model=MasterRecordDetailResponse)
def get_master_record(record_id: str, current_user: User = Depends(get_current_user)) -> MasterRecordDetailResponse:
    """The read-only record detail view #17 needs (a stable, refreshable
    URL — not just an in-memory search result), and the fetch-by-id #19/#20
    build their edit flows on top of. Current-version only: an edit
    proposal always targets whatever is current right now, never a
    superseded historical version."""
    _require_approver_or_admin(current_user)

    with get_session() as session:
        record = session.query(MasterRecord).filter_by(id=record_id, is_current=True).first()
        if record is None:
            raise HTTPException(status_code=404, detail=t("master_record_not_found"))
        pending_edit_request = (
            session.query(MasterRecordEditRequest).filter_by(master_record_id=record.id, status="pending").first()
        )
        return MasterRecordDetailResponse(
            id=record.id,
            domain=record.domain,
            record_key=record.record_key,
            version=record.version,
            fields=json.loads(record.fields_json),
            first_registered_at=record.first_registered_at,
            last_updated_at=record.last_updated_at,
            pending_edit_request_id=pending_edit_request.id if pending_edit_request is not None else None,
        )


class MasterRecordDirectEditBody(BaseModel):
    field_overrides: dict[str, str]


@router.post("/master-records/{record_id}/edit", response_model=MasterRecordDetailResponse)
def edit_master_record(
    record_id: str, payload: MasterRecordDirectEditBody, current_user: User = Depends(get_current_user)
) -> MasterRecordDetailResponse:
    """#19: direct-write edit for Client/Product — no second-person
    approval, mirroring REQUIRES_SEGREGATION exactly like every other
    mutation path in this app (Supplier is rejected below; it goes through
    #20's edit-request workflow instead). Strictly approver-only, not
    admin — see _require_approver_or_admin's own docstring for why viewing
    and deciding are gated differently."""
    _require_approver(current_user)

    with get_session() as session:
        record = session.query(MasterRecord).filter_by(id=record_id, is_current=True).first()
        if record is None:
            raise HTTPException(status_code=404, detail=t("master_record_not_found"))

        spec = DOMAIN_SPECS[record.domain]
        if spec.requires_segregation:
            raise HTTPException(status_code=400, detail=t("direct_edit_not_allowed_for_domain"))

        key_field = spec.key_field
        if key_field is not None and key_field in payload.field_overrides:
            raise HTTPException(status_code=422, detail=t("key_field_not_editable", field=key_field))

        editable_fields = set(spec.master_fields) - ({key_field} if key_field is not None else set())
        unknown = set(payload.field_overrides) - editable_fields
        if unknown:
            raise HTTPException(status_code=422, detail=t("unknown_fields_overrides", fields=sorted(unknown)))

        old_fields = json.loads(record.fields_json)
        merged = {**old_fields, **payload.field_overrides}
        now = datetime.datetime.now(datetime.timezone.utc)

        new_record = MasterRecord(
            id=str(uuid.uuid4()),
            domain=record.domain,
            record_key=record.record_key,
            version=record.version + 1,
            is_current=True,
            fields_json=json.dumps(merged),
            # Carried forward, not a new job — a direct edit has no
            # extraction behind it. This keeps the required FK honest
            # (source_job_id has no nullable/"no document" escape hatch)
            # without inventing a fictional job; the version's lineage
            # still correctly traces back to whatever originally
            # registered this record.
            source_job_id=record.source_job_id,
            first_registered_at=record.first_registered_at,
            last_updated_at=now,
        )
        record.is_current = False
        session.add(new_record)

        # Same reasoning as source_job_id above: an edit has no document of
        # its own, so the audit entry points at the record's original
        # source document — detail below makes it unambiguous this entry
        # is a manual edit, not something that document's extraction did.
        source_job = session.query(ExtractionJob).filter_by(id=record.source_job_id).first()
        assert source_job is not None, "a MasterRecord's source_job_id always references a real ExtractionJob"
        session.add(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                document_id=source_job.document_id,
                action="edited",
                actor_user_id=current_user.id,
                before_json=json.dumps(old_fields),
                after_json=json.dumps(merged),
                occurred_at=now,
                detail="Manual field edit via the master data console — not related to this document's own extraction",
            )
        )

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail=t("record_changed_concurrently")) from None

        return MasterRecordDetailResponse(
            id=new_record.id,
            domain=new_record.domain,
            record_key=new_record.record_key,
            version=new_record.version,
            fields=merged,
            first_registered_at=new_record.first_registered_at,
            last_updated_at=new_record.last_updated_at,
        )


class LinkDuplicateRequest(BaseModel):
    master_record_id: str
    notes: str | None = None


class LinkDuplicateResponse(BaseModel):
    case_id: str
    status: str


@router.post("/jobs/{job_id}/link-duplicate", response_model=LinkDuplicateResponse, status_code=201)
def link_duplicate(
    job_id: str, payload: LinkDuplicateRequest, current_user: User = Depends(get_current_user)
) -> LinkDuplicateResponse:
    """Manually create a DuplicateReviewCase against a reviewer-chosen
    record (#11's "manual search/link tooling") — the human-driven
    counterpart to detect_duplicate_by_key's automatic exact-match case
    creation. Once created, the case goes through the exact same side-by-
    side/accept/reject/partial resolution as any auto-detected case
    (GET/POST /duplicates/{case_id}...)."""
    _require_approver(current_user)

    with get_session() as session:
        job, document = _load_decidable_job(session, job_id)
        # A job can only ever have one DuplicateReviewCase (the DB enforces
        # a unique extraction_job_id) — refuse to attempt a second one
        # rather than let that surface as a raw IntegrityError.
        _reject_if_duplicate_pending(session, job)

        matched = session.query(MasterRecord).filter_by(id=payload.master_record_id, is_current=True).first()
        if matched is None:
            raise HTTPException(status_code=404, detail=t("master_record_not_found"))

        domain = job_domain(job)
        if matched.domain != domain:
            raise HTTPException(
                status_code=400,
                detail=t("cannot_link_domain_mismatch", domain=repr(domain), other_domain=repr(matched.domain)),
            )

        now = datetime.datetime.now(datetime.timezone.utc)
        case = DuplicateReviewCase(
            id=str(uuid.uuid4()),
            extraction_job_id=job.id,
            matched_master_record_id=matched.id,
            # Not derived from any field — a reviewer-chosen link, not an
            # exact-match result. FR-11's "no fuzzy/similarity matching"
            # constrains the AUTOMATIC path (detect_duplicate_by_key); this
            # is an explicit, human-confirmed decision, not the system
            # guessing at a weaker key.
            match_key="manual",
            status="pending",
            created_at=now,
        )
        session.add(case)
        session.add(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                document_id=document.id,
                action="link-duplicate",  # FR-19's own vocabulary for this action
                actor_user_id=current_user.id,
                before_json=json.dumps({"job_status": job.status}),
                after_json=json.dumps(
                    {"duplicate_review_case_id": case.id, "matched_master_record_id": matched.id, "notes": payload.notes}
                ),
                occurred_at=now,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            # _reject_if_duplicate_pending above is a read-then-write check,
            # not a lock — two concurrent link/resolve attempts for the same
            # job can both pass it before either commits. The DB's unique
            # extraction_job_id constraint on DuplicateReviewCase is the
            # actual backstop; this just turns the loser's raw IntegrityError
            # into the same clean 409 approve_job/resolve_duplicate give for
            # their own analogous races.
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=t("job_just_linked_duplicate"),
            ) from None

        return LinkDuplicateResponse(case_id=case.id, status=case.status)
