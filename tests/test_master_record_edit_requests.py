"""#20: Supplier edit-request workflow — the second-approver-reviewed
counterpart to #19's direct edit, for domains where
REQUIRES_SEGREGATION is True (Supplier). Same shape as duplicate
resolution: propose, a different approver reviews a side-by-side
comparison, approves (new MasterRecord version) or rejects (record
unchanged), both submission and decision audited."""

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


def _register_supplier(client: TestClient, monkeypatch, submitter_token: str, approver_token: str, cnpj: str) -> str:
    fields = {
        "cnpj": None,
        "legal_name": "Fornecedor Original",
        "email": "original@example.com",
        "telephone": "(31) 91111-1111",
        "address": "Rua Original, 1",
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


def _register_client(client: TestClient, monkeypatch, submitter_token: str, approver_token: str) -> str:
    fields = {
        "tax_id": None,
        "name": "Cliente Original",
        "email": "cliente@example.com",
        "telephone": "(31) 90000-0000",
        "address": "Rua Cliente, 1",
    }
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes("Destinatario: Cliente Original\nDestinatario CPF: 111.444.777-35")
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


def test_full_edit_request_round_trip(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-submitter")
    submitting_approver = _login_approver(client, admin_token, "er-submitting-approver")
    deciding_approver = _login_approver(client, admin_token, "er-deciding-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, submitting_approver, "11.222.330/0001-48"
    )

    submit = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "novo@example.com"}},
        headers={"Authorization": f"Bearer {submitting_approver}"},
    )
    assert submit.status_code == 201
    request_id = submit.json()["id"]
    assert submit.json()["status"] == "pending"

    # The record detail view surfaces the pending request.
    detail = client.get(
        f"/master-records/{record_id}", headers={"Authorization": f"Bearer {deciding_approver}"}
    )
    assert detail.json()["pending_edit_request_id"] == request_id

    # A different approver views the side-by-side comparison.
    view = client.get(
        f"/edit-requests/{request_id}", headers={"Authorization": f"Bearer {deciding_approver}"}
    )
    assert view.status_code == 200
    comparisons = {c["field"]: c for c in view.json()["comparisons"]}
    assert comparisons["email"]["old_value"] == "original@example.com"
    assert comparisons["email"]["new_value"] == "novo@example.com"
    assert comparisons["email"]["differs"] is True
    assert comparisons["legal_name"]["differs"] is False

    resolve = client.post(
        f"/edit-requests/{request_id}/resolve",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {deciding_approver}"},
    )
    assert resolve.status_code == 200
    body = resolve.json()
    assert body["status"] == "approved"

    with get_session() as session:
        old = session.get(MasterRecord, record_id)
        assert old is not None
        assert old.is_current is False

        current = (
            session.query(MasterRecord)
            .filter_by(domain="supplier", record_key=old.record_key, is_current=True)
            .first()
        )
        assert current is not None
        assert current.version == 2
        assert json.loads(current.fields_json)["email"] == "novo@example.com"

        entries = {e.action for e in session.query(AuditLogEntry).all()}
        assert "edit-requested" in entries
        assert "approved" in entries


def test_edit_request_rejects_key_field(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-keyfield-submitter")
    approver_token = _login_approver(client, admin_token, "er-keyfield-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0002-29"
    )

    response = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"cnpj": "99.999.999/0001-99"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 422


def test_edit_request_rejects_unknown_field(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-unknown-submitter")
    approver_token = _login_approver(client, admin_token, "er-unknown-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0003-00"
    )

    response = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"nonexistent": "x"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 422


def test_edit_request_rejects_non_segregated_domain(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-client-submitter")
    approver_token = _login_approver(client, admin_token, "er-client-approver")
    record_id = _register_client(client, monkeypatch, submitter_token, approver_token)

    response = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "x@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code in (400, 403)


def test_edit_request_rejects_admin_submission(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-adminsub-submitter")
    approver_token = _login_approver(client, admin_token, "er-adminsub-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0004-90"
    )

    response = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "x@example.com"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403


def test_submitting_approver_cannot_approve_own_request(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-selfapprove-submitter")
    approver_token = _login_approver(client, admin_token, "er-selfapprove-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0005-71"
    )

    submit = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "x@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    request_id = submit.json()["id"]

    resolve = client.post(
        f"/edit-requests/{request_id}/resolve",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 403


def test_submitting_approver_can_reject_own_request(monkeypatch) -> None:
    """Reject is exempt from the segregation check — same asymmetry as
    everywhere else in this app (rejecting isn't a fraud vector the way
    accepting your own change would be)."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-selfreject-submitter")
    approver_token = _login_approver(client, admin_token, "er-selfreject-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0006-52"
    )

    submit = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "x@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    request_id = submit.json()["id"]

    resolve = client.post(
        f"/edit-requests/{request_id}/resolve",
        json={"decision": "reject"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "rejected"


def test_a_second_pending_request_for_the_same_record_is_rejected(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "er-double-submitter")
    approver_token = _login_approver(client, admin_token, "er-double-approver")
    record_id = _register_supplier(
        client, monkeypatch, submitter_token, approver_token, "11.222.330/0007-33"
    )

    first = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "first@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert first.status_code == 201

    second = client.post(
        f"/master-records/{record_id}/edit-requests",
        json={"field_overrides": {"email": "second@example.com"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert second.status_code == 409
