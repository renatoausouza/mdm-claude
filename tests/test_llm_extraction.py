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
