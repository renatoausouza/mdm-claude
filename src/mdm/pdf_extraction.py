from dataclasses import dataclass

import fitz


@dataclass
class PdfPage:
    page_number: int  # 1-indexed
    text: str
    _page: fitz.Page

    def find_bbox(self, substring: str, occurrence_index: int = 0) -> tuple[float, float, float, float] | None:
        """Locate the bounding box of the occurrence_index'th occurrence of
        substring on this page (0 = first), for provenance on a regex
        match's exact text. A value repeated on a page (e.g. a CNPJ in
        both a header and footer) needs its own occurrence's bbox, not
        always the first one's."""
        matches = self._page.search_for(substring)
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
        PdfPage(page_number=i + 1, text=page.get_text(flags=fitz.TEXTFLAGS_SEARCH), _page=page)
        for i, page in enumerate(doc)
    ]
