import json

import pytest

from mdm import config, llm_extraction
from mdm.llm_extraction import OciGenAiExtractionClient, extract_supplier_fields
from mdm.oci_genai_client import OciGenAiClient


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


def test_oci_genai_client_uses_the_configured_timeout(monkeypatch) -> None:
    # Regression test: nginx's /documents route is configured for up to
    # 300s (deploy/nginx-mdm.conf). The internal OCI Generative AI call
    # must stay configurable and long enough to use that budget, not
    # silently cut the request short with its own unrelated, shorter,
    # hardcoded timeout.
    monkeypatch.setenv("MDM_OCI_GENAI_EXTRACTION_TIMEOUT_SECONDS", "280")
    monkeypatch.setenv("MDM_OCI_GENAI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setenv("MDM_OCI_GENAI_REGION", "us-chicago-1")
    monkeypatch.setattr(llm_extraction, "load_oci_sdk_config", lambda: {})
    captured: dict = {}

    class FakeChatResponseData:
        class chat_response:  # noqa: N801 - mirrors the real oci SDK's response shape
            choices = [
                type("Choice", (), {"message": type("Message", (), {"content": [type("C", (), {"text": "{}"})()]})()})()
            ]

    class FakeApiResponse:
        data = FakeChatResponseData()

    class FakeInferenceClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def chat(self, chat_details: object) -> FakeApiResponse:
            return FakeApiResponse()

    monkeypatch.setattr(llm_extraction, "GenerativeAiInferenceClient", FakeInferenceClient)

    OciGenAiExtractionClient().generate_json("some prompt")

    assert captured["timeout"] == 280.0


def test_oci_genai_client_timeout_defaults_to_a_value_at_least_as_large_as_a_typical_request_budget() -> None:
    assert config.get_oci_genai_extraction_timeout_seconds() >= 60.0


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


@pytest.mark.skipif(
    not OciGenAiClient().check(), reason="no reachable/configured OCI Generative AI credentials"
)
def test_real_extraction_against_oci_genai() -> None:
    """The one genuine end-to-end check that the prompt/model/parsing
    actually work together against the real managed service, not just the
    surrounding logic."""
    document_text = (
        "Fornecedor: ACME Distribuidora Ltda\n"
        "CNPJ: 12.345.678/0001-99\n"
        "Email: contato@acme.com.br\n"
        "Telefone: (11) 98765-4321\n"
        "Endereco: Rua das Flores, 123, Sao Paulo, SP\n"
    )

    result = extract_supplier_fields(document_text, cnpj_anchor="12.345.678/0001-99", client=OciGenAiExtractionClient())

    assert result["legal_name"] is not None
    assert "acme" in result["legal_name"].value.lower()
    assert result["email"] is not None
    assert result["email"].value.lower() == "contato@acme.com.br"
