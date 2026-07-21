import datetime
import os
from functools import lru_cache

from sqlalchemy import Boolean, DateTime, Engine, ForeignKey, Index, Integer, String, create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.schema import CreateColumn

from mdm import config


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    # The last TOTP code accepted for this user — rejecting a repeat of the
    # same code prevents replaying an observed/captured code within its
    # validity window (pyotp's verify() alone doesn't track consumption).
    last_used_totp_code: Mapped[str | None] = mapped_column(String, nullable=True)


class BootstrapMarker(Base):
    """A singleton row (fixed id) whose unique primary key makes 'am I the
    first user' an atomic DB-enforced check instead of a racy count()==0
    read-then-act — see create_user in auth.py."""

    __tablename__ = "bootstrap_marker"

    id: Mapped[str] = mapped_column(String, primary_key=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    # "full": normal authenticated session. "mfa_enrollment": issued after a
    # correct password for an approver who hasn't finished MFA enrollment
    # yet — usable only to reach the enrollment endpoints, resolving the
    # bootstrap problem where an approver can't log in without MFA, but
    # can't enroll in MFA without being logged in.
    scope: Mapped[str] = mapped_column(String, default="full")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    # Nullable only for migration-safety on pre-#6 rows — every upload since
    # #6 requires authentication, so this is always set going forward. Used
    # for the submitter != approver segregation-of-duties check (D6).
    uploaded_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    retention_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the retention-purge job (#13) has deleted the stored file.
    # The row itself (and its ExtractionJob/result) is kept — only the raw
    # source file is removed. Null means "still on disk (or never subject
    # to a retention window)".
    purged_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Not unique: one Document can have up to one ExtractionJob per domain
    # (supplier/client/product) since a single upload now extracts all three
    # rather than the one the caller picked (see _ensure_document_id_not_unique
    # below for the migration off the old unique index).
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), index=True)
    # queued -> pending_review | extraction_failed | unsupported_format
    # pending_review -> approved | rejected | needs_info (#6)
    # needs_info -> approved | rejected (a reviewer can decide once
    # clarified, without requiring a brand-new upload)
    status: Mapped[str] = mapped_column(String, default="queued")
    # "supplier" | "client" | "product" (#8/#10) — nullable only for
    # migration-safety on pre-#8 rows; every job created going forward sets
    # it explicitly (documents.py defaults new uploads to "supplier" for
    # backward compatibility). review.py/duplicates.py treat a null domain
    # as "supplier" (domains.job_domain()) for exactly those legacy rows.
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)


class MasterRecord(Base):
    """A registered record (Supplier | Client | Product, per `domain`).
    Versioned: an approval that updates an existing record inserts a new row
    rather than mutating one, so prior versions stay queryable for lineage
    (§6/§15 of the solution brief). `record_key` is stable across a given
    record's versions; `id` is unique per version row."""

    __tablename__ = "master_records"
    __table_args__ = (
        # At most one is_current=True row per (domain, record_key) — the
        # actual guarantee behind "never two current records for the same
        # supplier" (#7). Application-level pre-checks (review.py,
        # duplicates.py) exist to give a clean 409 in the common case, but
        # this index is what makes the invariant hold even if two writers
        # race past those checks at the same instant.
        Index(
            "ix_master_records_one_current_per_key",
            "domain",
            "record_key",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str] = mapped_column(String, index=True)  # "supplier" | "client" | "product"
    record_key: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    fields_json: Mapped[str] = mapped_column(String)
    source_job_id: Mapped[str] = mapped_column(String, ForeignKey("extraction_jobs.id"))
    first_registered_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class DuplicateReviewCase(Base):
    """A candidate whose match key (normalized CNPJ/CPF/SKU) matched an
    already-registered current MasterRecord (#7, D4/D2/FR-09/FR-10). Never
    auto-merged — held for a human to accept/reject/partially-accept,
    side-by-side against the existing record. One case per job: a job with
    no matching record never gets one."""

    __tablename__ = "duplicate_review_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    extraction_job_id: Mapped[str] = mapped_column(String, ForeignKey("extraction_jobs.id"), unique=True, index=True)
    matched_master_record_id: Mapped[str] = mapped_column(String, ForeignKey("master_records.id"))
    match_key: Mapped[str] = mapped_column(String, index=True)
    # "pending" | "accepted" | "rejected" | "partially_accepted"
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_fields_json: Mapped[str | None] = mapped_column(String, nullable=True)


class MasterRecordEditRequest(Base):
    """#20: a human-proposed correction to a current MasterRecord's
    non-key fields, for domains where REQUIRES_SEGREGATION is True
    (Supplier) — the second-approver-reviewed counterpart to #19's
    immediate direct-edit path for Client/Product. Deliberately not a
    DuplicateReviewCase: that table means "the system auto-detected a
    possible duplicate," and overloading it to also mean "a human proposed
    a manual correction" would make it (and the audit trail referencing
    it) mean two different things — see #17/#20's own reasoning."""

    __tablename__ = "master_record_edit_requests"
    __table_args__ = (
        # At most one pending request per record at a time — same
        # partial-unique-index pattern as MasterRecord's own
        # one-current-per-key guarantee, for the same reason: an
        # application-level pre-check gives a clean 409 in the common
        # case, but this is what makes the invariant hold even if two
        # approvers race to submit a proposal for the same record at once.
        Index(
            "ix_master_record_edit_requests_one_pending_per_record",
            "master_record_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    master_record_id: Mapped[str] = mapped_column(String, ForeignKey("master_records.id"), index=True)
    # Only the fields being changed — comparisons against the current
    # record's other (unchanged) fields are computed live at read time,
    # not snapshotted, so the reviewer always sees a true current-vs-
    # proposed diff even if this request sat pending for a while.
    proposed_fields_json: Mapped[str] = mapped_column(String)
    submitted_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    # "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalEvent(Base):
    """One row per review decision (approve/reject/needs_info) — the
    solution brief's §6/§11 record of who submitted, who decided, and what
    was decided. Append-only alongside AuditLogEntry; this table is the
    structured decision record, AuditLogEntry is the generic action log."""

    __tablename__ = "approval_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    extraction_job_id: Mapped[str] = mapped_column(String, ForeignKey("extraction_jobs.id"), index=True)
    submitted_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)  # "approved" | "rejected" | "needs_info"
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    master_record_id: Mapped[str | None] = mapped_column(String, ForeignKey("master_records.id"), nullable=True)


class AuditLogEntry(Base):
    """Append-only record of actions taken on a document/job — retention
    purges (#13) and submit/approve/reject/needs_info decisions (#6, FR-19).
    `actor_user_id` is null for system-initiated actions (the purge job);
    `before_json`/`after_json` capture the FR-19-required before/after
    snapshot for human-initiated actions."""

    __tablename__ = "audit_log_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), index=True)
    action: Mapped[str] = mapped_column(String)
    actor_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    before_json: Mapped[str | None] = mapped_column(String, nullable=True)
    after_json: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(String, nullable=True)


def _add_missing_columns(engine: Engine) -> None:
    """create_all() only creates tables that don't exist yet — it never adds
    a column to a table that's already there. This project has no migration
    tool, so a nullable column added to an existing model (as #13 did for
    Document.purged_at) would otherwise break every deployment against a
    pre-existing database. Handles nullable-column additions only; a
    renamed/dropped column or a new NOT NULL column needs a real migration.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # a brand-new table — create_all() already handled it
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            if not column.nullable:
                raise RuntimeError(
                    f"{table.name}.{column.name} is a new NOT NULL column on an "
                    "existing table — needs a real migration, not this helper."
                )
            column_ddl = CreateColumn(column).compile(engine)
            # Own transaction per column (not one shared across the whole
            # function): the app server and the hourly purge job are
            # separate processes that both call get_engine() on startup, so
            # two of them can see the same column missing and both attempt
            # to add it. Swallowing the loser's "duplicate column" error
            # here — after its own transaction has cleanly rolled back —
            # makes that race harmless instead of crashing the losing
            # process.
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column_ddl}"))
            except OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise


def _ensure_extraction_job_document_id_not_unique(engine: Engine) -> None:
    """Pre-multi-domain-upload databases have a UNIQUE index on
    extraction_jobs.document_id (the old one-Document-one-ExtractionJob
    invariant). A single upload now creates up to one ExtractionJob per
    domain, so that uniqueness must go — but SQLite can't just drop a
    column's UNIQUE constraint in place, so this drops the old unique index
    and recreates a plain one, mirroring _add_missing_columns' approach to
    evolving an existing SQLite schema without a real migration tool.
    """
    inspector = inspect(engine)
    if "extraction_jobs" not in inspector.get_table_names():
        return  # a brand-new table — create_all() already made it non-unique
    for index in inspector.get_indexes("extraction_jobs"):
        if index["column_names"] == ["document_id"] and index["unique"]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP INDEX {index["name"]}'))
                    conn.execute(
                        text(
                            f'CREATE INDEX IF NOT EXISTS {index["name"]} '
                            "ON extraction_jobs (document_id)"
                        )
                    )
            except OperationalError:
                # Lost a race with another process (app server / purge job)
                # performing the same migration — harmless either way.
                pass
            break


@lru_cache
def get_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        # The retention-purge job (#13) is a second process now writing to
        # the same SQLite file as the app server. SQLite's default ~5s
        # busy timeout can turn an ordinary lock wait into an unhandled
        # "database is locked" error; 30s gives concurrent writers room to
        # queue instead of failing.
        connect_args = {"timeout": 30}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    _ensure_extraction_job_document_id_not_unique(engine)
    return engine


def get_session() -> Session:
    return Session(get_engine(config.get_database_url()))


def ensure_aware_utc(value: datetime.datetime) -> datetime.datetime:
    """SQLite has no true timezone-aware storage: DateTime(timezone=True)
    columns can still round-trip as naive datetimes depending on the
    driver. Normalize before comparing against a fresh timezone-aware
    "now" to avoid 'can't compare offset-naive and offset-aware datetimes'.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value
