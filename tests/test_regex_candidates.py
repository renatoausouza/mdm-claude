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


def test_finds_valid_cpf_with_page_and_bbox_provenance() -> None:
    pdf_bytes = _make_pdf("Cliente: Joao Silva CPF 111.444.777-35")
    pages = extract_pdf_pages(pdf_bytes)

    candidates = find_candidates(pages)

    cpf_candidates = [c for c in candidates if c.kind == "cpf"]
    assert len(cpf_candidates) == 1
    assert cpf_candidates[0].value == "111.444.777-35"
    assert cpf_candidates[0].bbox is not None


def test_checksum_invalid_cpf_shaped_number_is_rejected() -> None:
    pdf_bytes = _make_pdf("Pedido No: 111.444.777-99")
    pages = extract_pdf_pages(pdf_bytes)

    candidates = find_candidates(pages)

    assert [c for c in candidates if c.kind == "cpf"] == []


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


def test_repeated_value_drawn_out_of_visual_order_still_gets_the_right_bbox_each() -> None:
    # Regression test for #14 code review: pdf_extraction.py's sort=True
    # reorders page.text into visual order, but find_bbox() used
    # search_for() results in their original (unsorted, draw-order) order.
    # For a value repeated on a page whose draw order doesn't match its
    # visual order (exactly the DANFE/NFS-e pattern #14 targets), the
    # occurrence_index computed against the sorted text no longer lines up
    # with search_for()'s draw-order match list, so the wrong bbox gets
    # attached to each occurrence. Drawing the visually-lower ("footer")
    # copy FIRST and the visually-higher ("header") copy SECOND reproduces
    # the mismatch.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 400), "Footer CNPJ: 11.223.344/0001-86", fontsize=10)  # drawn first, visually lower
    page.insert_text((72, 72), "Header CNPJ: 11.223.344/0001-86", fontsize=10)  # drawn second, visually higher
    pdf_bytes: bytes = doc.tobytes()
    doc.close()

    pages = extract_pdf_pages(pdf_bytes)
    candidates = [c for c in find_candidates(pages) if c.kind == "cnpj"]

    assert len(candidates) == 2
    # candidates are produced in (sorted) text order, so candidates[0] is
    # the header occurrence (comes first in visual reading order) and must
    # get the header's (higher, smaller-y) bbox — not the footer's.
    assert candidates[0].bbox[1] < candidates[1].bbox[1]
