from fastapi.testclient import TestClient

from mdm.main import app


def test_logout_invalidates_the_session_token() -> None:
    client = TestClient(app)
    client.post("/users", json={"username": "liam", "password": "correct-password", "role": "submitter"})
    login = client.post("/auth/login", json={"username": "liam", "password": "correct-password"})
    token = login.json()["token"]

    logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 200

    # The same token must no longer work for an authenticated action.
    second_user_response = client.post(
        "/users",
        json={"username": "someone-else", "password": "password123", "role": "submitter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_user_response.status_code == 401
