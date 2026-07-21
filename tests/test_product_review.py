import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import llm_extraction
from mdm.db import MasterRecord, get_session
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


def _upload_product_job(
    client: TestClient, monkeypatch, headers: dict[str, str], fields: dict, invoice_text: str | None = None
) -> str:
    monkeypatch.setattr(llm_extraction, "OciGenAiExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes(invoice_text or "Item: Parafuso Sextavado M8, SKU PSX-M8-001")
    response = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "product"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
    job_id: str = response.json()["id"]
    return job_id


_FULL_PRODUCT = {
    "name": "Parafuso Sextavado M8",
    "sku": "PSX-M8-001",
    "ncm": "7318.15.00",
    "description": "Parafuso sextavado em aco inox",
    "price": "12.50",
    "quantity": "100",
    "discount": "5%",
}


def test_uploading_with_product_domain_extracts_master_and_transactional_fields(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "product-approver1")

    job_id = _upload_product_job(client, monkeypatch, {"Authorization": f"Bearer {approver_token}"}, _FULL_PRODUCT)

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    body = result.json()
    assert body["domain"] == "product"
    assert body["result"]["name"]["value"] == "Parafuso Sextavado M8"
    assert body["result"]["sku"]["value"] == "PSX-M8-001"
    # Transactional evidence IS present in the extraction result...
    assert body["result"]["price"]["value"] == "12.50"
    assert body["result"]["quantity"]["value"] == "100"


def test_self_approval_is_allowed_for_product_domain(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "product-approver2")

    job_id = _upload_product_job(client, monkeypatch, {"Authorization": f"Bearer {approver_token}"}, _FULL_PRODUCT)

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 200
    assert response.json()["master_record_id"] is not None


def test_price_quantity_discount_are_never_stored_on_the_master_record(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "product-approver3")

    job_id = _upload_product_job(client, monkeypatch, {"Authorization": f"Bearer {approver_token}"}, _FULL_PRODUCT)
    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    master_record_id = response.json()["master_record_id"]

    with get_session() as session:
        record = session.get(MasterRecord, master_record_id)
        assert record is not None
        assert record.domain == "product"
        fields = json.loads(record.fields_json)
        assert set(fields.keys()) <= {"name", "sku", "ncm", "description"}
        assert "price" not in fields
        assert "quantity" not in fields
        assert "discount" not in fields
        assert fields["name"] == "Parafuso Sextavado M8"
        assert fields["sku"] == "PSX-M8-001"


def test_missing_sku_does_not_block_scoring_or_approval(monkeypatch) -> None:
    # FR-11: SKU absence routes to manual linking during review, but does
    # NOT force Low reliability the way a missing required field would.
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "product-approver4")

    fields = dict(_FULL_PRODUCT)
    fields["sku"] = None
    job_id = _upload_product_job(client, monkeypatch, {"Authorization": f"Bearer {approver_token}"}, fields)

    result = client.get(f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    scoring = result.json()["scoring"]
    assert scoring["missing_required_fields"] == []  # name is the only required field

    response = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert response.status_code == 200


def test_reuploading_an_invoice_with_a_different_price_creates_a_duplicate_case_matched_by_sku_only(
    monkeypatch,
) -> None:
    """AC: price must never be part of the match/diff. With #11's SKU-based
    detection now wired up, re-uploading the same SKU at a different price
    DOES create a duplicate case (matched purely on SKU) — but price must
    never appear in the match key or the side-by-side comparison."""
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "product-approver5")

    job_id = _upload_product_job(client, monkeypatch, {"Authorization": f"Bearer {approver_token}"}, _FULL_PRODUCT)
    client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})

    different_price = dict(_FULL_PRODUCT)
    different_price["price"] = "999.99"
    # A genuinely different document (distinct content_hash) — otherwise
    # content-hash idempotency (#2) would just return the first job again,
    # and this test would pass for the wrong reason.
    second_job_id = _upload_product_job(
        client,
        monkeypatch,
        {"Authorization": f"Bearer {approver_token}"},
        different_price,
        invoice_text="Item: Parafuso Sextavado M8, SKU PSX-M8-001 -- second invoice, different price",
    )
    assert second_job_id != job_id  # confirms this is genuinely a second document

    result = client.get(f"/jobs/{second_job_id}/result", headers={"Authorization": f"Bearer {approver_token}"})
    case_id = result.json()["duplicate_review_case_id"]
    assert case_id is not None  # matched by SKU, despite the price difference
    assert result.json()["result"].get("price") is not None  # price is still extracted as evidence...

    case = client.get(f"/duplicates/{case_id}", headers={"Authorization": f"Bearer {approver_token}"})
    field_names = {c["field"] for c in case.json()["comparisons"]}
    assert "price" not in field_names  # ...but never part of the match/diff (D10)
