"""Ticket #12: output-safety / stored-XSS verification (FR-18).

FR-18 requires extracted values to be treated as untrusted and output-encoded
"wherever rendered (dashboard, CLI, copy raw JSON feature)". This codebase has
no dashboard, CLI, or raw-JSON-copy feature yet (grep confirms no templating
engine — no Jinja2/HTML rendering anywhere in src/mdm); the only place
extracted values are ever rendered today is as a JSON API response body. That
is the one surface these tests can actually verify — they confirm malicious
field content is served as inert JSON, never as executable markup, and stays
byte-for-byte intact (not stripped/mangled, which would itself be a data
integrity problem distinct from XSS). The dashboard/CLI-specific parts of
FR-18 apply once those surfaces are built.
"""

import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import MasterRecord, get_session
from mdm.main import app

MALICIOUS_LEGAL_NAME = '<script>alert("xss")</script> Ltda'
MALICIOUS_ADDRESS = "Rua Teste\" onmouseover=\"alert(1)\" <img src=x onerror=alert(2)>"


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


def _upload_with_malicious_content(client: TestClient, monkeypatch, headers: dict[str, str]) -> str:
    monkeypatch.setattr(
        llm_extraction,
        "OciGenAiExtractionClient",
        lambda: FakeExtractionClient(
            {
                "legal_name": MALICIOUS_LEGAL_NAME,
                "email": "contato@acme.com",
                "telephone": None,
                "address": MALICIOUS_ADDRESS,
            }
        ),
    )
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86")
    response = client.post(
        "/documents", files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")}, headers=headers
    )
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


def test_job_result_response_is_served_as_json_not_html(monkeypatch) -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    job_id = _upload_with_malicious_content(client, monkeypatch, headers)

    response = client.get(f"/jobs/{job_id}/result", headers=headers)
    assert response.status_code == 200
    # A browser only ever executes <script> content served as HTML; a
    # JSON content-type is itself the output-encoding boundary here.
    assert response.headers["content-type"].startswith("application/json")


def test_malicious_field_value_round_trips_intact_and_inert(monkeypatch) -> None:
    """The value must survive the pipeline byte-for-byte — not stripped,
    escaped-and-corrupted, or otherwise silently mangled — while never being
    interpreted as anything other than a string value."""
    client = TestClient(app)
    headers = _uploader_headers(client)
    job_id = _upload_with_malicious_content(client, monkeypatch, headers)

    response = client.get(f"/jobs/{job_id}/result", headers=headers)
    body = response.json()

    assert body["result"]["legal_name"]["value"] == MALICIOUS_LEGAL_NAME
    assert body["result"]["address"]["value"] == MALICIOUS_ADDRESS
    # It's parsed JSON data at this point (a Python str), not markup that
    # got spliced into an HTML document — there is nothing here for a
    # browser to execute.
    assert isinstance(body["result"]["legal_name"]["value"], str)


def test_approving_malicious_content_stores_it_safely_json_encoded(monkeypatch) -> None:
    client = TestClient(app)
    headers = _uploader_headers(client)
    job_id = _upload_with_malicious_content(client, monkeypatch, headers)

    # Approve with a different, MFA-verified approver account.
    admin_token = _bootstrap_admin_token(client)
    client.post(
        "/users",
        json={"username": "approver-xss", "password": "app-password", "role": "approver"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    enrollment_login = client.post(
        "/auth/login", json={"username": "approver-xss", "password": "app-password"}
    )
    enrollment_token = enrollment_login.json()["token"]
    enroll = client.post("/auth/mfa/enroll", headers={"Authorization": f"Bearer {enrollment_token}"})
    secret = enroll.json()["secret"]
    client.post(
        "/auth/mfa/verify",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers={"Authorization": f"Bearer {enrollment_token}"},
    )
    full_login = client.post(
        "/auth/login",
        json={
            "username": "approver-xss",
            "password": "app-password",
            "totp_code": pyotp.TOTP(secret).at(int(time.time()) + 30),
        },
    )
    approver_token = full_login.json()["token"]

    approve_response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert approve_response.status_code == 200
    master_record_id = approve_response.json()["master_record_id"]

    with get_session() as session:
        record = session.get(MasterRecord, master_record_id)
        assert record is not None
        fields = json.loads(record.fields_json)  # json.loads is not an interpreter — inert by construction
        assert fields["legal_name"] == MALICIOUS_LEGAL_NAME
        assert fields["address"] == MALICIOUS_ADDRESS
