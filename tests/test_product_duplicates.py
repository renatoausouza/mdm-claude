"""#11: Product duplicate detection — SKU exact match only, replicating
#7/#9's pattern (see tests/test_duplicates.py, tests/test_client_duplicates.py).
A no-SKU candidate must never auto-match (no NCM+name fallback, no fuzzy
matching, ever) — instead a reviewer uses manual search + link-duplicate to
associate it with an existing record, or just approves it as new."""

import json
import threading
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import DuplicateReviewCase, MasterRecord, get_session
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


def _upload_product_job(client: TestClient, monkeypatch, token: str, fields: dict, invoice_text: str) -> str:
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text)
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "product"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    job_id: str = response.json()["id"]
    return job_id


_ORIGINAL_PRODUCT = {
    "name": "Parafuso Sextavado M8",
    "sku": "PSX-M8-001",
    "ncm": "7318.15.00",
    "description": "Parafuso sextavado em aco inox",
    "price": "12.50",
    "quantity": "100",
    "discount": None,
}


def _register_initial_product(client, monkeypatch, admin_token) -> tuple[str, str]:
    submitter_token = _login_submitter(client, admin_token, "original-product-submitter")
    approver_token = _login_approver(client, admin_token, "original-product-approver")

    job_id = _upload_product_job(
        client, monkeypatch, submitter_token, _ORIGINAL_PRODUCT, "Item: Parafuso Sextavado M8, SKU PSX-M8-001"
    )
    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200
    return approve.json()["master_record_id"], "PSX-M8-001"


def test_matching_sku_creates_duplicate_case_instead_of_second_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, sku = _register_initial_product(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "second-product-submitter")
    fields = dict(_ORIGINAL_PRODUCT)
    fields["price"] = "999.99"  # different price, same SKU
    job_id = _upload_product_job(
        client,
        monkeypatch,
        new_submitter_token,
        fields,
        "Item: Parafuso Sextavado M8, SKU PSX-M8-001 -- reorder, different price",
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    body = result.json()
    assert body["duplicate_review_case_id"] is not None

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1
        case = session.get(DuplicateReviewCase, body["duplicate_review_case_id"])
        assert case is not None
        assert case.matched_master_record_id == original_record_id
        assert case.match_key == sku


def test_no_sku_candidate_never_auto_matches_even_with_identical_name_and_ncm(monkeypatch) -> None:
    """FR-11: no NCM+name fallback key, no fuzzy/similarity matching, ever."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_product(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "no-sku-submitter")
    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None  # identical name/ncm/description, but no SKU
    job_id = _upload_product_job(
        client,
        monkeypatch,
        new_submitter_token,
        fields,
        "Item: Parafuso Sextavado M8 -- invoice without an SKU printed",
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    assert result.json()["duplicate_review_case_id"] is None

    with get_session() as session:
        assert session.query(DuplicateReviewCase).count() == 0


def test_manual_search_finds_existing_products_by_name(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_product(client, monkeypatch, admin_token)
    approver_token = _login_approver(client, admin_token, "search-approver")

    response = client.get(
        "/master-records/search",
        params={"domain": "product", "q": "Sextavado"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert any(r["id"] == original_record_id for r in results)

    no_match = client.get(
        "/master-records/search",
        params={"domain": "product", "q": "Nonexistent Widget"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert no_match.json()["results"] == []


def test_manual_link_creates_a_resolvable_duplicate_case_for_a_no_sku_candidate(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_product(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "no-sku-link-submitter")
    approver_token = _login_approver(client, admin_token, "no-sku-link-approver")
    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None
    fields["price"] = "13.00"
    job_id = _upload_product_job(
        client, monkeypatch, new_submitter_token, fields, "Item: Parafuso Sextavado M8 -- no SKU on this invoice"
    )

    # No auto-match — reviewer finds it manually and links it.
    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {new_submitter_token}"})
    assert result.json()["duplicate_review_case_id"] is None

    link = client.post(
        f"/jobs/{job_id}/link-duplicate",
        json={"master_record_id": original_record_id, "notes": "Same product, invoice just omitted the SKU"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert link.status_code == 201
    case_id = link.json()["case_id"]
    assert link.json()["status"] == "pending"

    # From here it's the exact same accept/reject/partial flow as an
    # auto-detected case.
    resolve = client.post(
        f"/duplicates/{case_id}/resolve",
        json={"decision": "accept_all"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert resolve.status_code == 200
    new_record_id = resolve.json()["master_record_id"]

    with get_session() as session:
        old_record = session.get(MasterRecord, original_record_id)
        new_record = session.get(MasterRecord, new_record_id)
        assert old_record is not None and new_record is not None
        assert old_record.is_current is False
        assert new_record.version == old_record.version + 1
        fields_json = json.loads(new_record.fields_json)
        assert "price" not in fields_json  # transactional evidence, never a master field


def test_link_duplicate_rejects_a_different_domains_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "cross-domain-approver")
    submitter_token = _login_submitter(client, admin_token, "cross-domain-submitter")

    # Register a supplier record, then try to link a product candidate to it.
    monkeypatch.setattr(
        llm_extraction,
        "OciGenAiExtractionClient",
        lambda: FakeExtractionClient(
            {"legal_name": "ACME Ltda", "email": None, "telephone": None, "address": None}
        ),
    )
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86")
    supplier_upload = client.post(
        "/documents",
        files={"file": ("supplier.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "supplier"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    supplier_job_id = supplier_upload.json()["id"]
    supplier_approve = client.post(
        f"/jobs/{supplier_job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"}
    )
    supplier_record_id = supplier_approve.json()["master_record_id"]

    product_job_id = _upload_product_job(
        client, monkeypatch, submitter_token, _ORIGINAL_PRODUCT, "Item: Parafuso Sextavado M8, SKU PSX-M8-001-b"
    )

    response = client.post(
        f"/jobs/{product_job_id}/link-duplicate",
        json={"master_record_id": supplier_record_id},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 400


def test_normal_approve_endpoint_is_blocked_while_a_product_duplicate_case_is_pending(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_product(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "blocked-product-submitter")
    approver_token = _login_approver(client, admin_token, "blocked-product-approver")
    job_id = _upload_product_job(
        client,
        monkeypatch,
        new_submitter_token,
        _ORIGINAL_PRODUCT,
        "Item: Parafuso Sextavado M8, SKU PSX-M8-001 -- reorder invoice",
    )

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 409

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1


def test_reviewer_can_assign_a_sku_when_approving_a_no_sku_candidate_as_new(monkeypatch) -> None:
    """AC: 'approve it as new (assigning a SKU during review if desired)'."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "assign-sku-submitter")
    approver_token = _login_approver(client, admin_token, "assign-sku-approver")

    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None
    fields["name"] = "Arruela Lisa M8"
    job_id = _upload_product_job(
        client, monkeypatch, submitter_token, fields, "Item: Arruela Lisa M8 -- no SKU printed on this invoice"
    )

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {submitter_token}"})
    assert result.json()["duplicate_review_case_id"] is None  # no SKU, so no auto-match at all

    response = client.post(
        f"/jobs/{job_id}/approve",
        json={"field_overrides": {"sku": "ARL-M8-NEW"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    master_record_id = response.json()["master_record_id"]

    with get_session() as session:
        record = session.get(MasterRecord, master_record_id)
        assert record is not None
        assert record.record_key == "ARL-M8-NEW"  # the assigned SKU seeds record_key too
        fields_json = json.loads(record.fields_json)
        assert fields_json["sku"] == "ARL-M8-NEW"


def test_assigning_a_sku_that_already_exists_routes_to_duplicate_review_not_a_second_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_product(client, monkeypatch, admin_token)

    new_submitter_token = _login_submitter(client, admin_token, "assign-existing-sku-submitter")
    approver_token = _login_approver(client, admin_token, "assign-existing-sku-approver")
    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None
    job_id = _upload_product_job(
        client, monkeypatch, new_submitter_token, fields, "Item: Parafuso Sextavado M8 -- no SKU, manually assigned"
    )

    response = client.post(
        f"/jobs/{job_id}/approve",
        # Manually (mis)assigning the ALREADY-REGISTERED SKU must still be
        # caught by duplicate detection, not silently create a second
        # "current" record for PSX-M8-001.
        json={"field_overrides": {"sku": "PSX-M8-001"}},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 409

    with get_session() as session:
        assert session.query(MasterRecord).count() == 1
        assert session.query(DuplicateReviewCase).count() == 1


def test_field_overrides_rejects_unknown_field_names(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "bad-override-submitter")
    approver_token = _login_approver(client, admin_token, "bad-override-approver")

    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None
    job_id = _upload_product_job(
        client, monkeypatch, submitter_token, fields, "Item: Parafuso Sextavado M8 -- bad override test"
    )

    response = client.post(
        f"/jobs/{job_id}/approve",
        json={"field_overrides": {"price": "999.99"}},  # not a master field for Product
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 422


def test_search_master_records_rejects_submitter(monkeypatch) -> None:
    """Approver and admin can both view (#17 widened this from
    approver-only — see tests/test_master_records.py); submitter still
    can't, same PII rationale as before."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    _register_initial_product(client, monkeypatch, admin_token)
    submitter_token = _login_submitter(client, admin_token, "search-submitter-no-access")

    response = client.get(
        "/master-records/search",
        params={"domain": "product", "q": ""},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 403


def test_concurrent_link_duplicate_calls_for_the_same_job_only_one_succeeds(monkeypatch) -> None:
    """Regression test: link_duplicate's pre-check (_reject_if_duplicate_pending)
    is read-then-write, not a lock — two concurrent link attempts for the
    same job must not both succeed (DuplicateReviewCase.extraction_job_id is
    unique); the loser must get a clean 409, not a raw 500."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    original_record_id, _ = _register_initial_product(client, monkeypatch, admin_token)

    submitter_token = _login_submitter(client, admin_token, "concurrent-link-submitter")
    approver_token = _login_approver(client, admin_token, "concurrent-link-approver")
    fields = dict(_ORIGINAL_PRODUCT)
    fields["sku"] = None
    job_id = _upload_product_job(
        client, monkeypatch, submitter_token, fields, "Item: Parafuso Sextavado M8 -- concurrent link test"
    )

    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def do_link() -> None:
        barrier.wait()
        response = client.post(
            f"/jobs/{job_id}/link-duplicate",
            json={"master_record_id": original_record_id},
            headers={"Authorization": f"Bearer {approver_token}"},
        )
        statuses.append(response.status_code)

    threads = [threading.Thread(target=do_link) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [201, 409]
    with get_session() as session:
        assert session.query(DuplicateReviewCase).filter_by(extraction_job_id=job_id).count() == 1
