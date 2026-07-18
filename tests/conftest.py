import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Isolate every test from the real repo-root data/ dir and from
    whatever MDM_* env vars happen to be set in the ambient environment."""
    monkeypatch.setenv("MDM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MDM_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MDM_DATABASE_URL", raising=False)
    monkeypatch.delenv("MDM_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("MDM_HOST", raising=False)
    monkeypatch.delenv("MDM_PORT", raising=False)
