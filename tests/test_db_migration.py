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
