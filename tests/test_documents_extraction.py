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


def test_uploading_a_pdf_triggers_extraction_and_result_is_retrievable(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None}
        ),
    )

    client = TestClient(app)
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")

    upload_response = client.post(
        "/documents", files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")}
    )
    assert upload_response.status_code == 201
    job_id = upload_response.json()["id"]
    assert upload_response.json()["status"] == "extracted"

    result_response = client.get(f"/jobs/{job_id}/result")
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["status"] == "extracted"
    assert body["result"]["cnpj"]["value"] == "11.223.344/0001-86"
    assert body["result"]["legal_name"]["value"] == "ACME Ltda"
    assert body["result"]["legal_name"]["provenance"]["source"] == "llm"


def test_result_for_unknown_job_id_is_404() -> None:
    client = TestClient(app)
    response = client.get("/jobs/nonexistent/result")
    assert response.status_code == 404


def test_non_pdf_upload_is_marked_unsupported_format() -> None:
    client = TestClient(app)
    upload_response = client.post(
        "/documents", files={"file": ("data.txt", b"plain text content", "text/plain")}
    )
    assert upload_response.status_code == 201
    assert upload_response.json()["status"] == "unsupported_format"
