import datetime
import hashlib
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from mdm import config, storage
from mdm.auth import get_current_user
from mdm.db import AuditLogEntry, Document, DuplicateReviewCase, ExtractionJob, User, get_session
from mdm.domains import DOMAIN_SPECS, job_domain
from mdm.scoring import ScoringResult

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".msg", ".json", ".xml", ".txt", ".log", ".png", ".jpg", ".jpeg"}


class JobResponse(BaseModel):
    id: str
    document_id: str
    content_hash: str
    status: str
    retention_until: datetime.datetime | None
    duplicate_review_case_id: str | None = None


def _compute_retention_until() -> datetime.datetime | None:
    retention_days = config.get_retention_days()
    if retention_days is None:
        return None
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=retention_days)


def _to_response(document: Document, job: ExtractionJob, duplicate_review_case_id: str | None = None) -> JobResponse:
    return JobResponse(
        id=job.id,
        document_id=document.id,
        content_hash=document.content_hash,
        status=job.status,
        retention_until=document.retention_until,
        duplicate_review_case_id=duplicate_review_case_id,
    )


@router.post("/documents", response_model=JobResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    domain: str = Form("supplier"),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    spec = DOMAIN_SPECS.get(domain)
    if spec is None:
        raise HTTPException(
            status_code=400, detail=f"Unsupported domain: {domain!r} (must be one of {sorted(DOMAIN_SPECS)})"
        )

    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {extension or '(none)'}")

    # A plain sync route (not async def) so FastAPI runs it in its
    # threadpool rather than blocking the event loop on the DB/disk work
    # below — file.file.read() is the sync counterpart to await file.read().
    content = file.file.read()
    max_bytes = config.get_max_upload_bytes()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds the {max_bytes}-byte upload limit")

    content_hash = hashlib.sha256(content).hexdigest()

    with get_session() as session:
        existing_document = session.query(Document).filter_by(content_hash=content_hash).first()
        if existing_document is not None:
            job = session.query(ExtractionJob).filter_by(document_id=existing_document.id).first()
            assert job is not None, "every Document row must have a matching ExtractionJob"
            # Content-hash idempotency (#2) predates multi-domain uploads
            # (#8/#10) and is keyed purely by file bytes — one Document has
            # exactly one ExtractionJob (a hard 1:1, DB-enforced). Silently
            # returning that job's Supplier result for a re-upload someone
            # explicitly requested as domain="client" would hand back the
            # wrong candidate with no indication anything was ignored; fail
            # loud instead of guessing which domain the caller actually
            # wants for this content.
            existing_domain = job_domain(job)
            if existing_domain != domain:
                raise HTTPException(
                    status_code=409,
                    detail=f"This content was already uploaded under domain={existing_domain!r}; "
                    f"re-uploading identical content under a different domain ({domain!r}) is not supported.",
                )
            existing_duplicate_case = (
                session.query(DuplicateReviewCase).filter_by(extraction_job_id=job.id, status="pending").first()
            )
            existing_duplicate_case_id = existing_duplicate_case.id if existing_duplicate_case is not None else None
            if not storage.document_exists(existing_document.id):
                if existing_document.purged_at is not None:
                    # The file was intentionally removed by the retention
                    # purge job (#13), not lost to corruption — re-upload of
                    # identical content restores it rather than raising the
                    # same alarm as unexpected data loss.
                    storage.save_document(existing_document.id, content)
                    existing_document.purged_at = None
                    existing_document.retention_until = _compute_retention_until()
                    session.add(
                        AuditLogEntry(
                            id=str(uuid.uuid4()),
                            document_id=existing_document.id,
                            action="restored",
                            actor_user_id=current_user.id,
                            occurred_at=datetime.datetime.now(datetime.timezone.utc),
                            detail="Re-uploaded after retention purge; file restored to storage",
                        )
                    )
                    session.commit()
                    return _to_response(existing_document, job, existing_duplicate_case_id)
                raise HTTPException(
                    status_code=500,
                    detail="Document record exists but its stored file is missing",
                )
            if current_user.id != existing_document.uploaded_by:
                # A different user re-uploading byte-identical content is
                # still their own submit action and belongs in the audit
                # trail (FR-19) — even though it doesn't change
                # Document.uploaded_by (that stays the original submitter,
                # which is what the segregation-of-duties check keys off).
                session.add(
                    AuditLogEntry(
                        id=str(uuid.uuid4()),
                        document_id=existing_document.id,
                        action="submitted",
                        actor_user_id=current_user.id,
                        after_json=json.dumps({"job_status": job.status}),
                        detail="Re-upload of already-registered content by a different user",
                        occurred_at=datetime.datetime.now(datetime.timezone.utc),
                    )
                )
                session.commit()
            return _to_response(existing_document, job, existing_duplicate_case_id)

        document_id = str(uuid.uuid4())
        document = Document(
            id=document_id,
            content_hash=content_hash,
            content_type=file.content_type or "application/octet-stream",
            uploaded_at=datetime.datetime.now(datetime.timezone.utc),
            uploaded_by=current_user.id,
            retention_until=_compute_retention_until(),
        )
        job = ExtractionJob(
            id=str(uuid.uuid4()),
            document_id=document_id,
            domain=domain,
            status="queued",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(document)
        session.add(job)

        try:
            session.commit()
        except IntegrityError:
            # Lost a concurrent race on content_hash's unique constraint —
            # someone else's identical upload committed first. Return theirs.
            session.rollback()
            winner_document = session.query(Document).filter_by(content_hash=content_hash).first()
            assert winner_document is not None
            winner_job = session.query(ExtractionJob).filter_by(document_id=winner_document.id).first()
            assert winner_job is not None
            return _to_response(winner_document, winner_job)

        # Only write to disk after the DB has confirmed this content_hash is
        # uniquely ours — avoids leaving an orphaned encrypted file if the
        # commit above had failed instead.
        storage.save_document(document_id, content)

        # Synchronous for now — no task queue exists yet (an explicitly
        # deferred architecture decision); PDF only, per this ticket's scope.
        # Concurrent uploads share FastAPI's default worker threadpool, so a
        # burst of slow extractions can starve other sync routes (including
        # GET /jobs/{id}/result polling) — a known, accepted limitation of
        # the synchronous-for-now design, not something this ticket fixes.
        duplicate_case: DuplicateReviewCase | None = None
        if extension == ".pdf":
            try:
                result = spec.extract(content)
                job.result_json = result.model_dump_json()
                # Scored candidates always land in PendingReview regardless
                # of reliability tier — nothing may be auto-approved (D14,
                # FR-12); the score itself is exposed via GET .../result for
                # the reviewer, not used to bypass review here.
                job.status = "pending_review"
                # Held alongside PendingReview, per the state machine in
                # solution-brief.md §7 — never blocks scoring/review, only
                # adds a case for the duplicate-resolution path (#7
                # Supplier, #9 Client, #11 Product all wire up
                # detect_duplicate the same way) to pick up.
                if spec.detect_duplicate is not None:
                    duplicate_case = spec.detect_duplicate(session, job, result)
                    if duplicate_case is not None:
                        session.add(duplicate_case)
            except Exception:  # document content is untrusted; must not crash the upload request
                logger.exception("Extraction failed for document %s (domain=%s)", document_id, domain)
                job.status = "extraction_failed"
                job.error_detail = "Extraction failed; see server logs for details"
        else:
            # No pipeline exists yet for this format — say so explicitly
            # rather than leaving the job at "queued" forever with no
            # signal to the caller that it will never advance.
            job.status = "unsupported_format"

        session.add(
            AuditLogEntry(
                id=str(uuid.uuid4()),
                document_id=document_id,
                action="submitted",
                actor_user_id=current_user.id,
                after_json=json.dumps({"job_status": job.status}),
                occurred_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        session.commit()

        return _to_response(document, job, duplicate_case.id if duplicate_case is not None else None)


class JobSummary(BaseModel):
    id: str
    document_id: str
    domain: str
    status: str
    created_at: datetime.datetime
    uploaded_by: str | None
    duplicate_review_case_id: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobSummary]
    has_more: bool = False


_JOB_LIST_LIMIT = 200


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    domain: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
) -> JobListResponse:
    """Backs the frontend's review queues — list jobs, optionally filtered
    to one domain and/or one status (e.g. domain=client&status=pending_review
    for "everything a Client reviewer needs to look at"). Not in the
    original API surface documented in solution-brief.md §16; added
    alongside the web frontend since a queue view has no way to discover
    job ids without one."""
    if domain is not None and domain not in DOMAIN_SPECS:
        raise HTTPException(
            status_code=400, detail=f"Unknown domain: {domain!r} (must be one of {sorted(DOMAIN_SPECS)})"
        )

    with get_session() as session:
        query = session.query(ExtractionJob, Document).join(Document, ExtractionJob.document_id == Document.id)
        if domain == "supplier":
            # job_domain() treats a null domain as "supplier" (pre-#8 rows)
            # — match that same fallback here so a "supplier" filter finds
            # any legacy rows too, not just ones with domain explicitly set.
            query = query.filter(or_(ExtractionJob.domain == "supplier", ExtractionJob.domain.is_(None)))
        elif domain is not None:
            query = query.filter(ExtractionJob.domain == domain)
        if status is not None:
            query = query.filter(ExtractionJob.status == status)
        # Fetch one extra row past the limit purely to detect truncation —
        # cheap way to tell the caller "there are more, narrow your filters"
        # instead of silently dropping the oldest pending jobs with no signal.
        rows = query.order_by(ExtractionJob.created_at.desc()).limit(_JOB_LIST_LIMIT + 1).all()
        has_more = len(rows) > _JOB_LIST_LIMIT
        rows = rows[:_JOB_LIST_LIMIT]

        job_ids = [job.id for job, _ in rows]
        pending_cases = (
            session.query(DuplicateReviewCase)
            .filter(DuplicateReviewCase.extraction_job_id.in_(job_ids), DuplicateReviewCase.status == "pending")
            .all()
            if job_ids
            else []
        )
        case_by_job = {case.extraction_job_id: case.id for case in pending_cases}

        jobs = [
            JobSummary(
                id=job.id,
                document_id=job.document_id,
                domain=job_domain(job),
                status=job.status,
                created_at=job.created_at,
                uploaded_by=document.uploaded_by,
                duplicate_review_case_id=case_by_job.get(job.id),
            )
            for job, document in rows
        ]
    return JobListResponse(jobs=jobs, has_more=has_more)


class JobResultResponse(BaseModel):
    id: str
    document_id: str
    domain: str
    status: str
    # A generic dict rather than a Union of the per-domain Pydantic models:
    # the concrete model is already selected server-side (via job.domain)
    # to build this, so the JSON shape is exactly as precise either way —
    # this just avoids ambiguous union-type serialization across three
    # structurally-overlapping candidate schemas. Same wire shape as before
    # for existing Supplier consumers (nested field objects, unchanged).
    result: dict[str, object] | None
    error_detail: str | None
    scoring: ScoringResult | None
    duplicate_review_case_id: str | None = None
    uploaded_by: str | None = None


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, current_user: User = Depends(get_current_user)) -> JobResultResponse:
    with get_session() as session:
        job = session.query(ExtractionJob).filter_by(id=job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        domain = job_domain(job)
        spec = DOMAIN_SPECS[domain]
        result = spec.result_model.model_validate_json(job.result_json) if job.result_json else None
        duplicate_case = (
            session.query(DuplicateReviewCase).filter_by(extraction_job_id=job.id, status="pending").first()
        )
        document = session.query(Document).filter_by(id=job.document_id).first()
        return JobResultResponse(
            id=job.id,
            document_id=job.document_id,
            domain=domain,
            status=job.status,
            result=result.model_dump(mode="json") if result is not None else None,
            error_detail=job.error_detail,
            scoring=spec.score(result) if result is not None else None,
            duplicate_review_case_id=duplicate_case.id if duplicate_case is not None else None,
            uploaded_by=document.uploaded_by if document is not None else None,
        )
