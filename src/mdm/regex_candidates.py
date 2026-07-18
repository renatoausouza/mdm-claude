import re
from dataclasses import dataclass

from mdm.cnpj_validation import is_valid_cnpj
from mdm.field_validation import EMAIL_PATTERN
from mdm.pdf_extraction import PdfPage

# Formatted only (no bare-14-digit fallback): an unformatted \d{14} pattern
# matches any 14 consecutive digits (an order number, a barcode fragment),
# and — combined with a nearby role label and no checksum check — that
# false positive would get asserted to the LLM as the supplier's real tax
# ID. The formatted punctuation shape is a much stronger signal on its own,
# and is_valid_cnpj() below still checksum-validates it as a second layer.
_CNPJ_PATTERN = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_PHONE_PATTERN = re.compile(r"\(\d{2}\)\s?\d{4,5}-\d{4}")

_PATTERNS: dict[str, re.Pattern[str]] = {
    "cnpj": _CNPJ_PATTERN,
    "email": EMAIL_PATTERN,
    "phone": _PHONE_PATTERN,
}

# Known limitation, not fixed here: if PyMuPDF's text extraction inserts a
# line break in the middle of a value (e.g. a CNPJ wrapped across two lines
# by a narrow table cell), these regexes won't match across the embedded
# newline and the candidate is silently missed entirely — not even flagged
# role:unknown. Reconstructing wrapped tokens across line breaks correctly
# (without also merging genuinely distinct values on adjacent lines) needs
# real layout analysis, disproportionate to this ticket's scope.


@dataclass
class RegexCandidate:
    value: str
    kind: str
    page_number: int
    bbox: tuple[float, float, float, float] | None
    match_start: int  # character offset within the page's text, for role-tagging context


def find_candidates(pages: list[PdfPage]) -> list[RegexCandidate]:
    candidates = []
    for page in pages:
        # Tracks how many times each (kind, value) pair has already been
        # seen on this page, so a value repeated on the page (e.g. a CNPJ
        # in both a header and footer) gets its OWN occurrence's bbox
        # rather than always the first one's.
        occurrence_counts: dict[tuple[str, str], int] = {}
        for kind, pattern in _PATTERNS.items():
            for match in pattern.finditer(page.text):
                value = match.group()
                if kind == "cnpj" and not is_valid_cnpj(value):
                    continue
                occurrence_index = occurrence_counts.get((kind, value), 0)
                occurrence_counts[(kind, value)] = occurrence_index + 1
                candidates.append(
                    RegexCandidate(
                        value=value,
                        kind=kind,
                        page_number=page.page_number,
                        bbox=page.find_bbox(value, occurrence_index),
                        match_start=match.start(),
                    )
                )
    return candidates
