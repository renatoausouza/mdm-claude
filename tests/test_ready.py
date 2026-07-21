import pytest
from fastapi.testclient import TestClient

from mdm.main import app, get_oci_genai_client
from mdm.oci_genai_client import OciGenAiClient


def _oci_genai_reachable() -> bool:
    return OciGenAiClient().check()


@pytest.mark.skipif(not _oci_genai_reachable(), reason="no reachable/configured OCI Generative AI credentials")
def test_ready_returns_200_when_oci_genai_responds() -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200


class BrokenOciGenAiClient(OciGenAiClient):
    def check(self) -> bool:
        return False


@pytest.fixture
def broken_oci_genai_override():
    app.dependency_overrides[get_oci_genai_client] = lambda: BrokenOciGenAiClient()
    yield
    app.dependency_overrides.clear()


def test_ready_returns_503_when_oci_genai_unavailable(broken_oci_genai_override: None) -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
