import json

import fitz

from mdm.supplier_extraction import run_supplier_extraction


class FakeClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_supplier_cnpj_comes_from_regex_with_role_tagging() -> None:
    pdf_bytes = _make_pdf("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")
    fake = FakeClient({"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is not None
    assert result.cnpj.value == "11.223.344/0001-86"
    assert result.cnpj.normalized_value == "11223344000186"
    assert result.cnpj.provenance.source == "regex"
    assert result.cnpj.provenance.page == 1
    assert result.cnpj.provenance.bbox is not None


def test_llm_fields_present_with_confidence_and_provenance() -> None:
    pdf_bytes = _make_pdf("Fornecedor CNPJ: 11.223.344/0001-86\nEmail: contato@acme.com")
    fake = FakeClient({"legal_name": "ACME Ltda", "email": "contato@acme.com", "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.legal_name is not None
    assert result.legal_name.value == "ACME Ltda"
    assert result.legal_name.provenance.source == "llm"
    assert result.telephone is None


def test_all_parties_retained_including_non_supplier_roles() -> None:
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.111.111/0001-91\n"
        "Destinatario CNPJ: 22.222.222/0001-91\n"
        "Transportador CNPJ: 33.333.333/0001-91"
    )
    fake = FakeClient({"legal_name": None, "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert len(result.parties) == 3
    roles = {p.role for p in result.parties}
    assert roles == {"supplier", "client", "transporter"}


def test_no_role_labels_means_cnpj_is_none_and_party_is_unknown() -> None:
    pdf_bytes = _make_pdf("Random text 11.223.344/0001-86 more text")
    fake = FakeClient({"legal_name": None, "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is None
    assert len(result.parties) == 1
    assert result.parties[0].role == "unknown"
