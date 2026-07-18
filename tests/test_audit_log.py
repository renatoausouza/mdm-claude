"""GET /audit — admin-only view over AuditLogEntry, backing the web
frontend's audit/history screen (solution-brief.md §16). No "auditor" role
exists in this codebase (UserRole is submitter/approver/admin only), so this
is scoped to admin rather than the brief's aspirational "auditor/admin"."""

from fastapi.testclient import TestClient

from mdm.main import app


def _bootstrap_admin_token(client: TestClient) -> str:
    client.post("/users", json={"username": "admin0", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "admin0", "password": "admin-password"})
    token: str = login.json()["token"]
    return token


def _create_submitter(client: TestClient, admin_token: str) -> dict[str, str]:
    client.post(
        "/users",
        json={"username": "submitter1", "password": "sub-password", "role": "submitter"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    login = client.post("/auth/login", json={"username": "submitter1", "password": "sub-password"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_sees_audit_entries_for_an_upload() -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin_token(client)
    submitter_headers = _create_submitter(client, admin_token)

    upload = client.post(
        "/documents",
        files={"file": ("notes.txt", b"some content", "text/plain")},
        headers=submitter_headers,
    )
    document_id = upload.json()["document_id"]

    response = client.get("/audit", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert any(e["document_id"] == document_id and e["action"] == "submitted" for e in entries)


def test_non_admin_cannot_view_audit_log() -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin_token(client)
    submitter_headers = _create_submitter(client, admin_token)

    response = client.get("/audit", headers=submitter_headers)
    assert response.status_code == 403


def test_requires_authentication() -> None:
    client = TestClient(app)
    response = client.get("/audit")
    assert response.status_code == 401


def test_filters_by_document_id() -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin_token(client)
    submitter_headers = _create_submitter(client, admin_token)

    first = client.post(
        "/documents", files={"file": ("a.txt", b"first content", "text/plain")}, headers=submitter_headers
    )
    second = client.post(
        "/documents", files={"file": ("b.txt", b"second content", "text/plain")}, headers=submitter_headers
    )
    first_doc_id = first.json()["document_id"]
    second_doc_id = second.json()["document_id"]

    response = client.get(
        "/audit", params={"document_id": first_doc_id}, headers={"Authorization": f"Bearer {admin_token}"}
    )
    entries = response.json()["entries"]
    assert len(entries) >= 1
    assert all(e["document_id"] == first_doc_id for e in entries)
    assert not any(e["document_id"] == second_doc_id for e in entries)
