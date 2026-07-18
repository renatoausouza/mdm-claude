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


def _upload_pending_review_job(
    client: TestClient, monkeypatch, submitter_token: str, fields: dict, cnpj: str = "11.223.344/0001-86"
) -> str:
    monkeypatch.setattr(llm_extraction, "OllamaExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(f"Fornecedor CNPJ: {cnpj}")
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


def _register_initial_supplier(client, monkeypatch, admin_token) -> tuple[str, str]:
    """Uploads and approves a first supplier candidate, returning
    (master_record_id, cnpj) so a second upload can be engineered as a
    duplicate of it."""
    submitter_token = _login_submitter(client, admin_token, "original-submitter")
    approver_token = _login_approver(client, admin_token, "original-approver")

    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        submitter_token,
        {"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None},
    )
    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200
    return approve.json()["master_record_id"], "11.223.344/0001-86"


def test_matching_cnpj_creates_duplicate_case_instead_of_second_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, cnpj = _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda Atualizada", "email": "novo@acme.com", "telephone": "1122223333", "address": None},
        cnpj=cnpj,
    )

    upload_status = client.get(
        f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"}
    )
    body = upload_status.json()
    assert body["status"] == "pending_review"
    assert body["duplicate_review_case_id"] is not None

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1  # still just the original — no auto second record
        case = session.get(DuplicateReviewCase, body["duplicate_review_case_id"])
        assert case is not None
        assert case.matched_master_record_id == original_record_id
        assert case.status == "pending"


def test_duplicate_case_response_includes_domain_and_submitter_for_segregation_ui(monkeypatch) -> None:
    # The frontend can't tell "am I the submitter of this candidate" without
    # these — needed to warn/disable accept actions before the segregation
    # check in resolve_duplicate (below) rejects them with a 403.
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "third-submitter")
    login = client.post("/auth/login", json={"username": "third-submitter", "password": "sub-password"})
    submitter_id = login.json()["user_id"]
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda Atualizada", "email": "novo@acme.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    case = client.get(f"/duplicates/{case_id}", headers={"Authorization": f"Bearer {new_submitter_token}"})
    assert case.status_code == 200
    body = case.json()
    assert body["domain"] == "supplier"
    assert body["uploaded_by"] == submitter_id


def test_reviewer_sees_old_vs_new_values_side_by_side(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter2")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda", "email": "novo@acme.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    case_response = client.get(f"/duplicates/{case_id}", headers={"Authorization": f"Bearer {new_submitter_token}"})
    assert case_response.status_code == 200
    comparisons = {c["field"]: c for c in case_response.json()["comparisons"]}

    assert comparisons["email"]["old_value"] == "contato@acme.com"
    assert comparisons["email"]["new_value"] == "novo@acme.com"
    assert comparisons["email"]["differs"] is True
    assert comparisons["legal_name"]["differs"] is False


def test_accepting_all_creates_a_new_master_record_version_and_preserves_the_old(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter3")
    approver_token = _login_approver(client, admin_token, "second-approver3")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda", "email": "novo@acme.com", "telephone": None, "address": None},
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
        assert new_record.first_registered_at == old_record.first_registered_at
        fields = json.loads(new_record.fields_json)
        assert fields["email"] == "novo@acme.com"

        assert session.query(MasterRecord).filter_by(record_key=old_record.record_key).count() == 2


def test_partial_acceptance_only_updates_the_chosen_fields(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter4")
    approver_token = _login_approver(client, admin_token, "second-approver4")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {
            "legal_name": "ACME Ltda RENAMED",
            "email": "novo@acme.com",
            "telephone": "1133334444",
            "address": None,
        },
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
        # accepted field changed...
        assert fields["telephone"] == "1133334444"
        # ...everything else kept the OLD record's value, not the new
        # candidate's.
        assert fields["legal_name"] == "ACME Ltda"
        assert fields["email"] == "contato@acme.com"

        case = session.get(DuplicateReviewCase, case_id)
        assert case is not None
        assert case.status == "partially_accepted"


def test_rejecting_a_duplicate_writes_no_new_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter5")
    approver_token = _login_approver(client, admin_token, "second-approver5")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "Fraudulent Rename Ltda", "email": None, "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    with get_session() as session:
        count_before = session.query(MasterRecord).count()

    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "reject_all", "notes": "Not a legitimate update"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "rejected"

    with get_session() as session:
        assert session.query(MasterRecord).count() == count_before
        case = session.get(DuplicateReviewCase, case_id)
        assert case is not None
        assert case.status == "rejected"


def test_normal_approve_endpoint_is_blocked_while_a_duplicate_case_is_pending(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter6")
    approver_token = _login_approver(client, admin_token, "second-approver6")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda", "email": "x@acme.com", "telephone": None, "address": None},
    )

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 409

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1  # only the original


def test_resolving_a_duplicate_for_own_submission_is_blocked_by_segregation_of_duties(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    approver_token = _login_approver(client, admin_token, "self-resolver")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        approver_token,
        {"legal_name": "ACME Ltda", "email": "y@acme.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    response = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 403

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1


def test_no_master_record_update_happens_without_the_resolve_step(monkeypatch) -> None:
    """A duplicate case sitting pending, untouched, must never silently
    become an update — reinforces that the only write path is resolve."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-submitter7")
    _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "Should Not Apply Ltda", "email": None, "telephone": None, "address": None},
    )

    with get_session() as session:
        record = session.get(MasterRecord, original_record_id)
        assert record is not None
        assert record.is_current is True
        fields = json.loads(record.fields_json)
        assert fields["legal_name"] == "ACME Ltda"
        assert session.query(MasterRecord).count() == 1
        assert session.query(ApprovalEvent).count() == 1  # only the original approval


def test_two_uploads_of_same_cnpj_before_either_approved_blocks_the_second_approval(monkeypatch) -> None:
    """Regression test: detect_supplier_duplicate only runs at upload time,
    so two candidates for the same CNPJ uploaded before either is approved
    would otherwise sail through approve_job independently, each creating
    its own 'current' MasterRecord for the same supplier."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_a = _login_submitter(client, admin_token, "race-submitter-a")
    submitter_b = _login_submitter(client, admin_token, "race-submitter-b")
    approver_token = _login_approver(client, admin_token, "race-approver")

    job_a = _upload_pending_review_job(
        client,
        monkeypatch,
        submitter_a,
        {"legal_name": "ACME Ltda", "email": "a@acme.com", "telephone": None, "address": None},
    )
    job_b = _upload_pending_review_job(
        client,
        monkeypatch,
        submitter_b,
        {"legal_name": "ACME Ltda", "email": "b@acme.com", "telephone": None, "address": None},
    )

    # Neither upload could see the other yet — no case exists for either.
    with get_session() as session:
        assert session.query(DuplicateReviewCase).count() == 0

    approve_a = client.post(f"/jobs/{job_a}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve_a.status_code == 200

    approve_b = client.post(f"/jobs/{job_b}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve_b.status_code == 409

    with get_session() as session:
        assert session.query(MasterRecord).filter_by(is_current=True).count() == 1
        case = session.query(DuplicateReviewCase).filter_by(extraction_job_id=job_b).first()
        assert case is not None
        assert case.status == "pending"


def test_resolving_a_stale_duplicate_case_is_blocked_not_corrupted(monkeypatch) -> None:
    """Regression test: two pending cases against the same matched record —
    resolving the second one after the first must not collide version
    numbers or silently discard the first resolution's data."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_a = _login_submitter(client, admin_token, "stale-submitter-a")
    submitter_b = _login_submitter(client, admin_token, "stale-submitter-b")
    approver_token = _login_approver(client, admin_token, "stale-approver")

    _, cnpj = _register_initial_supplier(client, monkeypatch, admin_token)

    job_a = _upload_pending_review_job(
        client,
        monkeypatch,
        submitter_a,
        {"legal_name": "ACME Ltda", "email": "updateA@acme.com", "telephone": None, "address": None},
        cnpj=cnpj,
    )
    job_b = _upload_pending_review_job(
        client,
        monkeypatch,
        submitter_b,
        {"legal_name": "ACME Ltda", "email": "updateB@acme.com", "telephone": None, "address": None},
        cnpj=cnpj,
    )

    result_a = client.get(f"/jobs/{job_a}/result", headers={"Authorization": f"Bearer {submitter_a}"})
    result_b = client.get(f"/jobs/{job_b}/result", headers={"Authorization": f"Bearer {submitter_b}"})
    case_a_id = result_a.json()["duplicate_review_case_id"]
    case_b_id = result_b.json()["duplicate_review_case_id"]
    assert case_a_id is not None and case_b_id is not None
    assert case_a_id != case_b_id

    resolve_a = client.post(
        f"/duplicates/{case_a_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve_a.status_code == 200

    resolve_b = client.post(
        f"/duplicates/{case_b_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve_b.status_code == 409

    normalized_cnpj = "".join(ch for ch in cnpj if ch.isdigit())  # record_key stores the normalized form
    with get_session() as session:
        current_records = (
            session.query(MasterRecord).filter_by(record_key=normalized_cnpj, is_current=True).all()
        )
        assert len(current_records) == 1  # never two current versions

        all_versions = [
            r.version for r in session.query(MasterRecord).filter_by(record_key=normalized_cnpj).all()
        ]
        assert len(all_versions) == len(set(all_versions))  # no colliding version numbers

        case_b = session.get(DuplicateReviewCase, case_b_id)
        assert case_b is not None
        assert case_b.status == "pending"  # left pending for manual follow-up, not corrupted


def test_partial_accepted_fields_only_lists_fields_actually_applied(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "partial-noop-submitter")
    approver_token = _login_approver(client, admin_token, "partial-noop-approver")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        new_submitter_token,
        {"legal_name": "ACME Ltda", "email": None, "telephone": None, "address": None},  # no new email extracted
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    case_id = result.json()["duplicate_review_case_id"]

    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "partial", "accepted_fields": ["email"]},  # requested, but nothing to apply
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200

    with get_session() as session:
        case = session.get(DuplicateReviewCase, case_id)
        assert case is not None
        assert case.accepted_fields_json is not None
        assert json.loads(case.accepted_fields_json) == []  # nothing was actually applied


def test_self_approval_on_duplicate_flagged_job_gets_403_not_409(monkeypatch) -> None:
    """Segregation-of-duties must be checked before the duplicate-pending
    check, so a blocked self-approver always gets a plain 403 rather than a
    409 that incidentally reveals duplicate-detection state."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    approver_token = _login_approver(client, admin_token, "self-approve-dup")
    job_id = _upload_pending_review_job(
        client,
        monkeypatch,
        approver_token,
        {"legal_name": "ACME Ltda", "email": "z@acme.com", "telephone": None, "address": None},
    )
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    assert result.json()["duplicate_review_case_id"] is not None

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 403


def test_reupload_of_duplicate_flagged_content_surfaces_the_case_id(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_supplier(client, monkeypatch, admin_token)

    submitter_token = _login_submitter(client, admin_token, "reupload-dup-submitter")
    monkeypatch.setattr(
        llm_extraction,
        "OllamaExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": "dup@acme.com", "telephone": None, "address": None}
        ),
    )
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86")
    first = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert first.json()["duplicate_review_case_id"] is not None

    second = client.post(
        "/documents",
        files={"file": ("invoice2.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert second.status_code == 201
    assert second.json()["duplicate_review_case_id"] == first.json()["duplicate_review_case_id"]
