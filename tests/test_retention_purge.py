import datetime
import uuid

from mdm import storage
from mdm.db import AuditLogEntry, Document, ExtractionJob, get_session
from mdm.retention_purge import run_purge_once


def _make_document(retention_until: datetime.datetime | None, purged_at: datetime.datetime | None = None) -> str:
    document_id = str(uuid.uuid4())
    storage.save_document(document_id, b"some content")
    with get_session() as session:
        session.add(
            Document(
                id=document_id,
                content_hash=document_id,  # only needs to be unique for these tests
                content_type="text/plain",
                uploaded_at=datetime.datetime.now(datetime.timezone.utc),
                retention_until=retention_until,
                purged_at=purged_at,
            )
        )
        session.add(
            ExtractionJob(
                id=str(uuid.uuid4()),
                document_id=document_id,
                status="extracted",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                result_json='{"cnpj": null}',
            )
        )
        session.commit()
    return document_id


def _past(days: int = 1) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)


def _future(days: int = 1) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)


def test_purges_document_past_retention_window() -> None:
    document_id = _make_document(retention_until=_past())

    purged_count = run_purge_once()

    assert purged_count == 1
    assert not storage.document_exists(document_id)
    with get_session() as session:
        document = session.get(Document, document_id)
        assert document is not None
        assert document.purged_at is not None


def test_document_within_retention_window_is_not_purged() -> None:
    document_id = _make_document(retention_until=_future())

    purged_count = run_purge_once()

    assert purged_count == 0
    assert storage.document_exists(document_id)


def test_document_with_no_retention_until_is_never_purged() -> None:
    document_id = _make_document(retention_until=None)

    purged_count = run_purge_once()

    assert purged_count == 0
    assert storage.document_exists(document_id)


def test_already_purged_document_is_skipped() -> None:
    document_id = _make_document(retention_until=_past(), purged_at=_past())

    purged_count = run_purge_once()

    assert purged_count == 0


def test_purge_does_not_delete_extraction_job_or_result() -> None:
    document_id = _make_document(retention_until=_past())

    run_purge_once()

    with get_session() as session:
        job = session.query(ExtractionJob).filter_by(document_id=document_id).first()
        assert job is not None
        assert job.result_json == '{"cnpj": null}'


def test_purge_writes_an_audit_log_entry() -> None:
    document_id = _make_document(retention_until=_past())

    run_purge_once()

    with get_session() as session:
        entry = session.query(AuditLogEntry).filter_by(document_id=document_id).first()
        assert entry is not None
        assert entry.action == "purged"


def test_purge_audit_log_detail_records_a_timezone_aware_timestamp() -> None:
    # SQLite round-trips DateTime(timezone=True) values as naive; the audit
    # detail must still record an unambiguous (offset-bearing) timestamp,
    # not a bare one a reader could mistake for local time.
    document_id = _make_document(retention_until=_past())

    run_purge_once()

    with get_session() as session:
        entry = session.query(AuditLogEntry).filter_by(document_id=document_id).first()
        assert entry is not None
        assert entry.detail is not None
        assert "+00:00" in entry.detail
