"""#21: chat query interface. The LLM's ONLY job is proposing a
constrained, whitelisted structured filter — never raw or sandboxed SQL,
never a live database connection, never the query results (one LLM call
per question, not two: this local, CPU-only model already runs 50-90s per
call elsewhere in this app, and re-exposing already-registered PII to the
model for a phrasing-only pass buys nothing). This is the exact same
trust boundary D14 already establishes for document extraction — the LLM
proposes structure, deterministic code decides what happens next.

Every value the LLM proposes is validated against an explicit allowlist
in propose_query_filter() below before anything executes. Anything
invalid — an unknown domain, an empty search term, malformed JSON, a
non-dict response — means "no filter was produced," never a best-effort
guess or partial execution."""

import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from mdm.auth import get_current_user
from mdm.db import User, get_session
from mdm.domains import DOMAIN_SPECS
from mdm.duplicates import MasterRecordSearchResult, search_records
from mdm.llm_extraction import OllamaExtractionClient
from mdm.review import _require_approver_or_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# Matches #17's own search page size cap — a chat answer isn't a bulk
# export, and this keeps a hallucinated/unreasonable limit from ever
# reaching the query.
MAX_LIMIT = 50
_DEFAULT_LIMIT = 10


@dataclass
class QueryFilter:
    domain: str
    contains: str
    limit: int


def _build_prompt(question: str) -> str:
    domains = ", ".join(f'"{d}"' for d in DOMAIN_SPECS)
    return (
        "You translate a natural-language question about a company's "
        "registered master data (Supplier/Client/Product records) into a "
        "single structured search filter. You do NOT answer the question "
        "yourself, and you never generate a database query of any kind — "
        "you only propose a filter shape for other code to execute.\n"
        f"Valid domains: {domains}.\n"
        'Return ONLY a flat JSON object with these exact keys: "domain" '
        "(one of the valid domains), \"contains\" (a short substring from "
        "the question to search for across that domain's records), "
        '"limit" (a positive integer — how many results were asked for; '
        "use 10 if not specified). "
        "If the question cannot be expressed this way, return null for "
        "all three keys. Do not include any other text.\n\n"
        f'Question: "{question}"\n'
    )


def propose_query_filter(question: str, client: OllamaExtractionClient | None = None) -> QueryFilter | None:
    client = client or OllamaExtractionClient()
    prompt = _build_prompt(question)

    try:
        raw = client.generate_json(prompt)
        parsed = json.loads(raw)
    except Exception as exc:  # the LLM's output is untrusted input; must never crash the request
        logger.warning("Chat query filter generation failed: %s", exc)
        return None

    if not isinstance(parsed, dict):
        return None

    domain = parsed.get("domain")
    contains = parsed.get("contains")
    limit = parsed.get("limit")

    if not isinstance(domain, str) or domain not in DOMAIN_SPECS:
        return None
    if not isinstance(contains, str) or not contains.strip():
        return None

    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
        limit = _DEFAULT_LIMIT
    limit = min(int(limit), MAX_LIMIT)

    return QueryFilter(domain=domain, contains=contains.strip(), limit=limit)


class ChatQueryRequest(BaseModel):
    question: str


class ChatQueryResponse(BaseModel):
    understood: bool
    filter_domain: str | None = None
    filter_contains: str | None = None
    results: list[MasterRecordSearchResult] = []


@router.post("/chat/query", response_model=ChatQueryResponse)
def chat_query(payload: ChatQueryRequest, current_user: User = Depends(get_current_user)) -> ChatQueryResponse:
    """Same PII-viewing rationale as #17's search endpoint (approver or
    admin only) — this surfaces the same underlying record data, just
    through a natural-language front end. Read-only: nothing on this path
    can create, update, or delete a record."""
    _require_approver_or_admin(current_user)

    proposed = propose_query_filter(payload.question)
    if proposed is None:
        return ChatQueryResponse(understood=False)

    with get_session() as session:
        search_response = search_records(session, proposed.domain, proposed.contains, offset=0, limit=proposed.limit)

    return ChatQueryResponse(
        understood=True,
        filter_domain=proposed.domain,
        filter_contains=proposed.contains,
        results=search_response.results,
    )
