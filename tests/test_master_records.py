"""#17: Browse & search master data — extends the existing
GET /master-records/search (previously approver-only, hard-capped at 50,
built narrowly for duplicate-linking) with real pagination and admin
viewing access, and adds GET /master-records/{id} for a stable,
refreshable record detail view (also the foundation #19/#20 will fetch a
specific record by id from)."""

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


def _upload_and_approve_client(
    client: TestClient, monkeypatch, submitter_token: str, approver_token: str, fields: dict, invoice_text: str
) -> str:
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text)
    upload = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "client"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert upload.status_code == 201
    job_id = next(j["id"] for j in upload.json()["all_jobs"] if j["domain"] == "client")

    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200
    record_id: str = approve.json()["master_record_id"]
    return record_id


_CPF_WEIGHTS_1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
_CPF_WEIGHTS_2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]


def _cpf_check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def _valid_cpf(index: int) -> str:
    """A distinct, checksum-valid CPF per index (mirrors
    mdm.cpf_validation.is_valid_cpf's own algorithm) — tax_id is populated
    by regex + role tagging from the invoice text, not from the fake LLM
    JSON, so it must be a real, correctly-formatted, checksum-valid CPF or
    it's silently dropped, same as a real mis-scanned document would be."""
    base = f"11144{index:04d}"
    first = _cpf_check_digit(base, _CPF_WEIGHTS_1)
    second = _cpf_check_digit(base + first, _CPF_WEIGHTS_2)
    digits = base + first + second
    return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"


_CLIENT_FIELDS_TEMPLATE = {
    "tax_id": None,
    "name": None,
    "email": "contato@example.com",
    "telephone": None,
    "address": "Rua das Flores, 100, Belo Horizonte, Minas Gerais",
}


def _client_fields(name: str) -> dict:
    fields = dict(_CLIENT_FIELDS_TEMPLATE)
    fields["name"] = name
    return fields


def _client_invoice_text(name: str, cpf: str) -> str:
    # "Destinatario" (recipient) is what role_tagging.py tags as the
    # client role — matches the convention test_client_duplicates.py
    # already uses ("Emitente" is the supplier-role label instead).
    return f"Destinatario: {name}\nDestinatario CPF: {cpf}"


def test_search_paginates_results_instead_of_silently_capping(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "paginate-submitter")
    approver_token = _login_approver(client, admin_token, "paginate-approver")

    ids = []
    for i in range(3):
        name = f"Cliente Minas {i}"
        record_id = _upload_and_approve_client(
            client,
            monkeypatch,
            submitter_token,
            approver_token,
            _client_fields(name),
            _client_invoice_text(name, _valid_cpf(i)),
        )
        ids.append(record_id)

    page1 = client.get(
        "/master-records/search",
        params={"domain": "client", "q": "", "limit": 2, "offset": 0},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["results"]) == 2
    assert body1["has_more"] is True

    page2 = client.get(
        "/master-records/search",
        params={"domain": "client", "q": "", "limit": 2, "offset": 2},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    body2 = page2.json()
    assert len(body2["results"]) == 1
    assert body2["has_more"] is False

    all_returned_ids = {r["id"] for r in body1["results"]} | {r["id"] for r in body2["results"]}
    assert all_returned_ids == set(ids)


def test_search_allows_admin_as_well_as_approver(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "admin-view-submitter")
    approver_token = _login_approver(client, admin_token, "admin-view-approver")
    _upload_and_approve_client(
        client,
        monkeypatch,
        submitter_token,
        approver_token,
        _client_fields("Cliente Admin View"),
        _client_invoice_text("Cliente Admin View", _valid_cpf(101)),
    )

    admin_response = client.get(
        "/master-records/search",
        params={"domain": "client", "q": "Admin View"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    assert len(admin_response.json()["results"]) == 1


def test_search_still_rejects_submitter(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "still-rejected-submitter")

    response = client.get(
        "/master-records/search",
        params={"domain": "client", "q": ""},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 403


def test_get_master_record_by_id_returns_full_current_fields(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "detail-submitter")
    approver_token = _login_approver(client, admin_token, "detail-approver")
    cpf = _valid_cpf(102)
    record_id = _upload_and_approve_client(
        client,
        monkeypatch,
        submitter_token,
        approver_token,
        _client_fields("Cliente Detalhe"),
        _client_invoice_text("Cliente Detalhe", cpf),
    )

    response = client.get(
        f"/master-records/{record_id}",
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == record_id
    assert body["domain"] == "client"
    assert body["fields"]["name"] == "Cliente Detalhe"
    assert body["fields"]["tax_id"] == cpf.replace(".", "").replace("-", "")
    assert "first_registered_at" in body
    assert "last_updated_at" in body


def test_get_master_record_not_found_returns_404(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "detail-404-approver")

    response = client.get(
        "/master-records/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 404


def test_get_master_record_requires_approver_or_admin(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "detail-403-submitter")
    approver_token = _login_approver(client, admin_token, "detail-403-approver")
    record_id = _upload_and_approve_client(
        client,
        monkeypatch,
        submitter_token,
        approver_token,
        _client_fields("Cliente Sem Acesso"),
        _client_invoice_text("Cliente Sem Acesso", _valid_cpf(103)),
    )

    response = client.get(
        f"/master-records/{record_id}",
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 403
