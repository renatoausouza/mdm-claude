import json

import fitz

from mdm.product_extraction import ProductCandidateResult, run_product_extraction, score_product


class FakeExtractionClient:
    def __init__(self, response_json: dict) -> None:
        self._response_json = response_json

    def generate_json(self, prompt: str) -> str:
        return json.dumps(self._response_json)


def _make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    content: bytes = doc.tobytes()
    doc.close()
    return content


def test_extracts_product_master_and_transactional_fields() -> None:
    fake = FakeExtractionClient(
        {
            "name": "Parafuso Sextavado M8",
            "sku": "PSX-M8-001",
            "ncm": "7318.15.00",
            "description": "Parafuso sextavado em aco inox",
            "price": "12.50",
            "quantity": "100",
            "discount": "5%",
        }
    )
    pdf_bytes = _make_pdf_bytes("Item: Parafuso Sextavado M8, SKU PSX-M8-001, preco 12.50")

    result = run_product_extraction(pdf_bytes, llm_client=fake)

    assert result.name is not None
    assert result.name.value == "Parafuso Sextavado M8"
    assert result.sku is not None and result.sku.value == "PSX-M8-001"
    assert result.ncm is not None and result.ncm.value == "7318.15.00"
    assert result.price is not None and result.price.value == "12.50"
    assert result.quantity is not None and result.quantity.value == "100"
    assert result.discount is not None and result.discount.value == "5%"


def test_score_product_requires_only_name() -> None:
    result = ProductCandidateResult(name=None, sku=None)

    scoring = score_product(result)

    assert scoring.reliability == "Low"
    assert scoring.missing_required_fields == ["name"]


def test_score_product_missing_sku_alone_does_not_force_low_reliability() -> None:
    from mdm.extraction_schema import FieldValue, Provenance

    result = ProductCandidateResult(
        name=FieldValue(value="Parafuso M8", confidence=0.9, provenance=Provenance(source="llm")),
        sku=None,
        ncm=FieldValue(value="7318.15.00", confidence=0.9, provenance=Provenance(source="llm")),
        description=FieldValue(value="Parafuso em aco", confidence=0.9, provenance=Provenance(source="llm")),
    )

    scoring = score_product(result)

    assert scoring.missing_required_fields == []  # SKU is optional, not required
    assert scoring.reliability in {"Excellent", "Good"}


def test_price_quantity_discount_never_affect_scoring() -> None:
    from mdm.extraction_schema import FieldValue, Provenance

    complete_evidence = ProductCandidateResult(
        name=FieldValue(value="Parafuso M8", confidence=0.9, provenance=Provenance(source="llm")),
        price=FieldValue(value="not-a-number-garbage", confidence=0.9, provenance=Provenance(source="llm")),
        quantity=FieldValue(value="???", confidence=0.9, provenance=Provenance(source="llm")),
        discount=FieldValue(value="???", confidence=0.9, provenance=Provenance(source="llm")),
    )
    no_evidence = ProductCandidateResult(
        name=FieldValue(value="Parafuso M8", confidence=0.9, provenance=Provenance(source="llm")),
    )

    # Garbage/missing transactional values must not change the score at all.
    assert score_product(complete_evidence) == score_product(no_evidence)
