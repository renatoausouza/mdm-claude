from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol


class ScorableField(Protocol):
    value: str
    confidence: float


@dataclass
class AlreadyApprovedField:
    """Bridges an already-registered MasterRecord's plain string field value
    (fields_json has no confidence — it's discarded on approval, see
    domains.fields_dict) into score_candidate's ScorableField shape, so
    completeness/compliance can be recomputed for registered data (#18's
    dashboard) with the exact same function extraction-time candidates use,
    not a second copy of this logic. confidence is fixed at 1.0 and must
    never be read from the result — completeness/compliance don't depend on
    it (only low_confidence_fields/reliability do, and #18 deliberately
    doesn't surface either: reliability/confidence are candidate-time-only
    concepts that don't apply to already-registered data)."""

    value: str
    confidence: float = 1.0


@dataclass
class DomainSpec:
    """A domain's field vocabulary for scoring — not hardcoded to any one
    domain (Supplier/Client/Product all plug in their own required/optional
    field names and structural validators)."""

    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    # field name -> structural validator; a field with no entry here is
    # considered valid whenever it's populated (nothing to violate, e.g. a
    # free-text legal name or address).
    validators: dict[str, Callable[[str], bool]] = field(default_factory=dict)

    @property
    def all_fields(self) -> frozenset[str]:
        return self.required_fields | self.optional_fields


@dataclass
class ScoringResult:
    completeness: float
    compliance: float
    reliability: str  # "Excellent" | "Good" | "Low"
    missing_required_fields: list[str]
    low_confidence_fields: list[str]
    requires_review: bool


def score_candidate(
    fields: Mapping[str, ScorableField | None],
    domain: DomainSpec,
    confidence_threshold: float,
) -> ScoringResult:
    total_fields = domain.all_fields
    populated: dict[str, ScorableField] = {
        name: f
        for name in total_fields
        if (f := fields.get(name)) is not None and f.value.strip()
    }

    completeness = len(populated) / len(total_fields) if total_fields else 0.0

    if populated:
        valid_count = 0
        for name, f in populated.items():
            validator = domain.validators.get(name)
            if validator is None or validator(f.value):
                valid_count += 1
        compliance = valid_count / len(populated)
    else:
        # Vacuously compliant: nothing populated means nothing to violate.
        # The missing-required-field hard floor below still catches this
        # case regardless of what compliance reports.
        compliance = 1.0

    missing_required = sorted(domain.required_fields - populated.keys())

    if missing_required:
        reliability = "Low"
    elif completeness >= 0.9 and compliance >= 0.9:
        reliability = "Excellent"
    elif completeness >= 0.7 and compliance >= 0.7:
        reliability = "Good"
    else:
        reliability = "Low"

    low_confidence_fields = sorted(
        name for name, f in fields.items() if f is not None and f.confidence < confidence_threshold
    )

    return ScoringResult(
        completeness=completeness,
        compliance=compliance,
        reliability=reliability,
        missing_required_fields=missing_required,
        low_confidence_fields=low_confidence_fields,
        # A missing required field must force review on its own (D15) — it
        # can't rely on low_confidence_fields, since a field that's entirely
        # absent has no confidence score to be low.
        requires_review=bool(missing_required) or bool(low_confidence_fields),
    )
