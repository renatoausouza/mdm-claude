"""GET /jobs — backs the review-queue views in the web frontend. Not part of
the original API surface; added alongside the frontend since a queue has no
way to discover job ids otherwise."""

import json

from fastapi.testclient import TestClient

from mdm import documents, llm_extraction
from mdm.main import app


class FakeExtractionClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _bootstrap_admin_token(client: TestClient) -> str:
    client.post("/users", json={"username": "_bootstrap_admin", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "_bootstrap_admin", "password": "admin-password"})
    token: str = login.json()["token"]
    return token


def _uploader_headers(client: TestClient, username: str = "uploader") -> dict[str, str]:
    admin_token = _bootstrap_admin_token(client)
    client.post(
        "/users",
        json={"username": username, "password": "upload-password", "role": "submitter"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    login = client.post("/auth/login", json={"username": username, "password": "upload-password"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, headers: dict, content: bytes, domain: str = "supplier") -> str:
    response = client.post(
        "/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        data={"domain": domain},
        headers=headers,
    )
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


def test_lists_jobs_across_domains() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)

    job_a = _upload(client, headers, b"supplier doc", domain="supplier")
    job_b = _upload(client, headers, b"client doc", domain="client")

    response = client.get("/jobs", headers=headers)
    assert response.status_code == 200
    job_ids = {job["id"] for job in response.json()["jobs"]}
    assert {job_a, job_b} <= job_ids


def test_filters_by_domain() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)

    job_supplier = _upload(client, headers, b"only supplier doc", domain="supplier")
    job_client = _upload(client, headers, b"only client doc", domain="client")

    response = client.get("/jobs", params={"domain": "client"}, headers=headers)
    jobs = response.json()["jobs"]
    assert all(job["domain"] == "client" for job in jobs)
    job_ids = {job["id"] for job in jobs}
    assert job_client in job_ids
    assert job_supplier not in job_ids


def test_filters_by_status() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    _upload(client, headers, b"unsupported format doc.notreal")

    response = client.get("/jobs", params={"status": "unsupported_format"}, headers=headers)
    jobs = response.json()["jobs"]
    assert len(jobs) >= 1
    assert all(job["status"] == "unsupported_format" for job in jobs)


def test_unknown_domain_filter_is_rejected() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)

    response = client.get("/jobs", params={"domain": "nonexistent"}, headers=headers)
    assert response.status_code == 400


def test_requires_authentication() -> None:
    client = TestClient(app)
    response = client.get("/jobs")
    assert response.status_code == 401


def test_job_list_response_reports_has_more_when_truncated(monkeypatch) -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    monkeypatch.setattr(documents, "_JOB_LIST_LIMIT", 2)

    for i in range(3):
        _upload(client, headers, f"doc {i}".encode())

    response = client.get("/jobs", headers=headers)
    body = response.json()
    assert len(body["jobs"]) == 2
    assert body["has_more"] is True


def test_job_list_response_has_more_is_false_when_not_truncated(monkeypatch) -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    monkeypatch.setattr(documents, "_JOB_LIST_LIMIT", 5)

    _upload(client, headers, b"only one doc")

    response = client.get("/jobs", headers=headers)
    assert response.json()["has_more"] is False


def test_job_result_includes_uploaded_by(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin_token(client)
    submitter_headers = _uploader_headers(client, "uploaded-by-check")
    login = client.post(
        "/auth/login", json={"username": "uploaded-by-check", "password": "upload-password"}
    )
    submitter_id = login.json()["user_id"]

    job_id = _upload(client, submitter_headers, b"some doc content")

    response = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.json()["uploaded_by"] == submitter_id


def test_job_summary_includes_uploader_and_pending_duplicate_case(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin_token(client)
    submitter_headers = _uploader_headers(client, "dup-submitter")

    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": None, "telephone": None, "address": None}
        ),
    )
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Fornecedor CNPJ: 11.223.344/0001-86", fontsize=10)
    pdf_bytes: bytes = doc.tobytes()
    doc.close()

    upload = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "supplier"},
        headers=submitter_headers,
    )
    job_id = upload.json()["id"]

    response = client.get("/jobs", headers=submitter_headers)
    summary = next(job for job in response.json()["jobs"] if job["id"] == job_id)
    assert summary["uploaded_by"] is not None
    assert summary["duplicate_review_case_id"] is None  # nothing registered yet to match against
    assert summary["domain"] == "supplier"
    assert summary["status"] == "pending_review"
