import json

import fitz

from mdm import llm_extraction
from mdm.client_extraction import ClientCandidateResult, run_client_extraction, score_client


class FakeExtractionClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_extracts_client_with_cpf_and_role_evidence() -> None:
    fake = FakeExtractionClient(
        {"name": "Joao Silva", "email": "joao@example.com", "telephone": None, "address": None}
    )
    pdf_bytes = _make_pdf_bytes("Destinatario CPF: 111.444.777-35\nEmail: joao@example.com")

    result = run_client_extraction(pdf_bytes, llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "111.444.777-35"
    assert result.tax_id.normalized_value == "11144477735"
    assert result.tax_id.provenance.source == "regex"
    assert result.name is not None
    assert result.name.value == "Joao Silva"
    assert result.name.provenance.source == "llm"


def test_extracts_client_with_cnpj() -> None:
    fake = FakeExtractionClient(
        {"name": "ACME Compras Ltda", "email": None, "telephone": None, "address": None}
    )
    pdf_bytes = _make_pdf_bytes("Cliente CNPJ: 11.223.344/0001-86")

    result = run_client_extraction(pdf_bytes, llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "11.223.344/0001-86"
    assert result.tax_id.normalized_value == "11223344000186"


def test_no_client_role_found_leaves_tax_id_none() -> None:
    fake = FakeExtractionClient({"name": None, "email": None, "telephone": None, "address": None})
    pdf_bytes = _make_pdf_bytes("Fornecedor CNPJ: 11.223.344/0001-86")  # only a supplier here

    result = run_client_extraction(pdf_bytes, llm_client=fake)

    assert result.tax_id is None


def test_valid_tax_id_under_a_dados_do_destinatario_header_is_extracted() -> None:
    # Regression test for the real bug report: a genuinely valid CNPJ
    # under a "Dados do Destinatário" section header (standard NFe/DANFE
    # phrasing) must populate tax_id, not silently end up None because the
    # header wasn't recognized as a role label.
    fake = FakeExtractionClient({"name": "Agencia Focus", "email": None, "telephone": None, "address": None})
    pdf_bytes = _make_pdf_bytes("Dados do Destinatario\nRazao Social\nCNPJ/CPF: 22.333.444/0001-81")

    result = run_client_extraction(pdf_bytes, llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "22.333.444/0001-81"
    assert result.rejected_tax_ids == []


def test_checksum_invalid_client_tax_id_is_reported_as_rejected_not_silently_missing() -> None:
    fake = FakeExtractionClient({"name": "Agencia de Marketing Digital Focus", "email": None, "telephone": None, "address": None})
    pdf_bytes = _make_pdf_bytes("Destinatario CNPJ/CPF: 22.333.444/0001-55")

    result = run_client_extraction(pdf_bytes, llm_client=fake)

    assert result.tax_id is None
    assert result.parties == []
    assert len(result.rejected_tax_ids) == 1
    assert result.rejected_tax_ids[0].value == "22.333.444/0001-55"
    assert result.rejected_tax_ids[0].kind == "cnpj"
    assert result.rejected_tax_ids[0].role == "client"


def test_score_client_requires_name_and_tax_id() -> None:
    result = ClientCandidateResult(name=None, tax_id=None)

    scoring = score_client(result)

    assert scoring.reliability == "Low"
    assert "name" in scoring.missing_required_fields
    assert "tax_id" in scoring.missing_required_fields


def test_score_client_excellent_when_complete_and_valid(monkeypatch) -> None:
    from mdm.extraction_schema import FieldValue, Provenance

    result = ClientCandidateResult(
        tax_id=FieldValue(value="111.444.777-35", confidence=0.95, provenance=Provenance(source="regex")),
        name=FieldValue(value="Joao Silva", confidence=0.9, provenance=Provenance(source="llm")),
        email=FieldValue(value="joao@example.com", confidence=0.9, provenance=Provenance(source="llm")),
        telephone=FieldValue(value="11987654321", confidence=0.9, provenance=Provenance(source="llm")),
        address=FieldValue(value="Rua A, 123", confidence=0.9, provenance=Provenance(source="llm")),
    )

    scoring = score_client(result)

    assert scoring.reliability == "Excellent"
    assert scoring.requires_review is False
