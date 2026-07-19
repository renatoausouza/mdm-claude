import json

import httpx
import pytest

from mdm import config
from mdm.llm_extraction import OllamaExtractionClient, extract_supplier_fields


class FakeClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def test_extracted_field_found_in_source_gets_high_confidence() -> None:
    document_text = "Fornecedor: ACME Ltda, contato@acme.com"
    fake = FakeClient({"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None})

    result = extract_supplier_fields(document_text, cnpj_anchor=None, client=fake)

    assert result["legal_name"] is not None
    assert result["legal_name"].value == "ACME Ltda"
    assert result["legal_name"].confidence == 0.9
    assert result["legal_name"].found_verbatim_in_source is True


def test_extracted_field_not_found_in_source_gets_low_confidence() -> None:
    document_text = "Some unrelated document text"
    fake = FakeClient({"legal_name": "Hallucinated Corp Ltda", "email": None, "telephone": None, "address": None})

    result = extract_supplier_fields(document_text, cnpj_anchor=None, client=fake)

    assert result["legal_name"] is not None
    assert result["legal_name"].confidence == 0.3
    assert result["legal_name"].found_verbatim_in_source is False


def test_ollama_client_uses_the_configured_timeout(monkeypatch) -> None:
    # Regression test: nginx's /documents route is configured for up to
    # 300s (deploy/nginx-mdm.conf, because CPU-only inference on this VM
    # was already observed running 50-90s on ordinary documents) but the
    # internal Ollama call had its own, unrelated, hardcoded 120s timeout
    # — self-limiting well below what nginx already tolerates. A longer,
    # denser real document (dense DANFE full text, ~1700+ tokens) can
    # legitimately take over 120s on this hardware, so the internal
    # timeout must be configurable and long enough to use nginx's budget,
    # not silently cut the request short first.
    monkeypatch.setenv("MDM_OLLAMA_EXTRACTION_TIMEOUT_SECONDS", "280")
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"response": "{}"}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    OllamaExtractionClient().generate_json("some prompt")

    assert captured["timeout"] == 280.0


def test_ollama_client_timeout_defaults_to_a_value_at_least_as_large_as_nginxs_budget() -> None:
    # nginx grants /documents up to 300s (deploy/nginx-mdm.conf); the
    # default here must leave that budget usable, not silently cap it back
    # down to something much smaller.
    assert config.get_ollama_extraction_timeout_seconds() >= 200.0


def test_missing_field_in_llm_response_is_none() -> None:
    fake = FakeClient({"legal_name": None, "email": None, "telephone": None, "address": None})

    result = extract_supplier_fields("some text", cnpj_anchor=None, client=fake)

    assert result["email"] is None


def test_malformed_json_response_does_not_crash() -> None:
    class BrokenClient:
        def generate_json(self, prompt: str) -> str:
            return "not valid json {{{"

    result = extract_supplier_fields("some text", cnpj_anchor=None, client=BrokenClient())

    assert all(v is None for v in result.values())


def test_nested_object_value_is_ignored_not_crashed_on() -> None:
    # Weaker models sometimes return nested objects instead of flat strings
    # (observed in practice with tinyllama) — must not crash, and such a
    # field is treated as not extracted rather than guessed at.
    fake = FakeClient({"legal_name": "ACME", "email": None, "telephone": {"area_code": "11"}, "address": None})

    result = extract_supplier_fields("ACME text", cnpj_anchor=None, client=fake)

    assert result["telephone"] is None


def test_numeric_value_is_coerced_to_string_not_dropped() -> None:
    # A weaker/different model can return a legitimate value as a JSON
    # number despite the prompt asking for a string (e.g. a phone number
    # as a bare int) — this should be coerced, not discarded like a
    # genuinely unusable nested object is.
    fake = FakeClient({"legal_name": None, "email": None, "telephone": 5511999999999, "address": None})

    result = extract_supplier_fields("call 5511999999999 now", cnpj_anchor=None, client=fake)

    assert result["telephone"] is not None
    assert result["telephone"].value == "5511999999999"
    assert result["telephone"].confidence == 0.9


def _ollama_reachable() -> bool:
    try:
        httpx.get(f"{config.get_ollama_base_url()}/api/tags", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_reachable(), reason="no local Ollama server reachable")
def test_real_extraction_against_local_ollama() -> None:
    """Slow (real model inference, ~20-50s on CPU-only hardware) — the one
    genuine end-to-end check that the prompt/model/parsing actually work
    together, not just the surrounding logic."""
    document_text = (
        "Fornecedor: ACME Distribuidora Ltda\n"
        "CNPJ: 12.345.678/0001-99\n"
        "Email: contato@acme.com.br\n"
        "Telefone: (11) 98765-4321\n"
        "Endereco: Rua das Flores, 123, Sao Paulo, SP\n"
    )

    result = extract_supplier_fields(document_text, cnpj_anchor="12.345.678/0001-99", client=OllamaExtractionClient())

    assert result["legal_name"] is not None
    assert "acme" in result["legal_name"].value.lower()
    assert result["email"] is not None
    assert result["email"].value.lower() == "contato@acme.com.br"
