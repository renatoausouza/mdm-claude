import httpx
import pytest
from fastapi.testclient import TestClient

from mdm import config
from mdm.main import app, get_ollama_client
from mdm.ollama_client import OllamaClient


def _ollama_reachable() -> bool:
    try:
        httpx.get(f"{config.get_ollama_base_url()}/api/tags", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_reachable(), reason="no local Ollama server reachable")
def test_ready_returns_200_when_ollama_responds() -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200


class BrokenOllamaClient(OllamaClient):
    def check(self) -> bool:
        return False


@pytest.fixture
def broken_ollama_override():
    app.dependency_overrides[get_ollama_client] = lambda: BrokenOllamaClient()
    yield
    app.dependency_overrides.clear()


def test_ready_returns_503_when_ollama_unavailable(broken_ollama_override: None) -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
