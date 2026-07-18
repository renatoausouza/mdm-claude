from mdm.extraction_schema import FieldValue, Provenance
from mdm.supplier_extraction import SupplierCandidateResult, score_supplier


def _field(value: str, confidence: float = 0.95) -> FieldValue:
    return FieldValue(value=value, confidence=confidence, provenance=Provenance(source="regex"))


def test_complete_valid_supplier_scores_excellent() -> None:
    result = SupplierCandidateResult(
        cnpj=_field("11.222.333/0001-81"),
        legal_name=_field("ACME Ltda"),
        email=_field("contato@acme.com"),
        telephone=_field("(11) 98765-4321"),
        address=_field("Rua X, 123"),
    )

    scoring = score_supplier(result)

    assert scoring.reliability == "Excellent"
    assert scoring.missing_required_fields == []


def test_missing_cnpj_caps_reliability_at_low() -> None:
    result = SupplierCandidateResult(
        cnpj=None,
        legal_name=_field("ACME Ltda"),
        email=_field("contato@acme.com"),
        telephone=_field("(11) 98765-4321"),
        address=_field("Rua X, 123"),
    )

    scoring = score_supplier(result)

    assert scoring.reliability == "Low"
    assert "cnpj" in scoring.missing_required_fields


def test_invalid_email_format_lowers_compliance() -> None:
    result = SupplierCandidateResult(
        cnpj=_field("11.222.333/0001-81"),
        legal_name=_field("ACME Ltda"),
        email=_field("not-a-valid-email"),
    )

    scoring = score_supplier(result)

    assert scoring.compliance < 1.0


def test_low_confidence_llm_field_forces_review() -> None:
    result = SupplierCandidateResult(
        cnpj=_field("11.222.333/0001-81"),
        legal_name=_field("ACME Ltda", confidence=0.3),  # e.g. not found verbatim in source
    )

    scoring = score_supplier(result)

    assert scoring.requires_review is True
    assert "legal_name" in scoring.low_confidence_fields
