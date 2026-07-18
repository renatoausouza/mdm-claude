import datetime
import logging
import uuid

from mdm import storage
from mdm.db import AuditLogEntry, Document, ensure_aware_utc, get_session

logger = logging.getLogger(__name__)


def run_purge_once() -> int:
    """Delete the stored file for every document whose retention window has
    passed. The Document row, its ExtractionJob, and its extraction result
    are left intact — only the raw source file is removed. Returns the
    number of documents purged."""
    now = datetime.datetime.now(datetime.timezone.utc)
    purged_count = 0

    with get_session() as session:
        candidates = (
            session.query(Document)
            .filter(Document.purged_at.is_(None), Document.retention_until.isnot(None))
            .all()
        )
        for document in candidates:
            # The query filter guarantees retention_until is non-null here.
            retention_until = document.retention_until
            assert retention_until is not None
            retention_until = ensure_aware_utc(retention_until)
            if retention_until > now:
                continue

            document.purged_at = now
            session.add(
                AuditLogEntry(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    action="purged",
                    occurred_at=now,
                    detail=f"Retention window ({retention_until.isoformat()}) elapsed",
                )
            )
            # Commit the DB state *before* touching the filesystem: a
            # request racing this job (e.g. a re-upload's dedup check in
            # documents.py) must never observe a file that's already gone
            # from disk while purged_at is still uncommitted, which would
            # misreport a legitimate purge as corruption.
            session.commit()
            storage.delete_document(document.id)
            purged_count += 1

    logger.info("Retention purge: %d document(s) purged", purged_count)
    return purged_count


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_purge_once()


if __name__ == "__main__":
    main()
