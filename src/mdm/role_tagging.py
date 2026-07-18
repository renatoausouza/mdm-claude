from dataclasses import dataclass

from mdm.pdf_extraction import PdfPage
from mdm.regex_candidates import RegexCandidate

_ROLE_LABELS: dict[str, list[str]] = {
    "supplier": ["emitente", "fornecedor"],
    "client": ["destinatario", "destinatário", "cliente", "comprador"],
    "transporter": ["transportador", "transportadora"],
    "intermediary": ["intermediario", "intermediário", "representante"],
    "branch": ["filial"],
}


@dataclass
class RoleEvidence:
    matched_label: str
    location: str  # e.g. "page 1, nearby text"


@dataclass
class TaggedParty:
    tax_id: RegexCandidate
    role: str
    role_evidence: RoleEvidence | None


def _find_role_label(context: str, anchor_offset: int) -> tuple[str, str] | None:
    """Find the role label CLOSEST to anchor_offset within context — not
    just the first role that happens to match in a fixed priority order.
    Without this, a line naming two parties (e.g. "Fornecedor CNPJ: X ...
    Destinatário CNPJ: Y") would tag both CNPJs with whichever role is
    checked first in _ROLE_LABELS, regardless of which label is actually
    nearest to each one."""
    normalized = context.lower()
    best: tuple[int, str, str] | None = None  # (distance, role, label)
    for role, labels in _ROLE_LABELS.items():
        for label in labels:
            start = 0
            while (idx := normalized.find(label, start)) != -1:
                distance = abs(idx - anchor_offset)
                if best is None or distance < best[0]:
                    best = (distance, role, label)
                start = idx + 1
    if best is None:
        return None
    return best[1], best[2]


def _line_bounds(text: str, position: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    return line_start, line_end


def tag_roles(candidates: list[RegexCandidate], pages: list[PdfPage]) -> list[TaggedParty]:
    pages_by_number = {page.page_number: page for page in pages}
    parties = []
    for candidate in candidates:
        if candidate.kind != "cnpj":
            continue
        page = pages_by_number[candidate.page_number]

        # Scoped to the same line as the tax ID first (the common case: a
        # label and the ID appear on one line, e.g. "Fornecedor CNPJ: ...").
        # Falls back to the immediately preceding line (the label sits on
        # its own line just above the ID) only if nothing is found there —
        # a fixed-width character window would instead bleed into
        # neighboring parties' labels on a multi-party document.
        line_start, line_end = _line_bounds(page.text, candidate.match_start)
        found = _find_role_label(page.text[line_start:line_end], candidate.match_start - line_start)

        if found is None and line_start > 0:
            prev_line_start, _ = _line_bounds(page.text, line_start - 1)
            prev_line = page.text[prev_line_start:line_start]
            found = _find_role_label(prev_line, len(prev_line))

        if found is None:
            parties.append(TaggedParty(tax_id=candidate, role="unknown", role_evidence=None))
        else:
            role, label = found
            evidence = RoleEvidence(matched_label=label, location=f"page {candidate.page_number}, nearby text")
            parties.append(TaggedParty(tax_id=candidate, role=role, role_evidence=evidence))
    return parties
