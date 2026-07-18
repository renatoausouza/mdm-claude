import fitz

from mdm.pdf_extraction import extract_pdf_pages


def _make_pdf(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_extracts_text_per_page() -> None:
    pdf_bytes = _make_pdf(["First page content", "Second page content"])

    pages = extract_pdf_pages(pdf_bytes)

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "First page content" in pages[0].text
    assert pages[1].page_number == 2
    assert "Second page content" in pages[1].text


def test_page_can_locate_bbox_for_a_substring() -> None:
    pdf_bytes = _make_pdf(["CNPJ 12.345.678/0001-99 here"])

    pages = extract_pdf_pages(pdf_bytes)

    bbox = pages[0].find_bbox("12.345.678/0001-99")
    assert bbox is not None
    assert len(bbox) == 4
