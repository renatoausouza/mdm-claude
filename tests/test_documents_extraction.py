import json

import fitz
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.main import app


class FakeExtractionClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def _uploader_headers(client: TestClient, username: str = "uploader") -> dict[str, str]:
    client.post("/users", json={"username": username, "password": "upload-password", "role": "submitter"})
    login = client.post("/auth/login", json={"username": username, "password": "upload-password"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_uploading_a_pdf_triggers_extraction_and_result_is_retrievable(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None}
        ),
    )

    client = TestClient(app)
    headers = _uploader_headers(client)
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")

    upload_response = client.post(
        "/documents", files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")}, headers=headers
    )
    assert upload_response.status_code == 201
    job_id = upload_response.json()["id"]
    assert upload_response.json()["status"] == "pending_review"

    result_response = client.get(f"/jobs/{job_id}/result", headers=headers)
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["status"] == "pending_review"
    assert body["result"]["cnpj"]["value"] == "11.223.344/0001-86"
    assert body["result"]["legal_name"]["value"] == "ACME Ltda"
    assert body["result"]["legal_name"]["provenance"]["source"] == "llm"
    assert body["scoring"]["reliability"] in {"Excellent", "Good", "Low"}


def test_result_for_unknown_job_id_is_404() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    response = client.get("/jobs/nonexistent/result", headers=headers)
    assert response.status_code == 404


def test_result_without_authentication_is_rejected() -> None:
    client = TestClient(app)
    response = client.get("/jobs/nonexistent/result")
    assert response.status_code == 401


def test_uploading_a_pdf_extracts_all_three_domains_at_once(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {
                "legal_name": "ACME Ltda",
                "name": "ACME Ltda",
                "email": "contato@acme.com",
                "telephone": None,
                "address": None,
                "sku": None,
                "ncm": None,
                "description": None,
                "price": None,
                "quantity": None,
                "discount": None,
            }
        ),
    )

    client = TestClient(app)
    headers = _uploader_headers(client)
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")

    upload_response = client.post(
        "/documents", files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")}, headers=headers
    )
    assert upload_response.status_code == 201
    all_jobs = upload_response.json()["all_jobs"]
    assert {job["domain"] for job in all_jobs} == {"supplier", "client", "product"}

    job_id_by_domain = {job["domain"]: job["id"] for job in all_jobs}
    for expected_domain in ("supplier", "client", "product"):
        assert job_id_by_domain[expected_domain]

    # Each domain's job is independently extracted and gettable, with no
    # second upload required.
    for expected_domain, job_id in job_id_by_domain.items():
        result_response = client.get(f"/jobs/{job_id}/result", headers=headers)
        assert result_response.status_code == 200
        body = result_response.json()
        assert body["domain"] == expected_domain
        assert body["status"] == "pending_review"

    # Each domain is also independently visible through the existing
    # per-domain review queues, without any second upload.
    for expected_domain in ("supplier", "client", "product"):
        queue_response = client.get(f"/jobs?domain={expected_domain}", headers=headers)
        assert queue_response.status_code == 200
        queue_job_ids = {job["id"] for job in queue_response.json()["jobs"]}
        assert job_id_by_domain[expected_domain] in queue_job_ids


def test_non_pdf_upload_is_marked_unsupported_format() -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    upload_response = client.post(
        "/documents", files={"file": ("data.txt", b"plain text content", "text/plain")}, headers=headers
    )
    assert upload_response.status_code == 201
    assert upload_response.json()["status"] == "unsupported_format"
