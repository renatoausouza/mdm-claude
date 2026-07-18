import fitz

from mdm.pdf_extraction import extract_pdf_pages
from mdm.regex_candidates import find_candidates


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_finds_cnpj_email_and_phone_with_page_and_bbox_provenance() -> None:
    pdf_bytes = _make_pdf(
        "Fornecedor: ACME Ltda CNPJ 11.223.344/0001-86\n"
        "Email: contato@acme.com Fone: (11) 98765-4321"
    )
    pages = extract_pdf_pages(pdf_bytes)

    candidates = find_candidates(pages)

    cnpj_candidates = [c for c in candidates if c.kind == "cnpj"]
    assert len(cnpj_candidates) == 1
    assert cnpj_candidates[0].value == "11.223.344/0001-86"
    assert cnpj_candidates[0].page_number == 1
    assert cnpj_candidates[0].bbox is not None

    email_candidates = [c for c in candidates if c.kind == "email"]
    assert len(email_candidates) == 1
    assert email_candidates[0].value == "contato@acme.com"

    phone_candidates = [c for c in candidates if c.kind == "phone"]
    assert len(phone_candidates) == 1
    assert "98765-4321" in phone_candidates[0].value


def test_checksum_invalid_cnpj_shaped_number_is_rejected() -> None:
    # An order/reference number that happens to look CNPJ-formatted but
    # fails the check-digit algorithm must not be treated as a real CNPJ.
    pdf_bytes = _make_pdf("Pedido No: 12.345.678/0001-99")
    pages = extract_pdf_pages(pdf_bytes)

    candidates = find_candidates(pages)

    assert [c for c in candidates if c.kind == "cnpj"] == []


def test_repeated_value_on_one_page_gets_its_own_bbox_each() -> None:
    # Regression test: find_bbox used to always return the FIRST
    # occurrence's bbox, so a CNPJ repeated in a header and footer would
    # get the same (wrong) bbox for both candidates.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Header CNPJ: 11.223.344/0001-86", fontsize=10)
    page.insert_text((72, 400), "Footer CNPJ: 11.223.344/0001-86", fontsize=10)
    pdf_bytes: bytes = doc.tobytes()
    doc.close()

    pages = extract_pdf_pages(pdf_bytes)
    candidates = [c for c in find_candidates(pages) if c.kind == "cnpj"]

    assert len(candidates) == 2
    assert candidates[0].bbox != candidates[1].bbox
    assert candidates[0].bbox[1] < candidates[1].bbox[1]  # header above footer
