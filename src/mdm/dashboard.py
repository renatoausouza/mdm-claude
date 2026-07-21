"""#18: data quality dashboard — registered-data health (completeness/
compliance recomputed live for current master records) plus pipeline
health (job-status backlog, extraction failure rate, open duplicate-case
count). Computed fresh on every request — no caching layer, no scheduled
job, matching how every other read path in this app already works."""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mdm.auth import get_current_user
from mdm.db import DuplicateReviewCase, ExtractionJob, MasterRecord, User, get_session
from mdm.domains import DOMAIN_SPECS, job_domain
from mdm.review import _require_approver_or_admin
from mdm.scoring import AlreadyApprovedField, score_candidate

router = APIRouter()


class DomainDataQuality(BaseModel):
    domain: str
    record_count: int
    completeness: float
    compliance: float


class DomainPipelineHealth(BaseModel):
    domain: str
    status_counts: dict[str, int]


class DashboardResponse(BaseModel):
    data_quality: list[DomainDataQuality]
    pipeline_health: list[DomainPipelineHealth]
    # Global, not per-domain: extraction is the same PDF/LLM pipeline
    # regardless of which domain a job belongs to, so a single rate is the
    # more meaningful number (per-domain failure counts are still visible
    # in each domain's status_counts["extraction_failed"] above).
    extraction_failure_rate: float
    # Also global — DuplicateReviewCase has no domain column of its own
    # (only reachable via a join through extraction_job_id or
    # matched_master_record_id), and the ticket doesn't ask for a
    # per-domain split here the way it explicitly does for status backlog.
    open_duplicate_case_count: int


def _domain_data_quality(session: Session, domain: str) -> DomainDataQuality:
    spec = DOMAIN_SPECS[domain].scoring_spec
    records = session.query(MasterRecord).filter_by(domain=domain, is_current=True).all()

    if not records:
        return DomainDataQuality(domain=domain, record_count=0, completeness=0.0, compliance=0.0)

    completeness_sum = 0.0
    compliance_sum = 0.0
    for record in records:
        raw_fields: dict[str, str] = json.loads(record.fields_json)
        scorable = {name: AlreadyApprovedField(value=value) for name, value in raw_fields.items()}
        # confidence_threshold is irrelevant here — only .completeness/
        # .compliance are read; reliability/low_confidence_fields (the only
        # things that depend on it) are deliberately not surfaced for
        # already-registered data (candidate-time-only concepts).
        result = score_candidate(scorable, spec, confidence_threshold=1.0)
        completeness_sum += result.completeness
        compliance_sum += result.compliance

    return DomainDataQuality(
        domain=domain,
        record_count=len(records),
        completeness=completeness_sum / len(records),
        compliance=compliance_sum / len(records),
    )


def _pipeline_health_by_domain(session: Session) -> dict[str, DomainPipelineHealth]:
    """One pass over every ExtractionJob, grouped by domain — not one query
    per domain, since job_domain() already needs every row loaded anyway
    (a null domain column means "supplier", not filterable in SQL)."""
    status_counts_by_domain: dict[str, dict[str, int]] = {domain: {} for domain in DOMAIN_SPECS}
    for job in session.query(ExtractionJob).all():
        domain = job_domain(job)
        counts = status_counts_by_domain[domain]
        counts[job.status] = counts.get(job.status, 0) + 1
    return {
        domain: DomainPipelineHealth(domain=domain, status_counts=counts)
        for domain, counts in status_counts_by_domain.items()
    }


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(current_user: User = Depends(get_current_user)) -> DashboardResponse:
    _require_approver_or_admin(current_user)

    with get_session() as session:
        data_quality = [_domain_data_quality(session, domain) for domain in DOMAIN_SPECS]

        pipeline_by_domain = _pipeline_health_by_domain(session)
        pipeline_health = list(pipeline_by_domain.values())

        total_jobs = sum(sum(p.status_counts.values()) for p in pipeline_health)
        failed_jobs = sum(p.status_counts.get("extraction_failed", 0) for p in pipeline_health)
        extraction_failure_rate = failed_jobs / total_jobs if total_jobs else 0.0

        open_duplicate_case_count = session.query(DuplicateReviewCase).filter_by(status="pending").count()

    return DashboardResponse(
        data_quality=data_quality,
        pipeline_health=pipeline_health,
        extraction_failure_rate=extraction_failure_rate,
        open_duplicate_case_count=open_duplicate_case_count,
    )
