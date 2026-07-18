from fastapi.testclient import TestClient

from mdm.main import app


def test_second_user_creation_requires_admin_auth() -> None:
    client = TestClient(app)
    client.post("/users", json={"username": "admin1", "password": "admin-password", "role": "admin"})

    response = client.post(
        "/users", json={"username": "someone", "password": "password123", "role": "submitter"}
    )
    assert response.status_code == 401


def test_admin_can_create_additional_users() -> None:
    client = TestClient(app)
    client.post("/users", json={"username": "admin2", "password": "admin-password", "role": "admin"})
    login = client.post("/auth/login", json={"username": "admin2", "password": "admin-password"})
    token = login.json()["token"]

    response = client.post(
        "/users",
        json={"username": "newperson", "password": "password123", "role": "submitter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "submitter"


def test_non_admin_cannot_create_users() -> None:
    client = TestClient(app)
    client.post("/users", json={"username": "admin3", "password": "admin-password", "role": "admin"})
    admin_login = client.post("/auth/login", json={"username": "admin3", "password": "admin-password"})
    admin_token = admin_login.json()["token"]
    client.post(
        "/users",
        json={"username": "regular", "password": "regular-password", "role": "submitter"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    login = client.post("/auth/login", json={"username": "regular", "password": "regular-password"})
    token = login.json()["token"]

    response = client.post(
        "/users",
        json={"username": "another", "password": "password123", "role": "submitter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
