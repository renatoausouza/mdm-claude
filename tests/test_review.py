import json
import threading
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


def _get_enrollment_scoped_token(client: TestClient, admin_token: str, username: str, password: str = "app2-password") -> str:
    """An approver session that has NOT completed MFA enrollment/verification."""
    _create_user(client, admin_token, username, password, "approver")
    login = client.post("/auth/login", json={"username": username, "password": password})
    token: str = login.json()["token"]
    return token


def _upload_pending_review_job(client: TestClient, monkeypatch, submitter_token: str) -> str:
    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None}
        ),
    )
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
    job_id: str = response.json()["id"]
    return job_id


def test_approving_a_supplier_job_creates_a_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter1")
    approver_token = _login_approver(client, admin_token, "approver1")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["master_record_id"] is not None

    with get_session() as session:
        record = session.get(MasterRecord, body["master_record_id"])
        assert record is not None
        assert record.domain == "supplier"
        assert record.version == 1
        assert record.is_current is True
        fields = json.loads(record.fields_json)
        assert fields["legal_name"] == "ACME Ltda"
        # Stored normalized (digits-only) so it's a stable dedup/link key
        # for #7 — matches record_key below.
        assert fields["cnpj"] == "11223344000186"
        assert record.record_key == "11223344000186"


def test_approving_own_submission_is_blocked_by_segregation_of_duties(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    # The same physical user account acts as both submitter and approver —
    # segregation of duties keys off user id, not role, so give this
    # account the approver role (with MFA) to isolate the check.
    approver_token = _login_approver(client, admin_token, "selfapprover")

    job_id = _upload_pending_review_job(client, monkeypatch, approver_token)

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert response.status_code == 403

    with get_session() as session:
        assert session.query(MasterRecord).count() == 0


def test_rejecting_a_job_writes_no_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter2")
    approver_token = _login_approver(client, admin_token, "approver2")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    response = client.post(
        f"/jobs/{job_id}/reject",
        json={"notes": "CNPJ does not match the invoice"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    with get_session() as session:
        assert session.query(MasterRecord).count() == 0
        event = session.query(ApprovalEvent).filter_by(extraction_job_id=job_id).first()
        assert event is not None
        assert event.decision == "rejected"
        assert event.notes == "CNPJ does not match the invoice"


def test_request_info_requires_notes_and_writes_no_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter3")
    approver_token = _login_approver(client, admin_token, "approver3")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    missing_notes = client.post(
        f"/jobs/{job_id}/request-info", json={}, headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert missing_notes.status_code == 422

    response = client.post(
        f"/jobs/{job_id}/request-info",
        json={"notes": "Please confirm the telephone number"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_info"

    with get_session() as session:
        assert session.query(MasterRecord).count() == 0


def test_job_can_still_be_decided_after_needs_info(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter4")
    approver_token = _login_approver(client, admin_token, "approver4")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)
    client.post(
        f"/jobs/{job_id}/request-info",
        json={"notes": "Please double-check the address"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_non_approver_role_cannot_make_review_decisions(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter5")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {submitter_token}"}
    )
    assert response.status_code == 403


def test_approval_requires_a_fully_mfa_verified_session(monkeypatch) -> None:
    """An approver session that hasn't completed MFA enrollment/verification
    (only the narrow mfa_enrollment scope) must not be usable to approve —
    proves D13's MFA requirement is enforced at the point of approval."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter6")
    unverified_token = _get_enrollment_scoped_token(client, admin_token, "approver6")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {unverified_token}"}
    )
    assert response.status_code == 403


def test_approving_a_job_not_pending_review_is_rejected(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter7")
    approver_token = _login_approver(client, admin_token, "approver7")

    upload = client.post(
        "/documents",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    job_id = upload.json()["id"]
    assert upload.json()["status"] == "unsupported_format"

    response = client.post(
        f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    assert response.status_code == 409


def test_concurrent_approvals_of_the_same_job_only_one_succeeds(monkeypatch) -> None:
    """Regression test: two approvers (or a double-click) racing
    POST /jobs/{id}/approve for the same job must not both pass the status
    check and both create a MasterRecord — the second must lose the race
    cleanly (409), not silently double-register the supplier."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter9")
    approver_token = _login_approver(client, admin_token, "approver9")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)

    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def do_approve() -> None:
        barrier.wait()
        response = client.post(
            f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
        )
        statuses.append(response.status_code)

    threads = [threading.Thread(target=do_approve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 409]
    with get_session() as session:
        assert session.query(MasterRecord).count() == 1


def test_every_decision_writes_an_audit_log_entry_with_actor_and_before_after(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "submitter8")
    approver_token = _login_approver(client, admin_token, "approver8")

    job_id = _upload_pending_review_job(client, monkeypatch, submitter_token)
    client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})

    with get_session() as session:
        entries = session.query(AuditLogEntry).filter_by(action="approved").all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.actor_user_id is not None
        assert json.loads(entry.before_json)["job_status"] == "pending_review"
        assert json.loads(entry.after_json)["job_status"] == "approved"
