from pydantic import BaseModel

from mdm import config
from mdm.extraction_schema import FieldValue, llm_field_to_value
from mdm.llm_extraction import OciGenAiExtractionClient, extract_product_fields
from mdm.pdf_extraction import extract_pdf_pages
from mdm.scoring import DomainSpec, ScoringResult, score_candidate


class ProductCandidateResult(BaseModel):
    name: FieldValue | None = None
    sku: FieldValue | None = None
    ncm: FieldValue | None = None
    description: FieldValue | None = None
    # Transactional evidence linked to the source document — captured here
    # for audit/lineage but deliberately never a Product MasterRecord field
    # and never part of duplicate-review matching/diffing (D10, #10). See
    # score_product below and review.py/duplicates.py's use of
    # domains.DOMAIN_SPECS["product"].master_fields, which excludes them.
    price: FieldValue | None = None
    quantity: FieldValue | None = None
    discount: FieldValue | None = None


def run_product_extraction(
    content: bytes, llm_client: OciGenAiExtractionClient | None = None
) -> ProductCandidateResult:
    # No tax-ID/role-tagging pass here — unlike Supplier/Client, a Product
    # candidate isn't identified by a CNPJ/CPF, just extracted directly from
    # the document text (see llm_extraction.py's scope note on
    # single-primary-item extraction).
    pages = extract_pdf_pages(content)
    full_text = "\n".join(page.text for page in pages)

    llm_fields = extract_product_fields(full_text, client=llm_client)

    return ProductCandidateResult(
        name=llm_field_to_value(llm_fields, "name"),
        sku=llm_field_to_value(llm_fields, "sku"),
        ncm=llm_field_to_value(llm_fields, "ncm"),
        description=llm_field_to_value(llm_fields, "description"),
        price=llm_field_to_value(llm_fields, "price"),
        quantity=llm_field_to_value(llm_fields, "quantity"),
        discount=llm_field_to_value(llm_fields, "discount"),
    )


# Required-for-registration per D15/FR-11: name only — SKU absence routes to
# manual linking during review rather than blocking scoring (#11).
PRODUCT_DOMAIN_SPEC = DomainSpec(
    required_fields=frozenset({"name"}),
    optional_fields=frozenset({"sku", "ncm", "description"}),
    validators={},
)


def score_product(result: ProductCandidateResult) -> ScoringResult:
    # price/quantity/discount are deliberately excluded — transactional
    # evidence, not master fields, never gate reliability/review (D10).
    fields = {
        "name": result.name,
        "sku": result.sku,
        "ncm": result.ncm,
        "description": result.description,
    }
    return score_candidate(fields, PRODUCT_DOMAIN_SPEC, config.get_confidence_threshold())
