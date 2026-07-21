"""#19: direct edit for Client/Product master records — approver-only
(not admin, mirroring every other record-decision gate in this app),
non-key fields only, versioned exactly like every other MasterRecord
mutation (new row, prior marked is_current=False), audited. Supplier is
explicitly out of scope here — it goes through #20's edit-request
workflow instead, since REQUIRES_SEGREGATION is True for it."""

import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import AuditLogEntry, MasterRecord, get_session
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


def _register_client(client: TestClient, monkeypatch, submitter_token: str, approver_token: str, cpf_index: int) -> str:
    cpf = _valid_cpf(cpf_index)
    fields = {
        "tax_id": None,
        "name": "Cliente Original",
        "email": "original@example.com",
        "telephone": "(31) 90000-0000",
        "address": "Rua Original, 1",
    }
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(f"Destinatario: Cliente Original\nDestinatario CPF: {cpf}")
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


def _register_supplier(client: TestClient, monkeypatch, submitter_token: str, approver_token: str) -> str:
    cnpj = "11.222.333/0001-81"  # a real checksum-valid test CNPJ
    fields = {
        "cnpj": None,
        "legal_name": "Fornecedor Original",
        "email": "fornecedor@example.com",
        "telephone": "(31) 91111-1111",
        "address": "Rua Fornecedor, 1",
    }
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(f"Emitente: Fornecedor Original\nEmitente CNPJ: {cnpj}")
    upload = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "supplier"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert upload.status_code == 201
    job_id = next(j["id"] for j in upload.json()["all_jobs"] if j["domain"] == "supplier")
    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200
    record_id: str = approve.json()["master_record_id"]
    return record_id


def test_approver_can_edit_client_record_creating_a_new_version(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-submitter")
    approver_token = _login_approver(client, admin_token, "edit-approver")
    old_record_id = _register_client(client, monkeypatch, submitter_token, approver_token, 1)

    response = client.post(
        f"/master-records/{old_record_id}/edit",
        json={"field_overrides": {"email": "updated@example.com", "telephone": "(31) 99999-8888"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] != old_record_id
    assert body["version"] == 2
    assert body["fields"]["email"] == "updated@example.com"
    assert body["fields"]["telephone"] == "(31) 99999-8888"
    # Untouched fields carry forward from the prior version.
    assert body["fields"]["name"] == "Cliente Original"

    with get_session() as session:
        old = session.get(MasterRecord, old_record_id)
        assert old is not None
        assert old.is_current is False

        new = session.get(MasterRecord, body["id"])
        assert new is not None
        assert new.is_current is True
        assert new.record_key == old.record_key
        assert new.first_registered_at == old.first_registered_at

        entries = session.query(AuditLogEntry).filter_by(action="edited").all()
        assert len(entries) == 1
        assert entries[0].document_id is not None


def test_edit_rejects_the_key_field(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-keyfield-submitter")
    approver_token = _login_approver(client, admin_token, "edit-keyfield-approver")
    record_id = _register_client(client, monkeypatch, submitter_token, approver_token, 2)

    response = client.post(
        f"/master-records/{record_id}/edit",
        json={"field_overrides": {"tax_id": "999.999.999-99"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 422


def test_edit_rejects_unknown_field(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-unknown-submitter")
    approver_token = _login_approver(client, admin_token, "edit-unknown-approver")
    record_id = _register_client(client, monkeypatch, submitter_token, approver_token, 3)

    response = client.post(
        f"/master-records/{record_id}/edit",
        json={"field_overrides": {"nonexistent_field": "x"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 422


def test_edit_rejects_supplier_records(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-supplier-submitter")
    approver_token = _login_approver(client, admin_token, "edit-supplier-approver")
    record_id = _register_supplier(client, monkeypatch, submitter_token, approver_token)

    response = client.post(
        f"/master-records/{record_id}/edit",
        json={"field_overrides": {"email": "new@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code in (400, 403)


def test_edit_rejects_admin(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-admin-submitter")
    approver_token = _login_approver(client, admin_token, "edit-admin-approver")
    record_id = _register_client(client, monkeypatch, submitter_token, approver_token, 4)

    response = client.post(
        f"/master-records/{record_id}/edit",
        json={"field_overrides": {"email": "new@example.com"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403


def test_edit_rejects_submitter(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "edit-plain-submitter")
    approver_token = _login_approver(client, admin_token, "edit-plain-approver")
    record_id = _register_client(client, monkeypatch, submitter_token, approver_token, 5)

    response = client.post(
        f"/master-records/{record_id}/edit",
        json={"field_overrides": {"email": "new@example.com"}},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 403
