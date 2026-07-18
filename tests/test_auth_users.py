from fastapi.testclient import TestClient

from mdm.db import User, get_session
from mdm.main import app


def test_create_first_user_becomes_admin_with_no_auth_required() -> None:
    client = TestClient(app)
    response = client.post(
        "/users",
        json={"username": "alice", "password": "correct horse battery staple", "role": "submitter"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["role"] == "admin"  # bootstrap: first user is always admin


def test_password_is_never_stored_in_plaintext() -> None:
    client = TestClient(app)
    client.post(
        "/users",
        json={"username": "bob", "password": "hunter2", "role": "submitter"},
    )
    with get_session() as session:
        user = session.query(User).filter_by(username="bob").first()
        assert user is not None
        assert user.password_hash != "hunter2"
        assert "hunter2" not in user.password_hash


def test_duplicate_username_is_rejected() -> None:
    client = TestClient(app)
    # First "carol" becomes the bootstrap admin; use her token for the second
    # attempt, since user creation past the first requires admin auth.
    client.post("/users", json={"username": "carol", "password": "password123", "role": "submitter"})
    login = client.post("/auth/login", json={"username": "carol", "password": "password123"})
    token = login.json()["token"]

    response = client.post(
        "/users",
        json={"username": "carol", "password": "different", "role": "submitter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
