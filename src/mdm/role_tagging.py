import re
from dataclasses import dataclass

from mdm.pdf_extraction import PdfPage
from mdm.regex_candidates import RegexCandidate

_ROLE_LABELS: dict[str, list[str]] = {
    "supplier": ["emitente", "fornecedor"],
    "client": ["destinatario", "destinatário", "cliente", "comprador", "tomador"],
    "transporter": ["transportador", "transportadora"],
    "intermediary": ["intermediario", "intermediário", "representante"],
    "branch": ["filial"],
}

# Flattened once at import time, with word-boundary patterns: used by both
# searches below, so a label like "cliente" or "comprador" only ever
# matches as its own word, never as a substring inside an unrelated
# longer word.
_LABEL_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (role, label, re.compile(r"\b" + re.escape(label) + r"\b"))
    for role, labels in _ROLE_LABELS.items()
    for label in labels
]


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
    for role, label, pattern in _LABEL_PATTERNS:
        for match in pattern.finditer(normalized):
            distance = abs(match.start() - anchor_offset)
            if best is None or distance < best[0]:
                best = (distance, role, label)
    if best is None:
        return None
    return best[1], best[2]


def _find_preceding_line_start_label(text: str) -> tuple[str, str] | None:
    """Find the role label on the nearest line (within `text`, scanned
    backward) that STARTS with that label — used for the backward
    fallback in tag_roles once the same-line check has failed, to walk
    back through the page (in true reading order, per #14's ordering fix)
    to the nearest preceding section header, however many lines above it
    sits. Requiring the label to start its own line (e.g. "Destinatário /
    Remetente", "Tomador do(s) Serviço(s)") — rather than matching
    anywhere in `text` — is what distinguishes a real section header from
    a role word used incidentally in unrelated running prose (e.g.
    "...exceto pelo comprador original." in return-policy boilerplate): a
    real false-positive risk once this search scans more than one line."""
    for line in reversed(text.split("\n")):
        stripped = line.strip().lower()
        if not stripped:
            continue
        for role, label, pattern in _LABEL_PATTERNS:
            if pattern.match(stripped):
                return role, label
    return None


def _line_bounds(text: str, position: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    return line_start, line_end


def tag_roles(candidates: list[RegexCandidate], pages: list[PdfPage]) -> list[TaggedParty]:
    pages_by_number = {page.page_number: page for page in pages}
    tax_id_candidates = [c for c in candidates if c.kind in ("cnpj", "cpf")]

    # Positions of every tax-ID candidate on each page, sorted by where
    # they actually sit on the page (not the order they appear in
    # `candidates`, which is grouped by kind — cnpj, then cpf — not by
    # position). Lets the backward fallback below stop at the end of the
    # nearest EARLIER candidate's own line, so a label belonging to one
    # party can never bleed onto a different, later party that has no
    # real label of its own (#14 regression: an unlabeled reference CNPJ
    # several sections after a real "Transportador" block must not
    # inherit "transporter").
    positions_by_page: dict[int, list[int]] = {}
    for c in tax_id_candidates:
        positions_by_page.setdefault(c.page_number, []).append(c.match_start)
    for positions in positions_by_page.values():
        positions.sort()

    parties = []
    for candidate in tax_id_candidates:
        page = pages_by_number[candidate.page_number]

        # Scoped to the same line as the tax ID first (the common case: a
        # label and the ID appear on one line, e.g. "Fornecedor CNPJ: ...").
        line_start, line_end = _line_bounds(page.text, candidate.match_start)
        found = _find_role_label(page.text[line_start:line_end], candidate.match_start - line_start)

        if found is None and line_start > 0:
            # Falls back to the nearest preceding line that STARTS with a
            # role label — real invoices commonly put a section header
            # ("Destinatário / Remetente") several lines above the block
            # of fields it labels, not on the line directly above the
            # value. Bounded to [nearest earlier candidate's line end,
            # this candidate's line start): a closer, more relevant
            # header always overrides a more distant one, a label
            # appearing *after* the candidate is never considered, and
            # the search never crosses into a different, earlier party's
            # own line.
            positions = positions_by_page[candidate.page_number]
            idx = positions.index(candidate.match_start)
            lower_bound = 0
            if idx > 0:
                _, lower_bound = _line_bounds(page.text, positions[idx - 1])
            found = _find_preceding_line_start_label(page.text[lower_bound:line_start])

        if found is None:
            parties.append(TaggedParty(tax_id=candidate, role="unknown", role_evidence=None))
        else:
            role, label = found
            evidence = RoleEvidence(matched_label=label, location=f"page {candidate.page_number}, nearby text")
            parties.append(TaggedParty(tax_id=candidate, role=role, role_evidence=evidence))
    return parties
