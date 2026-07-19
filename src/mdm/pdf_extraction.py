from dataclasses import dataclass

import fitz


@dataclass
class PdfPage:
    page_number: int  # 1-indexed
    text: str
    _page: fitz.Page

    def find_bbox(self, substring: str, occurrence_index: int = 0) -> tuple[float, float, float, float] | None:
        """Locate the bounding box of the occurrence_index'th occurrence of
        substring on this page (0 = first, in reading order), for
        provenance on a regex match's exact text. A value repeated on a
        page (e.g. a CNPJ in both a header and footer) needs its own
        occurrence's bbox, not always the first one's.

        occurrence_index is computed by the caller (regex_candidates.py)
        by counting matches in order through this page's sort=True'd
        .text — but search_for() has no sort option of its own and
        returns matches in PDF draw order, which doesn't necessarily match
        visual/reading order (that's the whole premise of #14). Sorting
        the results here by position (top-to-bottom, left-to-right) keeps
        occurrence_index meaning the same thing on both sides."""
        matches = sorted(self._page.search_for(substring), key=lambda rect: (rect.y0, rect.x0))
        if occurrence_index >= len(matches):
            return None
        rect = matches[occurrence_index]
        return (rect.x0, rect.y0, rect.x1, rect.y1)


def extract_pdf_pages(content: bytes) -> list[PdfPage]:
    doc = fitz.open(stream=content, filetype="pdf")
    # Same flag set as search_for()'s default (fitz.TEXTFLAGS_SEARCH) so text
    # used for regex matching and text used for bbox lookup are tokenized
    # identically — get_text()'s own default preserves ligatures (e.g. "ffi"
    # as one glyph) while search_for()'s does not, which silently truncated
    # regex matches spanning a ligature (e.g. "o[ffi]cial@x.com").
    return [
        # sort=True reorders spans into visual reading order (top-to-bottom,
        # left-to-right) rather than PDF content-stream draw order. Dense
        # form-style documents (DANFE/NFS-e invoices) are commonly generated
        # with fields drawn in an order that doesn't match their printed
        # layout — without this, "nearby text" heuristics downstream (regex
        # context, role-tagging) see values and their labels in the wrong
        # order relative to each other (#14).
        PdfPage(page_number=i + 1, text=page.get_text(flags=fitz.TEXTFLAGS_SEARCH, sort=True), _page=page)
        for i, page in enumerate(doc)
    ]
