from fastapi.testclient import TestClient

from mdm.main import app


def test_health_returns_200() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
