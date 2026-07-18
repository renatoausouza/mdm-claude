from fastapi.testclient import TestClient

from mdm.main import app


def _create_user(client: TestClient, username: str, password: str, role: str = "submitter") -> None:
    response = client.post("/users", json={"username": username, "password": password, "role": role})
    assert response.status_code == 201


def test_login_with_correct_credentials_succeeds() -> None:
    client = TestClient(app)
    _create_user(client, "dave", "correct-password")

    response = client.post("/auth/login", json={"username": "dave", "password": "correct-password"})
    assert response.status_code == 200
    assert "token" in response.json()


def test_login_with_wrong_password_fails() -> None:
    client = TestClient(app)
    _create_user(client, "erin", "correct-password")

    response = client.post("/auth/login", json={"username": "erin", "password": "wrong-password"})
    assert response.status_code == 401


def test_account_locks_out_after_repeated_failed_attempts() -> None:
    client = TestClient(app)
    _create_user(client, "frank", "correct-password")

    for _ in range(5):
        client.post("/auth/login", json={"username": "frank", "password": "wrong-password"})

    # Even the CORRECT password should now be rejected — account is locked.
    # (401, not a distinct locked-out status: a different status code would
    # itself reveal that this username exists and is locked.)
    response = client.post("/auth/login", json={"username": "frank", "password": "correct-password"})
    assert response.status_code == 401
