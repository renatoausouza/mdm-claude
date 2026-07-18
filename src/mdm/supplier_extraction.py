from pydantic import BaseModel

from mdm import config
from mdm.cnpj_validation import is_valid_cnpj
from mdm.extraction_schema import FieldValue, PartyInfo, llm_field_to_value
from mdm.field_validation import is_valid_email, is_valid_telephone
from mdm.llm_extraction import OllamaExtractionClient, extract_supplier_fields
from mdm.party_extraction import party_to_info
from mdm.pdf_extraction import extract_pdf_pages
from mdm.regex_candidates import find_candidates
from mdm.role_tagging import tag_roles
from mdm.scoring import DomainSpec, ScoringResult, score_candidate


class SupplierCandidateResult(BaseModel):
    cnpj: FieldValue | None = None
    legal_name: FieldValue | None = None
    email: FieldValue | None = None
    telephone: FieldValue | None = None
    address: FieldValue | None = None
    parties: list[PartyInfo] = []


def run_supplier_extraction(
    content: bytes, llm_client: OllamaExtractionClient | None = None
) -> SupplierCandidateResult:
    pages = extract_pdf_pages(content)
    full_text = "\n".join(page.text for page in pages)

    candidates = find_candidates(pages)
    parties = tag_roles(candidates, pages)
    party_infos = [party_to_info(p) for p in parties]  # computed once, reused for cnpj_field below

    # Only a CNPJ (not a CPF) satisfies the "cnpj" field — role_tagging
    # accepts either kind (needed for Client, #8, which can be either), but
    # Supplier's schema and validators (is_valid_cnpj below) are CNPJ-
    # specific. A CPF tagged "supplier" (e.g. a sole proprietor's personal
    # ID used as a business tax ID) still shows up in `parties` for the
    # reviewer to see, it just doesn't auto-populate this typed field.
    supplier_field = next(
        (info.tax_id for p, info in zip(parties, party_infos) if p.role == "supplier" and p.tax_id.kind == "cnpj"),
        None,
    )
    cnpj_field = supplier_field
    cnpj_anchor = cnpj_field.value if cnpj_field is not None else None

    llm_fields = extract_supplier_fields(full_text, cnpj_anchor, client=llm_client)

    return SupplierCandidateResult(
        cnpj=cnpj_field,
        legal_name=llm_field_to_value(llm_fields, "legal_name"),
        email=llm_field_to_value(llm_fields, "email"),
        telephone=llm_field_to_value(llm_fields, "telephone"),
        address=llm_field_to_value(llm_fields, "address"),
        parties=party_infos,
    )


# Required-for-registration per the solution brief's D15: Supplier = legal
# name + CNPJ. Email/telephone/address are optional but still structurally
# validated when present (D15's hard floor only concerns required fields;
# compliance still checks format on whatever IS populated).
SUPPLIER_DOMAIN_SPEC = DomainSpec(
    required_fields=frozenset({"cnpj", "legal_name"}),
    optional_fields=frozenset({"email", "telephone", "address"}),
    validators={
        "cnpj": is_valid_cnpj,
        "email": is_valid_email,
        "telephone": is_valid_telephone,
    },
)


def score_supplier(result: SupplierCandidateResult) -> ScoringResult:
    fields = {
        "cnpj": result.cnpj,
        "legal_name": result.legal_name,
        "email": result.email,
        "telephone": result.telephone,
        "address": result.address,
    }
    return score_candidate(fields, SUPPLIER_DOMAIN_SPEC, config.get_confidence_threshold())
