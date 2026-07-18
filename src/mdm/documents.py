import datetime
import hashlib
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from mdm import config, storage
from mdm.auth import get_current_user
from mdm.db import AuditLogEntry, Document, ExtractionJob, User, get_session
from mdm.scoring import ScoringResult
from mdm.supplier_extraction import SupplierCandidateResult, run_supplier_extraction, score_supplier

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".msg", ".json", ".xml", ".txt", ".log", ".png", ".jpg", ".jpeg"}


class JobResponse(BaseModel):
    id: str
    document_id: str
    content_hash: str
    status: str
    retention_until: datetime.datetime | None


def _compute_retention_until() -> datetime.datetime | None:
    retention_days = config.get_retention_days()
    if retention_days is None:
        return None
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=retention_days)


def _to_response(document: Document, job: ExtractionJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        document_id=document.id,
        content_hash=document.content_hash,
        status=job.status,
        retention_until=document.retention_until,
    )


@router.post("/documents", response_model=JobResponse, status_code=201)
def upload_document(file: UploadFile = File(...), current_user: User = Depends(get_current_user)) -> JobResponse:
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
                    return _to_response(existing_document, job)
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
            return _to_response(existing_document, job)

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
        if extension == ".pdf":
            try:
                result = run_supplier_extraction(content)
                job.result_json = result.model_dump_json()
                # Scored candidates always land in PendingReview regardless
                # of reliability tier — nothing may be auto-approved (D14,
                # FR-12); the score itself is exposed via GET .../result for
                # the reviewer, not used to bypass review here.
                job.status = "pending_review"
            except Exception:  # document content is untrusted; must not crash the upload request
                logger.exception("Supplier extraction failed for document %s", document_id)
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

        return _to_response(document, job)


class JobResultResponse(BaseModel):
    id: str
    document_id: str
    status: str
    result: SupplierCandidateResult | None
    error_detail: str | None
    scoring: ScoringResult | None


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, current_user: User = Depends(get_current_user)) -> JobResultResponse:
    with get_session() as session:
        job = session.query(ExtractionJob).filter_by(id=job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        result = SupplierCandidateResult.model_validate_json(job.result_json) if job.result_json else None
        return JobResultResponse(
            id=job.id,
            document_id=job.document_id,
            status=job.status,
            result=result,
            error_detail=job.error_detail,
            scoring=score_supplier(result) if result is not None else None,
        )
