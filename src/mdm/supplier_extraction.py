import re

from pydantic import BaseModel, ConfigDict

from mdm import config
from mdm.cnpj_validation import is_valid_cnpj
from mdm.field_validation import is_valid_email, is_valid_telephone
from mdm.llm_extraction import OllamaExtractionClient, extract_supplier_fields
from mdm.pdf_extraction import extract_pdf_pages
from mdm.regex_candidates import find_candidates
from mdm.role_tagging import TaggedParty, tag_roles
from mdm.scoring import DomainSpec, ScoringResult, score_candidate

REGEX_CONFIDENCE = 0.95


class Provenance(BaseModel):
    source: str  # "regex" | "llm"
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class FieldValue(BaseModel):
    value: str
    normalized_value: str | None = None
    confidence: float
    provenance: Provenance


class RoleEvidenceInfo(BaseModel):
    # from_attributes lets this be built directly from role_tagging's
    # RoleEvidence dataclass (model_validate below) instead of a hand-copied
    # field-by-field mapping that silently drifts if either side gains a field.
    model_config = ConfigDict(from_attributes=True)

    matched_label: str
    location: str


class PartyInfo(BaseModel):
    tax_id: FieldValue
    role: str
    role_evidence: RoleEvidenceInfo | None = None


class SupplierCandidateResult(BaseModel):
    cnpj: FieldValue | None = None
    legal_name: FieldValue | None = None
    email: FieldValue | None = None
    telephone: FieldValue | None = None
    address: FieldValue | None = None
    parties: list[PartyInfo] = []


def _normalize_cnpj(value: str) -> str:
    return re.sub(r"\D", "", value)


def _party_to_info(party: TaggedParty) -> PartyInfo:
    tax_id_field = FieldValue(
        value=party.tax_id.value,
        normalized_value=_normalize_cnpj(party.tax_id.value),
        confidence=REGEX_CONFIDENCE,
        provenance=Provenance(source="regex", page=party.tax_id.page_number, bbox=party.tax_id.bbox),
    )
    evidence = RoleEvidenceInfo.model_validate(party.role_evidence) if party.role_evidence is not None else None
    return PartyInfo(tax_id=tax_id_field, role=party.role, role_evidence=evidence)


def run_supplier_extraction(
    content: bytes, llm_client: OllamaExtractionClient | None = None
) -> SupplierCandidateResult:
    pages = extract_pdf_pages(content)
    full_text = "\n".join(page.text for page in pages)

    candidates = find_candidates(pages)
    parties = tag_roles(candidates, pages)
    party_infos = [_party_to_info(p) for p in parties]  # computed once, reused for cnpj_field below

    supplier_info = next((info for info in party_infos if info.role == "supplier"), None)
    cnpj_field = supplier_info.tax_id if supplier_info is not None else None
    cnpj_anchor = cnpj_field.value if cnpj_field is not None else None

    llm_fields = extract_supplier_fields(full_text, cnpj_anchor, client=llm_client)

    def to_field(name: str) -> FieldValue | None:
        result = llm_fields.get(name)
        if result is None:
            return None
        return FieldValue(value=result.value, confidence=result.confidence, provenance=Provenance(source="llm"))

    return SupplierCandidateResult(
        cnpj=cnpj_field,
        legal_name=to_field("legal_name"),
        email=to_field("email"),
        telephone=to_field("telephone"),
        address=to_field("address"),
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
