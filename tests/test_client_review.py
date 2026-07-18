import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import ApprovalEvent, AuditLogEntry, MasterRecord, get_session
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


def _upload_client_job(
    client: TestClient, monkeypatch, headers: dict[str, str], fields: dict, invoice_text: str | None = None
) -> str:
    monkeypatch.setattr(llm_extraction, "OllamaExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text or "Destinatario CPF: 111.444.777-35")
    response = client.post(
        "/documents",
        files={"file": ("client-doc.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "client"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
    job_id: str = response.json()["id"]
    return job_id


def test_uploading_with_client_domain_produces_client_candidate(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver1")

    job_id = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None},
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    body = result.json()
    assert body["domain"] == "client"
    assert body["result"]["tax_id"]["value"] == "111.444.777-35"
    assert body["result"]["name"]["value"] == "Joao Silva"
    assert body["scoring"]["reliability"] in {"Excellent", "Good", "Low"}


def test_self_approval_is_allowed_for_client_domain(monkeypatch) -> None:
    """#8's core distinction from #6: Client approvals are single-approver,
    self-approval allowed, no segregation-of-duties block."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver2")

    # The SAME account both uploads and approves.
    job_id = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None},
    )

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["master_record_id"] is not None


def test_approving_a_client_creates_a_versioned_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver3")

    job_id = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None},
    )

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    master_record_id = response.json()["master_record_id"]

    with get_session() as session:
        record = session.get(MasterRecord, master_record_id)
        assert record is not None
        assert record.domain == "client"
        assert record.version == 1
        assert record.is_current is True
        # Client has no duplicate-detection/resolution path yet (#9), so
        # record_key is a fresh random id, not the normalized tax_id — using
        # the natural key here without #9's resolve-a-collision machinery
        # would let a second approval for the same person/company hit the
        # DB's one-current-per-key constraint and get stuck with no way to
        # resolve it.
        assert record.record_key != "11144477735"
        fields = json.loads(record.fields_json)
        assert fields["name"] == "Joao Silva"
        assert fields["tax_id"] == "11144477735"  # still captured on the record itself
        assert fields["tax_id"] == "11144477735"


def test_every_client_action_writes_an_audit_log_entry(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver4")

    job_id = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": None, "telephone": None, "address": None},
    )
    client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})

    with get_session() as session:
        submitted = session.query(AuditLogEntry).filter_by(action="submitted").all()
        approved = session.query(AuditLogEntry).filter_by(action="approved").all()
        assert len(submitted) == 1
        assert len(approved) == 1
        assert approved[0].actor_user_id is not None

        event = session.query(ApprovalEvent).filter_by(extraction_job_id=job_id).first()
        assert event is not None
        assert event.decision == "approved"


def test_client_scoring_uses_client_required_fields_not_supplier(monkeypatch) -> None:
    # Missing "legal_name"/"cnpj" (Supplier's required fields) must not
    # matter for Client — only "name" + "tax_id" (Client's own required
    # fields, #8) drive the hard floor.
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver5")

    job_id = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": "11987654321", "address": "Rua A, 1"},
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    scoring = result.json()["scoring"]
    assert scoring["missing_required_fields"] == []
    assert scoring["reliability"] in {"Excellent", "Good"}


def test_approving_two_clients_with_the_same_tax_id_does_not_get_stuck(monkeypatch) -> None:
    """Regression test: Client has no duplicate-detection/resolution path
    yet (#9), so approving a second candidate for the same CPF must not
    hit the DB's one-current-record-per-key constraint and get permanently
    stuck in an unresolvable 409 (there is no case to point it at until #9
    ships) — a very ordinary scenario (the same person appears in two
    documents) that has nothing to do with true concurrency."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "client-approver6")

    first_job = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None},
    )
    first_response = client.post(
        f"/jobs/{first_job}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert first_response.status_code == 200

    second_job = _upload_client_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        {"name": "Joao Silva", "email": "joao-novo@example.com", "telephone": None, "address": None},
        invoice_text="Destinatario CPF: 111.444.777-35 -- second document, same person",
    )
    second_response = client.post(
        f"/jobs/{second_job}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert second_response.status_code == 200
    assert second_response.json()["master_record_id"] != first_response.json()["master_record_id"]
