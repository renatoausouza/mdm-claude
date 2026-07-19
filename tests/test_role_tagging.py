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


def test_label_several_lines_above_the_value_is_still_found() -> None:
    # Regression test for #14: real invoices commonly put a section header
    # ("Destinatário / Remetente") several lines above the block of fields
    # it labels, not on the line immediately before the tax ID. The old
    # "same line or one line up" window missed this; the search must walk
    # back through the page (in reading order) to the nearest preceding
    # label, however many lines away.
    pdf_bytes = _make_pdf(
        "Destinatario / Remetente\n"
        "Nome / Razao Social\n"
        "Endereco\n"
        "Municipio\n"
        "CNPJ/CPF: 22.222.222/0001-91"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert parties[0].role == "client"
    assert parties[0].role_evidence is not None
    assert parties[0].role_evidence.matched_label in ("destinatario", "destinatário")


def test_tomador_label_is_recognized_as_client_role() -> None:
    # NFS-e (services invoice) uses "Tomador do(s) Servico(s)" to label the
    # service recipient, not "Destinatario" — a real label vocabulary gap
    # found while investigating #14 against a services-invoice layout.
    pdf_bytes = _make_pdf("Tomador do(s) Servico(s)\nCPF/CNPJ: 111.444.777-35")
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert parties[0].role == "client"


def test_unlabeled_candidate_after_a_labeled_block_does_not_inherit_its_label() -> None:
    # Regression test found in code review of #14: the widened backward
    # search must stop at the nearest earlier OTHER candidate's own line —
    # otherwise a label that correctly belongs to an earlier, different
    # party "bleeds" onto a later, unrelated candidate that has no real
    # label of its own (e.g. an unlabeled reference CNPJ in a "Dados
    # Adicionais" footer, several sections after a real Transportador
    # block). That candidate must stay "unknown", not inherit
    # "transporter" just because "Transportador" is the nearest word.
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.111.111/0001-91\n"
        "Destinatario CNPJ: 22.222.222/0001-91\n"
        "Transportador CNPJ: 33.333.333/0001-91\n"
        "Dados Adicionais\n"
        "Nota fiscal referente ao contrato 456.\n"
        "Contador responsavel: 44.444.444/0001-91"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)
    parties_by_cnpj = {p.tax_id.value: p.role for p in parties}

    assert parties_by_cnpj["11.111.111/0001-91"] == "supplier"
    assert parties_by_cnpj["22.222.222/0001-91"] == "client"
    assert parties_by_cnpj["33.333.333/0001-91"] == "transporter"
    assert parties_by_cnpj["44.444.444/0001-91"] == "unknown"


def test_role_word_inside_unrelated_prose_is_not_matched_as_a_label() -> None:
    # Regression test found in code review of #14: a role word appearing
    # incidentally inside ordinary prose (a return-policy disclaimer,
    # here) — not as its own section-header line — must not be treated as
    # a real label. The second (repeated) CNPJ has no real label of its
    # own nearby, so it must correctly land on "unknown" (routes to human
    # review), not get pulled into "client" just because "comprador"
    # happens to appear somewhere earlier on the page.
    pdf_bytes = _make_pdf(
        "Fornecedor CNPJ: 11.223.344/0001-86\n"
        "Este cupom nao pode ser trocado, exceto pelo comprador original.\n"
        "Via: 11.223.344/0001-86"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert [p.role for p in parties] == ["supplier", "unknown"]


def test_a_label_appearing_later_in_the_document_is_not_picked_up() -> None:
    # Regression test for #14: a role-label-shaped word positioned *after*
    # a tax ID in reading order (e.g. a freight-payer code reading "0 -
    # Emitente" further down the page) must never be treated as that
    # earlier tax ID's role evidence. The search only looks backward from
    # the candidate's own position.
    pdf_bytes = _make_pdf(
        "Some unrelated heading\n"
        "CNPJ: 11.223.344/0001-86\n"
        "more unrelated text\n"
        "Frete por conta: 0 - Emitente"
    )
    pages = extract_pdf_pages(pdf_bytes)
    candidates = find_candidates(pages)

    parties = tag_roles(candidates, pages)

    assert parties[0].role == "unknown"
    assert parties[0].role_evidence is None


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
