import json
import logging
from dataclasses import dataclass

import httpx

from mdm import config

logger = logging.getLogger(__name__)

SUPPLIER_FIELDS = ["legal_name", "email", "telephone", "address"]

HIGH_CONFIDENCE = 0.9
LOW_CONFIDENCE = 0.3


@dataclass
class LlmFieldResult:
    value: str
    confidence: float
    found_verbatim_in_source: bool


class OllamaExtractionClient:
    def generate_json(self, prompt: str) -> str:
        response = httpx.post(
            f"{config.get_ollama_base_url()}/api/generate",
            json={
                "model": config.get_ollama_extraction_model(),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=config.get_ollama_extraction_timeout_seconds(),
        )
        response.raise_for_status()
        result: str = response.json()["response"]
        return result


def _build_prompt(
    document_text: str, tax_id_anchor: str | None, party_label: str, fields: list[str], extra_instructions: str = ""
) -> str:
    anchor_line = (
        f'The {party_label}\'s tax ID (CPF/CNPJ) is known to be: "{tax_id_anchor}". '
        f"Use this to identify which party in the document is the {party_label}.\n"
        if tax_id_anchor
        else ""
    )
    field_list = ", ".join(f'"{f}"' for f in fields)
    return (
        "You are a document extraction assistant. Extract information about "
        f"the {party_label.upper()} from the text below.\n"
        f"{anchor_line}"
        f"{extra_instructions}"
        f"Return ONLY a flat JSON object with these exact keys: {field_list}. "
        "Each value must be a plain string, not a nested object. Use null "
        "for any field you cannot find. Do not include any other text.\n\n"
        f'Document:\n"""\n{document_text}\n"""\n'
    )


def extract_fields(
    document_text: str,
    tax_id_anchor: str | None,
    party_label: str,
    fields: list[str],
    client: OllamaExtractionClient | None = None,
    extra_instructions: str = "",
) -> dict[str, LlmFieldResult | None]:
    """Domain-generic LLM extraction — extract_supplier_fields/
    extract_client_fields/extract_product_fields are thin wrappers around
    this with their own field list and prompt wording (#4, #8, #10).
    `tax_id_anchor` is None for domains with no tax ID (Product)."""
    client = client or OllamaExtractionClient()
    prompt = _build_prompt(document_text, tax_id_anchor, party_label, fields, extra_instructions)

    try:
        raw = client.generate_json(prompt)
        parsed = json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("LLM extraction call failed, treating all fields as not found: %s", exc)
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    results: dict[str, LlmFieldResult | None] = {}
    for field in fields:
        value = parsed.get(field)
        if isinstance(value, (int, float, bool)):
            # A weaker/different model can return a legitimate value as a
            # JSON number/bool despite the prompt asking for a string
            # (e.g. a phone number as a bare int) — coerce rather than
            # silently discard a value that was actually found.
            value = str(value)
        if not isinstance(value, str) or not value.strip():
            results[field] = None
            continue
        found = value.lower() in document_text.lower()
        confidence = HIGH_CONFIDENCE if found else LOW_CONFIDENCE
        results[field] = LlmFieldResult(value=value, confidence=confidence, found_verbatim_in_source=found)
    return results


def extract_supplier_fields(
    document_text: str,
    cnpj_anchor: str | None,
    client: OllamaExtractionClient | None = None,
) -> dict[str, LlmFieldResult | None]:
    return extract_fields(document_text, cnpj_anchor, "supplier", SUPPLIER_FIELDS, client)


CLIENT_FIELDS = ["name", "email", "telephone", "address"]


def extract_client_fields(
    document_text: str,
    tax_id_anchor: str | None,
    client: OllamaExtractionClient | None = None,
) -> dict[str, LlmFieldResult | None]:
    return extract_fields(document_text, tax_id_anchor, "client", CLIENT_FIELDS, client)


# Scope decision: extracts the PRIMARY product line item only, mirroring
# the existing one-candidate-per-domain-per-job architecture Supplier/Client
# already use (an invoice's single issuing supplier) rather than building
# multi-item extraction — a materially larger change this ticket doesn't
# ask for. Price/quantity/discount are captured here as transactional
# evidence but never become Product MasterRecord fields (#10). The prompt
# below explicitly instructs the model to pick one line item consistently
# (not just "extract product fields" with no guidance) — without that, a
# multi-item invoice could produce a candidate with fields silently mixed
# across different rows (e.g. name from item 1, price from item 3).
PRODUCT_FIELDS = ["name", "sku", "ncm", "description", "price", "quantity", "discount"]
_PRODUCT_EXTRA_INSTRUCTIONS = (
    "If the document lists multiple product line items, extract only the "
    "FIRST one listed. Take every field value from that same line item — "
    "never combine values from different line items.\n"
)


def extract_product_fields(
    document_text: str,
    client: OllamaExtractionClient | None = None,
) -> dict[str, LlmFieldResult | None]:
    return extract_fields(
        document_text, None, "product", PRODUCT_FIELDS, client, extra_instructions=_PRODUCT_EXTRA_INSTRUCTIONS
    )
