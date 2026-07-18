import datetime
import os
from functools import lru_cache

from sqlalchemy import DateTime, Engine, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mdm import config


class Base(DeclarativeBase):
    pass


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
    status: Mapped[str] = mapped_column(String, default="queued")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


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
