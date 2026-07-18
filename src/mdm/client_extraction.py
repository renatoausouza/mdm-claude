from pydantic import BaseModel

from mdm import config
from mdm.cnpj_validation import is_valid_cnpj
from mdm.cpf_validation import is_valid_cpf
from mdm.extraction_schema import FieldValue, PartyInfo, llm_field_to_value
from mdm.field_validation import is_valid_email, is_valid_telephone
from mdm.llm_extraction import OllamaExtractionClient, extract_client_fields
from mdm.party_extraction import party_to_info
from mdm.pdf_extraction import extract_pdf_pages
from mdm.regex_candidates import find_candidates
from mdm.role_tagging import tag_roles
from mdm.scoring import DomainSpec, ScoringResult, score_candidate


class ClientCandidateResult(BaseModel):
    tax_id: FieldValue | None = None  # CPF (individual) or CNPJ (company), whichever was found
    name: FieldValue | None = None
    email: FieldValue | None = None
    telephone: FieldValue | None = None
    address: FieldValue | None = None
    parties: list[PartyInfo] = []


def run_client_extraction(
    content: bytes, llm_client: OllamaExtractionClient | None = None
) -> ClientCandidateResult:
    pages = extract_pdf_pages(content)
    full_text = "\n".join(page.text for page in pages)

    candidates = find_candidates(pages)
    parties = tag_roles(candidates, pages)
    party_infos = [party_to_info(p) for p in parties]  # computed once, reused for tax_id_field below

    client_info = next((info for info in party_infos if info.role == "client"), None)
    tax_id_field = client_info.tax_id if client_info is not None else None
    tax_id_anchor = tax_id_field.value if tax_id_field is not None else None

    llm_fields = extract_client_fields(full_text, tax_id_anchor, client=llm_client)

    return ClientCandidateResult(
        tax_id=tax_id_field,
        name=llm_field_to_value(llm_fields, "name"),
        email=llm_field_to_value(llm_fields, "email"),
        telephone=llm_field_to_value(llm_fields, "telephone"),
        address=llm_field_to_value(llm_fields, "address"),
        parties=party_infos,
    )


def _is_valid_cpf_or_cnpj(value: str) -> bool:
    return is_valid_cpf(value) or is_valid_cnpj(value)


# Required-for-registration per D15 (redefined for the Client domain, #8):
# name + CPF/CNPJ. Email/telephone/address are optional but still
# structurally validated when present.
CLIENT_DOMAIN_SPEC = DomainSpec(
    required_fields=frozenset({"tax_id", "name"}),
    optional_fields=frozenset({"email", "telephone", "address"}),
    validators={
        "tax_id": _is_valid_cpf_or_cnpj,
        "email": is_valid_email,
        "telephone": is_valid_telephone,
    },
)


def score_client(result: ClientCandidateResult) -> ScoringResult:
    fields = {
        "tax_id": result.tax_id,
        "name": result.name,
        "email": result.email,
        "telephone": result.telephone,
        "address": result.address,
    }
    return score_candidate(fields, CLIENT_DOMAIN_SPEC, config.get_confidence_threshold())
