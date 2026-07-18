from dataclasses import dataclass

from mdm.scoring import DomainSpec, score_candidate


@dataclass
class _Field:
    value: str
    confidence: float


def test_completeness_and_compliance_basic_case() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b", "c", "d"}),
        validators={},
    )
    fields = {
        "a": _Field(value="x", confidence=0.9),
        "b": _Field(value="y", confidence=0.9),
        "c": None,
        "d": None,
    }

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.completeness == 0.5  # 2 of 4 fields populated
    assert result.compliance == 1.0  # both populated fields pass (no validators)


def test_missing_required_field_caps_reliability_at_low_even_if_otherwise_excellent() -> None:
    # Regression test explicitly requested by the ticket: a record missing
    # one required field but with everything else populated and valid must
    # score Low, not Good/Excellent.
    domain = DomainSpec(
        required_fields=frozenset({"cnpj"}),
        optional_fields=frozenset({"email", "telephone", "address"}),
        validators={},
    )
    fields = {
        "cnpj": None,  # the one required field, missing
        "email": _Field(value="a@b.com", confidence=0.95),
        "telephone": _Field(value="11999999999", confidence=0.95),
        "address": _Field(value="Rua X, 123", confidence=0.95),
    }

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.completeness == 0.75  # 3 of 4 populated — would read "Good" on percentages alone
    assert result.compliance == 1.0
    assert result.reliability == "Low"
    assert "cnpj" in result.missing_required_fields
    # A missing required field must force review on its own — the other
    # fields' high confidence must not be enough to wave it through.
    assert result.requires_review is True


def test_blank_value_on_required_field_counts_as_missing_not_populated() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset(),
        validators={},
    )
    fields = {"a": _Field(value="   ", confidence=0.95)}

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.reliability == "Low"
    assert "a" in result.missing_required_fields
    assert result.requires_review is True


def test_high_completeness_and_compliance_yields_excellent() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b"}),
        validators={},
    )
    fields = {"a": _Field(value="x", confidence=0.95), "b": _Field(value="y", confidence=0.95)}

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.reliability == "Excellent"


def test_moderate_completeness_and_compliance_yields_good() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b", "c", "d", "e", "f", "g", "h", "i", "j"}),
        validators={},
    )
    # 7 of 10 fields populated = 70% completeness, all valid = 100% compliance
    fields = {name: _Field(value="x", confidence=0.95) for name in ["a", "b", "c", "d", "e", "f", "g"]}
    fields.update({"h": None, "i": None, "j": None})

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.completeness == 0.7
    assert result.reliability == "Good"


def test_low_completeness_yields_low() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b", "c", "d", "e", "f", "g", "h", "i", "j"}),
        validators={},
    )
    fields = {"a": _Field(value="x", confidence=0.95)}
    fields.update({name: None for name in ["b", "c", "d", "e", "f", "g", "h", "i", "j"]})

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.completeness == 0.1
    assert result.reliability == "Low"


def test_structural_validation_failure_lowers_compliance() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b"}),
        validators={"a": lambda v: v == "valid-shape"},
    )
    fields = {"a": _Field(value="not-the-right-shape", confidence=0.95), "b": _Field(value="y", confidence=0.95)}

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.compliance == 0.5  # 1 of 2 populated fields passes validation


def test_field_below_confidence_threshold_forces_review_regardless_of_reliability() -> None:
    domain = DomainSpec(
        required_fields=frozenset({"a"}),
        optional_fields=frozenset({"b"}),
        validators={},
    )
    fields = {"a": _Field(value="x", confidence=0.95), "b": _Field(value="y", confidence=0.3)}

    result = score_candidate(fields, domain, confidence_threshold=0.7)

    assert result.reliability == "Excellent"  # completeness/compliance both 100%
    assert result.requires_review is True  # ...but a low-confidence field still forces review
    assert "b" in result.low_confidence_fields


def test_engine_is_domain_generic_not_hardcoded_to_supplier() -> None:
    # Two structurally different domain specs, proving the engine takes
    # its field lists as a parameter rather than being hardcoded.
    supplier_like = DomainSpec(
        required_fields=frozenset({"cnpj", "legal_name"}),
        optional_fields=frozenset({"email", "telephone", "address"}),
        validators={},
    )
    other_domain = DomainSpec(
        required_fields=frozenset({"sku"}),
        optional_fields=frozenset({"description"}),
        validators={},
    )

    supplier_result = score_candidate(
        {"cnpj": _Field("x", 0.9), "legal_name": _Field("y", 0.9), "email": None, "telephone": None, "address": None},
        supplier_like,
        confidence_threshold=0.7,
    )
    other_result = score_candidate(
        {"sku": _Field("x", 0.9), "description": None},
        other_domain,
        confidence_threshold=0.7,
    )

    assert supplier_result.completeness == 0.4  # 2 of 5
    assert other_result.completeness == 0.5  # 1 of 2
