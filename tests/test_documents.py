import os

from fastapi.testclient import TestClient

from mdm import storage
from mdm.main import app

# These tests exercise the generic upload/storage/idempotency behavior from
# ticket #2, deliberately using a non-PDF extension (.txt) so they stay
# independent of ticket #4's PDF extraction pipeline — fake/invalid PDF
# bytes would now trigger a real (and correctly failing) extraction
# attempt, which is not what these tests are about.


def test_upload_supported_document_returns_job_info() -> None:
    client = TestClient(app)
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert "document_id" in body
    assert "content_hash" in body
    assert body["status"] == "unsupported_format"  # extraction only exists for .pdf so far
    assert "retention_until" in body


def test_upload_unsupported_extension_is_rejected() -> None:
    client = TestClient(app)
    response = client.post(
        "/documents",
        files={"file": ("malware.exe", b"not a real document", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_reuploading_identical_content_returns_same_job() -> None:
    client = TestClient(app)
    content = b"identical content"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")})
    second = client.post("/documents", files={"file": ("b.txt", content, "text/plain")})

    assert first.json()["id"] == second.json()["id"]
    assert first.json()["document_id"] == second.json()["document_id"]


def test_different_documents_get_different_jobs() -> None:
    client = TestClient(app)

    first = client.post("/documents", files={"file": ("a.txt", b"content A", "text/plain")})
    second = client.post("/documents", files={"file": ("b.txt", b"content B", "text/plain")})

    assert first.json()["id"] != second.json()["id"]


def test_reupload_fails_loudly_if_stored_file_is_missing(tmp_path) -> None:
    client = TestClient(app)
    content = b"content whose file will vanish"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")})
    document_id = first.json()["document_id"]

    # Simulate the stored file being lost (corruption, out-of-band deletion)
    # while the DB row survives.
    os.remove(storage._document_path(document_id))

    second = client.post("/documents", files={"file": ("b.txt", content, "text/plain")})
    assert second.status_code == 500
