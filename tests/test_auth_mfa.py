import time

import pyotp
from fastapi.testclient import TestClient

from mdm.main import app


def _totp_code_after(secret: str, seconds: int) -> str:
    """A TOTP code guaranteed distinct from the current one — used to
    simulate a later, still-valid code without actually waiting, since two
    pyotp.TOTP(secret).now() calls in quick succession can return the
    identical 30s code (which anti-replay protection correctly rejects)."""
    return pyotp.TOTP(secret).at(int(time.time()) + seconds)


def _bootstrap_admin(client: TestClient) -> str:
    # First user is always admin (bootstrap) — created so subsequent
    # approver creation isn't itself the first/bootstrap user. Returns the
    # admin's session token, since creating any further user requires it.
    client.post("/users", json={"username": "admin0", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "admin0", "password": "admin-password"})
    token: str = login.json()["token"]
    return token


def _create_approver(client: TestClient, username: str, password: str) -> None:
    admin_token = _bootstrap_admin(client)
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": "approver"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201


def test_approver_login_with_correct_password_requires_mfa_enrollment_first() -> None:
    client = TestClient(app)
    _create_approver(client, "grace", "correct-password")

    response = client.post("/auth/login", json={"username": "grace", "password": "correct-password"})
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_enrollment_required"] is True
    assert "token" in body  # limited enrollment-scoped token


def test_enrollment_flow_then_full_login_requires_totp_code() -> None:
    client = TestClient(app)
    _create_approver(client, "heidi", "correct-password")

    login_response = client.post("/auth/login", json={"username": "heidi", "password": "correct-password"})
    enrollment_token = login_response.json()["token"]

    enroll_response = client.post(
        "/auth/mfa/enroll", headers={"Authorization": f"Bearer {enrollment_token}"}
    )
    assert enroll_response.status_code == 200
    secret = enroll_response.json()["secret"]

    valid_code = pyotp.TOTP(secret).now()
    verify_response = client.post(
        "/auth/mfa/verify",
        json={"totp_code": valid_code},
        headers={"Authorization": f"Bearer {enrollment_token}"},
    )
    assert verify_response.status_code == 200

    # Now a normal login without a TOTP code must fail...
    no_code_response = client.post("/auth/login", json={"username": "heidi", "password": "correct-password"})
    assert no_code_response.status_code == 401

    # ...but with a valid current TOTP code it succeeds with a full session.
    fresh_code = _totp_code_after(secret, 30)
    full_login_response = client.post(
        "/auth/login",
        json={"username": "heidi", "password": "correct-password", "totp_code": fresh_code},
    )
    assert full_login_response.status_code == 200
    assert full_login_response.json()["mfa_enrollment_required"] is False


def test_full_session_cannot_be_used_to_reenroll_mfa() -> None:
    """Regression test: a stolen full session token must not be usable to
    silently re-provision MFA on an already-enrolled account — enrollment
    endpoints must require an actual mfa_enrollment-scoped session, not
    just any authenticated session."""
    client = TestClient(app)
    _create_approver(client, "judy", "correct-password")

    login_response = client.post("/auth/login", json={"username": "judy", "password": "correct-password"})
    enrollment_token = login_response.json()["token"]
    enroll_response = client.post(
        "/auth/mfa/enroll", headers={"Authorization": f"Bearer {enrollment_token}"}
    )
    secret = enroll_response.json()["secret"]
    valid_code = pyotp.TOTP(secret).now()
    client.post(
        "/auth/mfa/verify",
        json={"totp_code": valid_code},
        headers={"Authorization": f"Bearer {enrollment_token}"},
    )

    # judy is now enrolled; log in fully (password + TOTP).
    fresh_code = _totp_code_after(secret, 30)
    full_login = client.post(
        "/auth/login",
        json={"username": "judy", "password": "correct-password", "totp_code": fresh_code},
    )
    full_token = full_login.json()["token"]

    # A full session must NOT be able to re-enroll MFA.
    reenroll_response = client.post(
        "/auth/mfa/enroll", headers={"Authorization": f"Bearer {full_token}"}
    )
    assert reenroll_response.status_code == 403

    reverify_response = client.post(
        "/auth/mfa/verify",
        json={"totp_code": _totp_code_after(secret, 60)},
        headers={"Authorization": f"Bearer {full_token}"},
    )
    assert reverify_response.status_code == 403


def test_totp_code_cannot_be_replayed() -> None:
    client = TestClient(app)
    _create_approver(client, "karl", "correct-password")

    login_response = client.post("/auth/login", json={"username": "karl", "password": "correct-password"})
    enrollment_token = login_response.json()["token"]
    enroll_response = client.post(
        "/auth/mfa/enroll", headers={"Authorization": f"Bearer {enrollment_token}"}
    )
    secret = enroll_response.json()["secret"]
    code = pyotp.TOTP(secret).now()
    client.post(
        "/auth/mfa/verify",
        json={"totp_code": code},
        headers={"Authorization": f"Bearer {enrollment_token}"},
    )

    # Replaying the SAME code (the one just used to confirm enrollment)
    # against the login endpoint must be rejected, not accepted.
    replay_response = client.post(
        "/auth/login",
        json={"username": "karl", "password": "correct-password", "totp_code": code},
    )
    assert replay_response.status_code == 401


def test_non_approver_accounts_never_require_mfa() -> None:
    client = TestClient(app)
    admin_token = _bootstrap_admin(client)
    client.post(
        "/users",
        json={"username": "ivan", "password": "correct-password", "role": "submitter"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = client.post("/auth/login", json={"username": "ivan", "password": "correct-password"})
    assert response.status_code == 200
    assert response.json()["mfa_enrollment_required"] is False
