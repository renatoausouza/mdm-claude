"""#21: chat query interface — the LLM only ever proposes a constrained,
whitelisted structured filter ({domain, contains, limit}); it never sees
a live database connection, never generates SQL, and never sees query
results (one LLM call per question, not two — see mdm/chat_query.py's
own docstring). Every proposed value is validated against an explicit
allowlist before anything executes; anything invalid means "no filter
produced," never a best-effort guess."""

import json
import time

import fitz
import pyotp
from fastapi.testclient import TestClient

from mdm import chat_query, llm_extraction
from mdm.chat_query import propose_query_filter
from mdm.main import app


class FakeChatClient:
    def __init__(self, response_json: object) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


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


# ---- propose_query_filter: pure-function validation seam ----


def test_propose_query_filter_accepts_a_valid_proposal() -> None:
    fake = FakeChatClient({"domain": "client", "contains": "Minas Gerais", "limit": 5})
    result = propose_query_filter("show me 5 clients based in Minas Gerais", client=fake)
    assert result is not None
    assert result.domain == "client"
    assert result.contains == "Minas Gerais"
    assert result.limit == 5


def test_propose_query_filter_rejects_unknown_domain() -> None:
    fake = FakeChatClient({"domain": "employee", "contains": "x", "limit": 5})
    assert propose_query_filter("anything", client=fake) is None


def test_propose_query_filter_rejects_empty_contains() -> None:
    fake = FakeChatClient({"domain": "client", "contains": "", "limit": 5})
    assert propose_query_filter("anything", client=fake) is None


def test_propose_query_filter_rejects_non_dict_output() -> None:
    fake = FakeChatClient(["not", "a", "dict"])
    assert propose_query_filter("anything", client=fake) is None


def test_propose_query_filter_rejects_malformed_json() -> None:
    class BrokenClient:
        def generate_json(self, prompt: str) -> str:
            return "not valid json{{{"

    assert propose_query_filter("anything", client=BrokenClient()) is None


def test_propose_query_filter_defaults_and_caps_limit() -> None:
    fake = FakeChatClient({"domain": "client", "contains": "x", "limit": 999})
    result = propose_query_filter("anything", client=fake)
    assert result is not None
    assert result.limit == chat_query.MAX_LIMIT

    fake_no_limit = FakeChatClient({"domain": "client", "contains": "x", "limit": None})
    result2 = propose_query_filter("anything", client=fake_no_limit)
    assert result2 is not None
    assert result2.limit > 0


# ---- POST /chat/query: integration seam ----


def test_chat_query_returns_matching_records(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "chat-submitter")
    approver_token = _login_approver(client, admin_token, "chat-approver")

    fields = {
        "tax_id": None,
        "name": "Cliente Minas",
        "email": "cliente@example.com",
        "telephone": None,
        "address": "Rua X, Belo Horizonte, Minas Gerais",
    }
    monkeypatch.setattr(llm_extraction, "OllamaExtractionClient", lambda: FakeExtractionClient(fields))
    pdf_bytes = _make_pdf_bytes("Destinatario: Cliente Minas\nDestinatario CPF: 111.444.777-35")
    upload = client.post(
        "/documents",
        files={"file": ("invoice.pdf", pdf_bytes, "application/pdf")},
        data={"domain": "client"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    job_id = next(j["id"] for j in upload.json()["all_jobs"] if j["domain"] == "client")
    approve = client.post(f"/jobs/{job_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve.status_code == 200

    monkeypatch.setattr(
        chat_query,
        "OllamaExtractionClient",
        lambda: FakeChatClient({"domain": "client", "contains": "Minas Gerais", "limit": 5}),
    )

    response = client.post(
        "/chat/query",
        json={"question": "show me clients based in Minas Gerais"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["understood"] is True
    assert len(body["results"]) == 1
    assert body["results"][0]["fields"]["name"] == "Cliente Minas"


def test_chat_query_reports_not_understood_without_executing_anything(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    approver_token = _login_approver(client, admin_token, "chat-garbage-approver")

    monkeypatch.setattr(
        chat_query, "OllamaExtractionClient", lambda: FakeChatClient({"domain": "not-a-real-domain"})
    )

    response = client.post(
        "/chat/query",
        json={"question": "gibberish question"},
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["understood"] is False
    assert body["results"] == []


def test_chat_query_rejects_submitter(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    submitter_token = _login_submitter(client, admin_token, "chat-rejected-submitter")

    response = client.post(
        "/chat/query",
        json={"question": "anything"},
        headers={"Authorization": f"Bearer {submitter_token}"},
    )
    assert response.status_code == 403


def test_chat_query_allows_admin(monkeypatch) -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    monkeypatch.setattr(
        chat_query, "OllamaExtractionClient", lambda: FakeChatClient({"domain": "client", "contains": "x", "limit": 5})
    )

    response = client.post(
        "/chat/query",
        json={"question": "anything"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
