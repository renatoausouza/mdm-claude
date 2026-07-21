"""#18: Data quality dashboard — registered-data health (completeness/
compliance recomputed live from current MasterRecord.fields_json, via the
same score_candidate() extraction-time candidates use — see
scoring.AlreadyApprovedField) plus pipeline health (job-status backlog per
domain, extraction failure rate, open duplicate-case backlog). No
reliability/confidence — those are candidate-time-only concepts."""

import json
import time

import fitz
import pyotp
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


def _totp_code_after(secret: str, seconds: int) -> str:
    return pyotp.TOTP(secret).at(int(time.time()) + seconds)


def _bootstrap_admin(client: TestClient) -> str:
    client.post("/users", json={"username": "admin0", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "admin0", "password": "admin-password"})
    token: str = login.json()["token"]
    return token


def _create_user(client: TestClient, admin_token: str, username: str, password: str, role: str) -> None:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201


def _login_submitter(client: TestClient, admin_token: str, username: str, password: str = "sub-password") -> str:
    _create_user(client, admin_token, username, password, "submitter")
    login = client.post("/auth/login", json={"username": username, "password": password})
    token: str = login.json()["token"]
    return token


def _login_approver(client: TestClient, admin_token: str, username: str, password: str = "app-password") -> str:
    _create_user(client, admin_token, username, password, "approver")

    enrollment_login = client.post("/auth/login", json={"username": username, "password": password})
    enrollment_token = enrollment_login.json()["token"]

    enroll = client.post("/auth/mfa/enroll", headers={"Authorization": f"Bearer {enrollment_token}"})
    secret = enroll.json()["secret"]
    valid_code = pyotp.TOTP(secret).now()
    client.post(
        "/auth/mfa/verify",
        json={"totp_code": valid_code},
        headers={"Authorization": f"Bearer {enrollment_token}"},
    )

    fresh_code = _totp_code_after(secret, 30)
    full_login = client.post(
        "/auth/login", json={"username": username, "password": password, "totp_code": fresh_code}
    )
    token: str = full_login.json()["token"]
    return token


_CPF_WEIGHTS_1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
_CPF_WEIGHTS_2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]


def _cpf_check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def _valid_cpf(index: int) -> str:
    base = f"11144{index:04d}"
    first = _cpf_check_digit(base, _CPF_WEIGHTS_1)
    second = _cpf_check_digit(base + first, _CPF_WEIGHTS_2)
    digits = base + first + second
    return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"


def _upload_client(
    client: TestClient, monkeypatch, submitter_token: str, fields: dict, invoice_text: str
) -> dict:
    """Uploads (all 3 domains extracted per #14) and returns the mapping of
    domain -> job id from the response, without approving anything."""
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text)
    upload = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "client"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert upload.status_code == 201
    return {j["domain"]: j["id"] for j in upload.json()["all_jobs"]}


def test_dashboard_computes_data_quality_and_pipeline_health(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "dash-submitter")
    approver_token = _login_approver(client, admin_token, "dash-approver")

    # Record A — every Client field populated: completeness 5/5 = 1.0.
    cpf_a = _valid_cpf(1)
    jobs_a = _upload_client(
        client,
        monkeypatch,
        submitter_token,
        {
            "tax_id": None,
            "name": "Cliente Completo",
            "email": "completo@example.com",
            "telephone": "(31) 90000-0000",
            "address": "Rua A, 1",
        },
        f"Destinatario: Cliente Completo\nDestinatario CPF: {cpf_a}",
    )
    approve_a = client.post(
        f"/jobs/{jobs_a['client']}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert approve_a.status_code == 200

    # Record B — only the two required fields populated: completeness 2/5 = 0.4.
    cpf_b = _valid_cpf(2)
    jobs_b = _upload_client(
        client,
        monkeypatch,
        submitter_token,
        {"tax_id": None, "name": "Cliente Parcial", "email": None, "telephone": None, "address": None},
        f"Destinatario: Cliente Parcial\nDestinatario CPF: {cpf_b}",
    )
    approve_b = client.post(
        f"/jobs/{jobs_b['client']}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert approve_b.status_code == 200

    # A duplicate candidate (same CPF as Record A) — left pending, never
    # approved, so it must not count toward record_count/completeness, but
    # its client job contributes a "pending_review" to the status backlog
    # and its case contributes to the open duplicate-case count.
    jobs_dup = _upload_client(
        client,
        monkeypatch,
        submitter_token,
        {"tax_id": None, "name": "Cliente Completo", "email": "novo@example.com", "telephone": None, "address": None},
        f"Destinatario: Cliente Completo\nDestinatario CPF: {cpf_a}",
    )
    dup_result = client.get(
        f"/jobs/{jobs_dup['client']}/result", headers={"Authorization": f"Bearer {submitter_token}"}
    )
    assert dup_result.json()["duplicate_review_case_id"] is not None

    # A genuinely corrupt PDF — fails extraction for all three domains.
    bad_upload = client.post(
        "/documents",
        files={"file": ("bad.pdf", b"not a real pdf", "application/pdf")},
        data={"domain": "client"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert bad_upload.status_code == 201
    assert all(j["status"] == "extraction_failed" for j in bad_upload.json()["all_jobs"])

    response = client.get("/dashboard", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 200
    body = response.json()

    client_quality = next(d for d in body["data_quality"] if d["domain"] == "client")
    assert client_quality["record_count"] == 2
    assert client_quality["completeness"] == 0.7  # (1.0 + 0.4) / 2
    assert client_quality["compliance"] == 1.0  # every populated field was valid

    client_pipeline = next(p for p in body["pipeline_health"] if p["domain"] == "client")
    assert client_pipeline["status_counts"]["approved"] == 2
    assert client_pipeline["status_counts"]["pending_review"] == 1
    assert client_pipeline["status_counts"]["extraction_failed"] == 1

    supplier_pipeline = next(p for p in body["pipeline_health"] if p["domain"] == "supplier")
    # Every upload extracts all 3 domains (#14) — 3 successful uploads left
    # their supplier job untouched (pending_review), the corrupt one failed.
    assert supplier_pipeline["status_counts"]["pending_review"] == 3
    assert supplier_pipeline["status_counts"]["extraction_failed"] == 1

    # 4 uploads x 3 domains = 12 jobs total; 3 extraction_failed (one per
    # domain, from the one corrupt upload).
    assert body["extraction_failure_rate"] == 3 / 12
    assert body["open_duplicate_case_count"] == 1


def test_dashboard_rejects_submitter(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "dash-rejected-submitter")

    response = client.get("/dashboard", headers={"Authorization": f"Bearer {submitter_token}"})
    assert response.status_code == 403


def test_dashboard_allows_admin(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)

    response = client.get("/dashboard", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200


def test_dashboard_reports_zero_for_domain_with_no_current_records(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)

    response = client.get("/dashboard", headers={"Authorization": f"Bearer {admin_token}"})
    body = response.json()
    supplier_quality = next(d for d in body["data_quality"] if d["domain"] == "supplier")
    assert supplier_quality["record_count"] == 0
    assert supplier_quality["completeness"] == 0.0
    assert supplier_quality["compliance"] == 0.0
