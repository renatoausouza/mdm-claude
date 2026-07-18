"""#9: Client duplicate detection — replicates #7's pattern (see
tests/test_duplicates.py) for the Client domain, matching on normalized
CPF/CNPJ, with one deliberate difference: Client has no segregation-of-duties
requirement (#8), so self-resolution is allowed here where it's blocked for
Supplier."""

import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import ApprovalEvent, DuplicateReviewCase, MasterRecord, get_session
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


def _upload_client_job(
    client: TestClient, monkeypatch, token: str, fields: dict, cpf: str = "111.444.777-35", invoice_text: str | None = None
) -> str:
    monkeypatch.setattr(llm_extraction, "OllamaExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text or f"Destinatario CPF: {cpf}")
    response = client.post(
        "/documents",
        files={"file": ("client-doc.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "client"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


def _register_initial_client(client, monkeypatch, admin_token) -> tuple[str, str]:
    submitter_token = _login_submitter(client, admin_token, "original-client-submitter")
    approver_token = _login_approver(client, admin_token, "original-client-approver")

    job_id = _upload_client_job(
        client,
        monkeypatch,
        submitter_token,
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None},
    )
    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200
    return approve.json()["master_record_id"], "111.444.777-35"


def test_matching_tax_id_creates_duplicate_case_instead_of_second_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, cpf = _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Joao Silva", "email": "joao-novo@example.com", "telephone": "1122223333", "address": None},
        cpf=cpf,
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    body = result.json()
    assert body["status"] == "pending_review"
    assert body["duplicate_review_case_id"] is not None

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1
        case = session.get(DuplicateReviewCase, body["duplicate_review_case_id"])
        assert case is not None
        assert case.matched_master_record_id == original_record_id
        assert case.status == "pending"
        assert case.match_key == "11144477735"


def test_reviewer_sees_old_vs_new_values_side_by_side(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter2")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Joao Silva", "email": "novo@example.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    case_response = client.get(f"/duplicates/{case_id}", headers={"Authorization": f"Bearer {new_submitter_token}"})
    assert case_response.status_code == 200
    comparisons = {c["field"]: c for c in case_response.json()["comparisons"]}

    assert comparisons["email"]["old_value"] == "joao@example.com"
    assert comparisons["email"]["new_value"] == "novo@example.com"
    assert comparisons["email"]["differs"] is True
    assert comparisons["name"]["differs"] is False


def test_accepting_all_creates_a_new_master_record_version_and_preserves_the_old(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter3")
    approver_token = _login_approver(client, admin_token, "second-client-approver3")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Joao Silva", "email": "novo@example.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    new_record_id = resolve.json()["master_record_id"]
    assert new_record_id != original_record_id

    with get_session() as session:
        old_record = session.get(MasterRecord, original_record_id)
        new_record = session.get(MasterRecord, new_record_id)
        assert old_record is not None and new_record is not None
        assert old_record.is_current is False
        assert new_record.is_current is True
        assert new_record.version == old_record.version + 1
        assert new_record.record_key == old_record.record_key
        fields = json.loads(new_record.fields_json)
        assert fields["email"] == "novo@example.com"


def test_partial_acceptance_only_updates_the_chosen_fields(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter4")
    approver_token = _login_approver(client, admin_token, "second-client-approver4")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Joao Silva RENAMED", "email": "novo@example.com", "telephone": "1133334444", "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "partial", "accepted_fields": ["telephone"]},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    new_record_id = resolve.json()["master_record_id"]

    with get_session() as session:
        new_record = session.get(MasterRecord, new_record_id)
        assert new_record is not None
        fields = json.loads(new_record.fields_json)
        assert fields["telephone"] == "1133334444"
        assert fields["name"] == "Joao Silva"  # kept the OLD value, not the new candidate's
        assert fields["email"] == "joao@example.com"


def test_rejecting_a_duplicate_writes_no_new_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter5")
    approver_token = _login_approver(client, admin_token, "second-client-approver5")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Fraudulent Rename", "email": None, "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    with get_session() as session:
        count_before = session.query(MasterRecord).count()

    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "reject_all", "notes": "Not the same person"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "rejected"

    with get_session() as session:
        assert session.query(MasterRecord).count() == count_before


def test_normal_approve_endpoint_is_blocked_while_a_duplicate_case_is_pending(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter6")
    approver_token = _login_approver(client, admin_token, "second-client-approver6")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Joao Silva", "email": "x@example.com", "telephone": None, "address": None},
    )

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 409

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1


def test_self_resolution_is_allowed_for_client_unlike_supplier(monkeypatch) -> None:
    """The key difference from #7: Client has no segregation-of-duties rule
    (#8), so the SAME user submitting and resolving a duplicate case is
    allowed, unlike test_resolving_a_duplicate_for_own_submission_is_blocked
    in tests/test_duplicates.py (Supplier)."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_client(client, monkeypatch, admin_token)

    approver_token = _login_approver(client, admin_token, "self-resolve-client")
    job_id = _upload_client_job(
        client,
        monkeypatch,
        approver_token,
        {"name": "Joao Silva", "email": "self@example.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    response = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200


def test_no_master_record_update_happens_without_the_resolve_step(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_client(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-client-submitter7")
    _upload_client_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"name": "Should Not Apply", "email": None, "telephone": None, "address": None},
    )

    with get_session() as session:
        record = session.get(MasterRecord, original_record_id)
        assert record is not None
        assert record.is_current is True
        fields = json.loads(record.fields_json)
        assert fields["name"] == "Joao Silva"
        assert session.query(MasterRecord).count() == 1
        assert session.query(ApprovalEvent).count() == 1  # only the original approval
