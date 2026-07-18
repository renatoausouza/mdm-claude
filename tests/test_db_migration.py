import threading

from sqlalchemy import create_engine, inspect

from mdm.db import Base, _add_missing_columns


def test_concurrent_missing_column_add_does_not_crash(tmp_path) -> None:
    """Regression test for the app server and the retention-purge job (two
    separate processes) both calling get_engine() -> _add_missing_columns()
    against the same pre-existing database at once."""
    db_path = tmp_path / "race.db"
    engine = create_engine(f"sqlite:///{db_path}")

    # Build a "pre-#13" documents table (no purged_at column yet) to
    # reproduce the state of a database that predates this migration.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE documents RENAME TO documents_old")
        conn.exec_driver_sql(
            "CREATE TABLE documents (id VARCHAR PRIMARY KEY, content_hash VARCHAR UNIQUE, "
            "content_type VARCHAR, uploaded_at DATETIME, retention_until DATETIME)"
        )
        conn.exec_driver_sql("DROP TABLE documents_old")

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def add_columns() -> None:
        barrier.wait()
        try:
            _add_missing_columns(engine)
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=add_columns) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    columns = {col["name"] for col in inspect(engine).get_columns("documents")}
    assert "purged_at" in columns


def test_adding_a_nullable_column_to_an_existing_table_preserves_existing_rows(tmp_path) -> None:
    # Simulate a database created before ticket #13, whose "documents" table
    # predates the purged_at column and has a real row in it already — the
    # exact situation a live deploy of this ticket hits. Builds the
    # pre-migration table the same way as the concurrency test above.
    from sqlalchemy.orm import Session

    from mdm.db import Document, get_engine

    db_path = tmp_path / "pre_existing.db"
    setup_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(setup_engine)
    with setup_engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE documents RENAME TO documents_old")
        conn.exec_driver_sql(
            "CREATE TABLE documents (id VARCHAR PRIMARY KEY, content_hash VARCHAR UNIQUE, "
            "content_type VARCHAR, uploaded_at DATETIME, retention_until DATETIME)"
        )
        conn.exec_driver_sql("DROP TABLE documents_old")
        conn.exec_driver_sql(
            "INSERT INTO documents VALUES ('doc-1', 'hash-1', 'text/plain', "
            "'2026-01-01T00:00:00+00:00', NULL)"
        )
    setup_engine.dispose()

    engine = get_engine(f"sqlite:///{db_path}")

    with Session(engine) as session:
        document = session.get(Document, "doc-1")
        assert document is not None
        assert document.content_hash == "hash-1"  # pre-existing row survived the migration
        assert document.purged_at is None  # new column, backfilled as NULL
