import datetime
import os
from functools import lru_cache

from sqlalchemy import Boolean, DateTime, Engine, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

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
    retention_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), unique=True, index=True)
    # queued -> extracted | extraction_failed | unsupported_format
    # (no "scored"/"pending_review" yet — that's the scoring engine, #5)
    status: Mapped[str] = mapped_column(String, default="queued")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)


@lru_cache
def get_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
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
