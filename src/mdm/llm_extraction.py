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
            timeout=120.0,
        )
        response.raise_for_status()
        result: str = response.json()["response"]
        return result


def _build_prompt(document_text: str, cnpj_anchor: str | None) -> str:
    anchor_line = (
        f'The supplier\'s tax ID (CNPJ) is known to be: "{cnpj_anchor}". '
        "Use this to identify which party in the document is the supplier.\n"
        if cnpj_anchor
        else ""
    )
    fields = ", ".join(f'"{f}"' for f in SUPPLIER_FIELDS)
    return (
        "You are a document extraction assistant. Extract information about "
        "the SUPPLIER (the company issuing/sending this document) from the "
        "text below.\n"
        f"{anchor_line}"
        f"Return ONLY a flat JSON object with these exact keys: {fields}. "
        "Each value must be a plain string, not a nested object. Use null "
        "for any field you cannot find. Do not include any other text.\n\n"
        f'Document:\n"""\n{document_text}\n"""\n'
    )


def extract_supplier_fields(
    document_text: str,
    cnpj_anchor: str | None,
    client: OllamaExtractionClient | None = None,
) -> dict[str, LlmFieldResult | None]:
    client = client or OllamaExtractionClient()
    prompt = _build_prompt(document_text, cnpj_anchor)

    try:
        raw = client.generate_json(prompt)
        parsed = json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("LLM extraction call failed, treating all fields as not found: %s", exc)
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    results: dict[str, LlmFieldResult | None] = {}
    for field in SUPPLIER_FIELDS:
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
