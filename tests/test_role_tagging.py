import fitz

from mdm.pdf_extraction import extract_pdf_pages
from mdm.regex_candidates import find_candidates
from mdm.role_tagging import tag_roles


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_tags_supplier_role_from_nearby_label() -> None:
    pdf_bytes = _make_pdf("Fornecedor CNPJ: 11.223.344/0001-86")
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    cnpj_parties = [p for p in parties if p.tax_id.kind == "cnpj"]
    assert len(cnpj_parties) == 1
    assert cnpj_parties[0].role == "supplier"
    assert cnpj_parties[0].role_evidence is not None


def test_tags_client_role_from_nearby_label() -> None:
    pdf_bytes = _make_pdf("Destinatario CNPJ: 98.765.432/0001-98")
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert parties[0].role == "client"


def test_tags_client_role_from_a_cpf_not_just_cnpj() -> None:
    # A client can be an individual (CPF), not just a company (CNPJ) — #8.
    pdf_bytes = _make_pdf("Cliente CPF: 111.444.777-35")
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    cpf_parties = [p for p in parties if p.tax_id.kind == "cpf"]
    assert len(cpf_parties) == 1
    assert cpf_parties[0].role == "client"


def test_tax_id_with_no_nearby_label_is_unknown() -> None:
    pdf_bytes = _make_pdf("Some random document text 11.223.344/0001-86 more text")
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert parties[0].role == "unknown"
    assert parties[0].role_evidence is None


def test_two_parties_on_the_same_line_get_the_closer_label_each() -> None:
    # Regression test: both CNPJs previously got tagged "supplier" because
    # _find_role_label checked roles in a fixed priority order rather than
    # by proximity to each candidate's own position on the shared line.
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.111.111/0001-91   Destinatario CNPJ: 22.222.222/0001-91"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)
    parties_by_cnpj = {p.tax_id.value: p.role for p in parties}

    assert parties_by_cnpj["11.111.111/0001-91"] == "supplier"
    assert parties_by_cnpj["22.222.222/0001-91"] == "client"


def test_three_or_more_tax_ids_are_all_retained() -> None:
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.111.111/0001-91\n"
        "Destinatario CNPJ: 22.222.222/0001-91\n"
        "Transportador CNPJ: 33.333.333/0001-91"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    cnpj_parties = [p for p in parties if p.tax_id.kind == "cnpj"]
    assert len(cnpj_parties) == 3
    roles = {p.role for p in cnpj_parties}
    assert roles == {"supplier", "client", "transporter"}
