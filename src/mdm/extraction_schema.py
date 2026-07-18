"""Field/provenance/party shapes shared across every extraction domain
(Supplier #4, Client #8, Product #10) — every extracted field, regardless of
domain, carries {value, confidence, provenance} (D16), and any tax-ID-bearing
party additionally carries a role (D3). Domain-specific candidate result
models (SupplierCandidateResult, ClientCandidateResult, ProductCandidateResult)
live in their own per-domain modules and compose these types."""

from pydantic import BaseModel, ConfigDict

from mdm.llm_extraction import LlmFieldResult


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
    # RoleEvidence dataclass (model_validate) instead of a hand-copied
    # field-by-field mapping that silently drifts if either side gains a field.
    model_config = ConfigDict(from_attributes=True)

    matched_label: str
    location: str


class PartyInfo(BaseModel):
    tax_id: FieldValue
    role: str
    role_evidence: RoleEvidenceInfo | None = None


def llm_field_to_value(llm_fields: dict[str, LlmFieldResult | None], name: str) -> FieldValue | None:
    # Identical across every extraction domain (Supplier/Client/Product) —
    # one definition instead of three copies of the same closure.
    result = llm_fields.get(name)
    if result is None:
        return None
    return FieldValue(value=result.value, confidence=result.confidence, provenance=Provenance(source="llm"))
