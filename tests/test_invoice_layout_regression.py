import json

import fitz

from mdm.client_extraction import run_client_extraction
from mdm.supplier_extraction import run_supplier_extraction

# Regression fixtures for #14. Each PDF below is entirely synthetic —
# fabricated company/person names and checksum-valid-but-fake CNPJ/CPF
# values — but structurally modeled on three real invoice layouts (a
# product NF-e with a transporter block, a product-return NF-e, and an
# NFS-e services invoice) that motivated this ticket. No real document
# content or PII is reproduced here.
#
# Text is drawn out of visual order (a decoy/late block inserted before
# earlier-positioned blocks) to reproduce the PDF content-stream/visual-order
# mismatch that #14's pdf_extraction.py fix addresses — these fixtures would
# fail without both that fix and role_tagging's widened search.


class FakeLlmClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _draw(page: "fitz.Page", y: float, text: str) -> None:
    page.insert_text((72, y), text, fontsize=10)


def _product_nfe_with_transporter_block() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    # Drawn out of visual order on purpose: the transporter/freight decoy
    # block (visually last) is drawn first, then the masthead (visually
    # first), then the destinatario block (visually second).
    _draw(page, 400, "TRANSPORTADOR / VOLUMES TRANSPORTADOS")
    _draw(page, 415, "FRETE POR CONTA")
    _draw(page, 430, "0 - Emitente")
    _draw(page, 80, "AURORA COMERCIO DE ELETRONICOS LTDA")
    _draw(page, 95, "CNPJ 11.223.344/0001-86")
    _draw(page, 160, "DESTINATARIO / REMETENTE")
    _draw(page, 175, "Nome / Razao Social")
    _draw(page, 190, "Endereco")
    _draw(page, 205, "Municipio")
    _draw(page, 220, "CNPJ/CPF: 98.765.432/0001-98")
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_product_nfe_client_tagged_despite_distant_label_and_draw_order() -> None:
    fake = FakeLlmClient({"name": "Comprador Exemplo", "email": None, "telephone": None, "address": None})

    result = run_client_extraction(_product_nfe_with_transporter_block(), llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "98.765.432/0001-98"
    client_parties = [p for p in result.parties if p.role == "client"]
    assert len(client_parties) == 1


def test_product_nfe_masthead_issuer_stays_unknown_not_misattached_to_decoy() -> None:
    # The masthead CNPJ has no preceding label at all (it's the first thing
    # on the page) — per #14's revised scope this correctly stays unknown
    # rather than being guessed from position. The "0 - Emitente" freight
    # decoy sits *after* the masthead CNPJ in reading order and must not
    # retroactively attach to it.
    fake = FakeLlmClient({"legal_name": None, "email": None, "telephone": None, "address": None})

    result = run_supplier_extraction(_product_nfe_with_transporter_block(), llm_client=fake)

    assert result.cnpj is None
    masthead_party = next(p for p in result.parties if p.tax_id.value == "11.223.344/0001-86")
    assert masthead_party.role == "unknown"
    assert masthead_party.role_evidence is None


def _product_return_nfe() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    # Again drawn out of order: bottom acknowledgment line first, masthead
    # second, transporter block (with its own labeled CNPJ) third, client
    # block last — none in their visual top-to-bottom order.
    _draw(page, 500, "RECEBI(EMOS) DE COMERCIAL BOA VISTA LTDA")
    _draw(page, 80, "COMERCIAL BOA VISTA LTDA")
    _draw(page, 95, "CNPJ 33.333.333/0001-91")
    _draw(page, 300, "TRANSPORTADOR / VOLUMES TRANSPORTADOS")
    _draw(page, 315, "Transportador CNPJ: 11.111.111/0001-91")
    _draw(page, 160, "DESTINATARIO / REMETENTE")
    _draw(page, 175, "Nome / Razao Social")
    _draw(page, 190, "CNPJ/CPF: 22.222.222/0001-91")
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_product_return_nfe_client_and_transporter_both_correctly_tagged() -> None:
    fake = FakeLlmClient({"name": "Cliente Devolucao", "email": None, "telephone": None, "address": None})

    result = run_client_extraction(_product_return_nfe(), llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "22.222.222/0001-91"
    roles = {p.tax_id.value: p.role for p in result.parties}
    assert roles["11.111.111/0001-91"] == "transporter"
    assert roles["33.333.333/0001-91"] == "unknown"  # masthead, unlabeled


def _nfse_services_invoice() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    # Drawn out of order: tomador block first, masthead second.
    _draw(page, 200, "Tomador do(s) Servico(s)")
    _draw(page, 215, "CPF/CNPJ: 111.444.777-35")
    _draw(page, 80, "CLINICA EXEMPLO DE SAUDE LTDA")
    _draw(page, 95, "CPF/CNPJ: 11.223.344/0001-86")
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_nfse_tomador_label_tagged_as_client_despite_draw_order() -> None:
    fake = FakeLlmClient({"name": "Paciente Exemplo", "email": None, "telephone": None, "address": None})

    result = run_client_extraction(_nfse_services_invoice(), llm_client=fake)

    assert result.tax_id is not None
    assert result.tax_id.value == "111.444.777-35"
    roles = {p.tax_id.value: p.role for p in result.parties}
    assert roles["11.223.344/0001-86"] == "unknown"  # masthead issuer, unlabeled
