"""Shared tax-ID-bearing-party conversion (role_tagging.TaggedParty ->
extraction_schema.PartyInfo) — used by every domain whose candidate is
identified by a CNPJ or CPF (Supplier #4, Client #8). Product (#10) has no
tax ID and doesn't use this module."""

import re

from mdm.extraction_schema import FieldValue, PartyInfo, Provenance, RejectedTaxId, RoleEvidenceInfo
from mdm.role_tagging import TaggedParty

REGEX_CONFIDENCE = 0.95


def normalize_tax_id(value: str) -> str:
    return re.sub(r"\D", "", value)


def party_to_info(party: TaggedParty) -> PartyInfo:
    tax_id_field = FieldValue(
        value=party.tax_id.value,
        normalized_value=normalize_tax_id(party.tax_id.value),
        confidence=REGEX_CONFIDENCE,
        provenance=Provenance(source="regex", page=party.tax_id.page_number, bbox=party.tax_id.bbox),
    )
    evidence = RoleEvidenceInfo.model_validate(party.role_evidence) if party.role_evidence is not None else None
    return PartyInfo(tax_id=tax_id_field, role=party.role, role_evidence=evidence)


def rejected_party_to_info(party: TaggedParty) -> RejectedTaxId:
    """Same TaggedParty -> API-shape conversion as party_to_info, for a
    candidate that role_tagging.tag_roles tagged but that never passed
    checksum validation (see RejectedTaxId's own docstring)."""
    evidence = RoleEvidenceInfo.model_validate(party.role_evidence) if party.role_evidence is not None else None
    return RejectedTaxId(value=party.tax_id.value, kind=party.tax_id.kind, role=party.role, role_evidence=evidence)
