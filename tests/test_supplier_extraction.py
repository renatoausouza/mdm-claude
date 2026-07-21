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


def test_a_cpf_tagged_supplier_does_not_populate_the_cnpj_field() -> None:
    # Regression test: role_tagging accepts CPF too (needed for Client, #8),
    # but Supplier's "cnpj" field and validator (is_valid_cnpj) are
    # CNPJ-specific — a CPF tagged "supplier" (e.g. a sole proprietor) must
    # not silently populate it with a value that isn't actually a CNPJ.
    pdf_bytes = _make_pdf("Fornecedor CPF: 111.444.777-35")
    fake = FakeClient({"legal_name": "Joao MEI", "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is None
    assert len(result.parties) == 1
    assert result.parties[0].role == "supplier"  # still visible to the reviewer
    assert result.parties[0].tax_id.value == "111.444.777-35"


def test_no_role_labels_falls_back_to_positional_supplier() -> None:
    # Superseded by #16 (amends D3): the only tax ID on the page, with no
    # label anywhere, is the "topmost unlabeled candidate" by definition —
    # it now populates cnpj via the positional fallback, clearly marked as
    # inferred rather than evidenced.
    pdf_bytes = _make_pdf("Random text 11.223.344/0001-86 more text")
    fake = FakeClient({"legal_name": None, "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is not None
    assert result.cnpj.value == "11.223.344/0001-86"
    assert len(result.parties) == 1
    assert result.parties[0].role == "supplier"
    assert result.parties[0].role_evidence is not None
    assert result.parties[0].role_evidence.inferred is True


def test_valid_cnpj_under_a_dados_do_emitente_header_is_extracted() -> None:
    # Regression test for the real bug report: a genuinely valid CNPJ
    # under a "Dados do Emitente" section header (standard NFe/DANFE
    # phrasing) must populate cnpj, not silently end up None because the
    # header wasn't recognized as a role label.
    pdf_bytes = _make_pdf("Dados do Emitente\nRazao Social\nCNPJ: 11.223.344/0001-86")
    fake = FakeClient({"legal_name": "ACME Ltda", "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is not None
    assert result.cnpj.value == "11.223.344/0001-86"
    assert result.rejected_tax_ids == []


def test_checksum_invalid_supplier_cnpj_is_reported_as_rejected_not_silently_missing() -> None:
    # The bug report this guards against: a reviewer sees cnpj=None and
    # assumes extraction just missed it, when really a CNPJ-shaped value
    # WAS found right next to "Fornecedor" but failed check-digit
    # validation — a materially different, and more actionable, situation.
    pdf_bytes = _make_pdf("Fornecedor CNPJ: 99.888.777/0001-66")
    fake = FakeClient({"legal_name": "Suprimentos Office Papelaria EIRELI", "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is None
    assert result.parties == []
    assert len(result.rejected_tax_ids) == 1
    assert result.rejected_tax_ids[0].value == "99.888.777/0001-66"
    assert result.rejected_tax_ids[0].kind == "cnpj"
    assert result.rejected_tax_ids[0].role == "supplier"
    assert result.rejected_tax_ids[0].role_evidence is not None
    assert result.rejected_tax_ids[0].role_evidence.inferred is False


def test_valid_and_rejected_cnpj_on_the_same_document_are_kept_separate() -> None:
    # A page can genuinely have both: one party with a real, valid CNPJ,
    # and a second CNPJ-shaped value elsewhere that fails validation. The
    # valid one must still win the `cnpj` field; the invalid one must
    # never leak into it, only into rejected_tax_ids.
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.223.344/0001-86\n"
        "Transportador CNPJ: 99.888.777/0001-66"
    )
    fake = FakeClient({"legal_name": "ACME Ltda", "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(pdf_bytes, llm_client=fake)

    assert result.cnpj is not None
    assert result.cnpj.value == "11.223.344/0001-86"
    assert len(result.rejected_tax_ids) == 1
    assert result.rejected_tax_ids[0].value == "99.888.777/0001-66"
    assert result.rejected_tax_ids[0].role == "transporter"
