import datetime
import os

from fastapi.testclient import TestClient

from mdm import storage
from mdm.db import AuditLogEntry, Document, get_session
from mdm.main import app

# These tests exercise the generic upload/storage/idempotency behavior from
# ticket #2, deliberately using a non-PDF extension (.txt) so they stay
# independent of ticket #4's PDF extraction pipeline — fake/invalid PDF
# bytes would now trigger a real (and correctly failing) extraction
# attempt, which is not what these tests are about.


def _bootstrap_admin_token(client: TestClient) -> str:
    # Idempotent within a test: the first call creates the bootstrap admin
    # (first user in a fresh DB always becomes admin, no auth required);
    # later calls in the same test just log the same account back in, since
    # creating any *other* user now requires an admin-authenticated caller.
    client.post("/users", json={"username": "_bootstrap_admin", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "_bootstrap_admin", "password": "admin-password"})
    token: str = login.json()["token"]
    return token


def _uploader_headers(client: TestClient, username: str = "uploader") -> dict[str, str]:
    # Upload requires authentication since #6 (submitter identity is needed
    # for the segregation-of-duties check). "Submitter" isn't a privileged
    # role — any authenticated user may upload.
    admin_token = _bootstrap_admin_token(client)
    client.post(
        "/users",
        json={"username": username, "password": "upload-password", "role": "submitter"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    login = client.post("/auth/login", json={"username": username, "password": "upload-password"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_supported_document_returns_job_info() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert "document_id" in body
    assert "content_hash" in body
    assert body["status"] == "unsupported_format"  # extraction only exists for .pdf so far
    assert "retention_until" in body


def test_upload_without_authentication_is_rejected() -> None:
    client = TestClient(app)
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
    )
    assert response.status_code == 401


def test_upload_unsupported_extension_is_rejected() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    response = client.post(
        "/documents",
        files={"file": ("malware.exe", b"not a real document", "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 400


def test_reuploading_identical_content_returns_same_job() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    content = b"identical content"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")}, headers=headers)
    second = client.post("/documents", files={"file": ("b.txt", content, "text/plain")}, headers=headers)

    assert first.json()["id"] == second.json()["id"]
    assert first.json()["document_id"] == second.json()["document_id"]


def test_different_documents_get_different_jobs() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)

    first = client.post("/documents", files={"file": ("a.txt", b"content A", "text/plain")}, headers=headers)
    second = client.post("/documents", files={"file": ("b.txt", b"content B", "text/plain")}, headers=headers)

    assert first.json()["id"] != second.json()["id"]


def test_reupload_fails_loudly_if_stored_file_is_missing(tmp_path) -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    content = b"content whose file will vanish"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")}, headers=headers)
    document_id = first.json()["document_id"]

    # Simulate the stored file being lost (corruption, out-of-band deletion)
    # while the DB row survives.
    os.remove(storage._document_path(document_id))

    second = client.post("/documents", files={"file": ("b.txt", content, "text/plain")}, headers=headers)
    assert second.status_code == 500


def test_reupload_after_purge_restores_the_file_instead_of_500ing() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    content = b"content that will be purged and restored"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")}, headers=headers)
    document_id = first.json()["document_id"]

    # Simulate the retention-purge job having already run for this document.
    with get_session() as session:
        document = session.get(Document, document_id)
        assert document is not None
        document.purged_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
    storage.delete_document(document_id)

    second = client.post("/documents", files={"file": ("b.txt", content, "text/plain")}, headers=headers)

    assert second.status_code == 201
    assert second.json()["document_id"] == document_id
    assert storage.document_exists(document_id)


def test_reupload_after_purge_writes_a_restored_audit_log_entry() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    content = b"content that will be purged and restored, audited too"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")}, headers=headers)
    document_id = first.json()["document_id"]

    with get_session() as session:
        document = session.get(Document, document_id)
        assert document is not None
        document.purged_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
    storage.delete_document(document_id)

    client.post("/documents", files={"file": ("b.txt", content, "text/plain")}, headers=headers)

    with get_session() as session:
        entry = session.query(AuditLogEntry).filter_by(document_id=document_id, action="restored").first()
        assert entry is not None


def test_reupload_of_existing_content_by_a_different_user_is_still_audited() -> None:
    client = TestClient(app)
    original_headers = _uploader_headers(client, "original-uploader")
    other_headers = _uploader_headers(client, "other-uploader")
    content = b"content uploaded once, then re-uploaded by someone else"

    first = client.post("/documents", files={"file": ("a.txt", content, "text/plain")}, headers=original_headers)
    document_id = first.json()["document_id"]

    client.post("/documents", files={"file": ("b.txt", content, "text/plain")}, headers=other_headers)

    with get_session() as session:
        document = session.get(Document, document_id)
        assert document is not None
        # The original submitter stays of record — segregation-of-duties
        # keys off this — even though a different user also interacted.
        assert document.uploaded_by is not None

        entries = session.query(AuditLogEntry).filter_by(document_id=document_id, action="submitted").all()
        actors = {entry.actor_user_id for entry in entries}
        assert len(actors) == 2


def test_upload_writes_a_submitted_audit_log_entry() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)

    response = client.post(
        "/documents", files={"file": ("notes.txt", b"some content", "text/plain")}, headers=headers
    )
    document_id = response.json()["document_id"]

    with get_session() as session:
        entry = session.query(AuditLogEntry).filter_by(document_id=document_id, action="submitted").first()
        assert entry is not None
        assert entry.actor_user_id is not None


def test_reuploading_identical_content_under_a_different_domain_reveals_that_domain_too() -> None:
    # A single upload now extracts every domain (supplier/client/product) at
    # once — re-requesting a different `domain` for identical bytes no
    # longer 409s (that domain's job already exists from the first upload;
    # `domain` only selects which job's fields are echoed at the top level).
    client = TestClient(app)
    headers = _uploader_headers(client)
    content = b"identical content, two different domain requests"

    first = client.post(
        "/documents",
        files={"file": ("a.txt", content, "text/plain")},
        data={"domain": "supplier"},
        headers=headers,
    )
    assert first.status_code == 201
    first_domains = {j["domain"] for j in first.json()["all_jobs"]}
    assert first_domains == {"supplier", "client", "product"}

    second = client.post(
        "/documents",
        files={"file": ("b.txt", content, "text/plain")},
        data={"domain": "client"},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["domain"] == "client"
    assert second.json()["document_id"] == first.json()["document_id"]
    # Same job ids both times — nothing was re-created on the re-upload.
    second_ids_by_domain = {j["domain"]: j["id"] for j in second.json()["all_jobs"]}
    first_ids_by_domain = {j["domain"]: j["id"] for j in first.json()["all_jobs"]}
    assert second_ids_by_domain == first_ids_by_domain
