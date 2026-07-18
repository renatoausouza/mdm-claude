"""Per-domain registry the review/approval/duplicate-detection machinery
(review.py, duplicates.py, documents.py) uses to treat Supplier (#4/#6/#7),
Client (#8), and Product (#10) generically instead of being hardcoded to
Supplier. Lives below review.py/duplicates.py in the dependency graph (it
only imports db.py, scoring.py, and the leaf per-domain extraction modules)
so both of those can depend on it without a cycle.
"""

import datetime
import uuid
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from mdm.client_extraction import ClientCandidateResult, run_client_extraction, score_client
from mdm.db import DuplicateReviewCase, ExtractionJob, MasterRecord
from mdm.extraction_schema import FieldValue
from mdm.product_extraction import ProductCandidateResult, run_product_extraction, score_product
from mdm.scoring import ScoringResult
from mdm.supplier_extraction import SupplierCandidateResult, run_supplier_extraction, score_supplier


def normalized_field(field: FieldValue) -> str:
    # Single source of truth for "which representation of a field goes into
    # a MasterRecord/match key" (record_key, DuplicateReviewCase.match_key,
    # and the fields_json snapshot) — computed once here so the various
    # call sites can never silently diverge from each other.
    return field.normalized_value or field.value


def fields_dict(result: BaseModel, master_fields: tuple[str, ...]) -> dict[str, str]:
    return {
        name: normalized_field(field)
        for name in master_fields
        if (field := getattr(result, name, None)) is not None
    }


def find_current_master_record(session: Session, domain: str, record_key: str) -> MasterRecord | None:
    return session.query(MasterRecord).filter_by(domain=domain, record_key=record_key, is_current=True).first()


def detect_supplier_duplicate(
    session: Session, job: ExtractionJob, result: SupplierCandidateResult
) -> DuplicateReviewCase | None:
    """Exact-match CNPJ dedup against already-registered current Supplier
    records (FR-09, #7). Never merges anything itself — only flags for a
    human (D4/D2); the caller is responsible for adding the returned case to
    the session (it isn't committed here).

    The only entry in DOMAIN_SPECS with a detect_duplicate today — #9
    (client) and #11 (product) haven't been implemented yet, so those specs
    below have detect_duplicate=None and get no last-resort approval-time
    check either (see review.py's approve_job)."""
    if result.cnpj is None:
        return None
    match_key = normalized_field(result.cnpj)
    matched = find_current_master_record(session, "supplier", match_key)
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


@dataclass(frozen=True)
class DomainRegistration:
    result_model: type[BaseModel]
    master_fields: tuple[str, ...]
    # Which master field seeds record_key / duplicate matching; None means
    # no natural key exists for this domain yet (falls back to a random key
    # on every approval, same as a missing key_field value does today).
    key_field: str | None
    requires_segregation: bool  # D6/FR-13 — submitter != approver
    score: Callable[[BaseModel], ScoringResult]
    detect_duplicate: Callable[[Session, ExtractionJob, BaseModel], DuplicateReviewCase | None] | None
    # The domain's PDF extraction entry point (#4 Supplier, #8 Client, #10
    # Product). Lives on the spec itself — not a second dict documents.py
    # has to keep in sync by hand — so a domain that's registered here but
    # missing an extractor can't happen; adding a domain to DOMAIN_SPECS is
    # the only place a new one needs to be wired in.
    extract: Callable[[bytes], BaseModel]


DOMAIN_SPECS: dict[str, DomainRegistration] = {
    "supplier": DomainRegistration(
        result_model=SupplierCandidateResult,
        master_fields=("cnpj", "legal_name", "email", "telephone", "address"),
        key_field="cnpj",
        requires_segregation=True,
        score=score_supplier,  # type: ignore[arg-type]
        detect_duplicate=detect_supplier_duplicate,  # type: ignore[arg-type]
        extract=run_supplier_extraction,
    ),
    "client": DomainRegistration(
        result_model=ClientCandidateResult,
        master_fields=("tax_id", "name", "email", "telephone", "address"),
        key_field="tax_id",
        # Client approvals use a single approver — self-approval allowed,
        # unlike Supplier (#8's ticket text, FR-13's Client carve-out).
        requires_segregation=False,
        score=score_client,  # type: ignore[arg-type]
        detect_duplicate=None,  # #9, not yet implemented
        extract=run_client_extraction,
    ),
    "product": DomainRegistration(
        result_model=ProductCandidateResult,
        master_fields=("name", "sku", "ncm", "description"),  # price/quantity/discount excluded (D10)
        key_field="sku",
        requires_segregation=False,
        score=score_product,  # type: ignore[arg-type]
        detect_duplicate=None,  # #11, not yet implemented
        extract=run_product_extraction,
    ),
}


def job_domain(job: ExtractionJob) -> str:
    return job.domain or "supplier"
