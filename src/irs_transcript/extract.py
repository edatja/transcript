"""PDF -> text.  The only module in this project that opens a PDF.

Everything downstream works on plain strings, which is what makes the parsers
testable against synthetic fixtures instead of real taxpayer documents.

Design notes
------------
IRS "Get Transcript" PDFs are generated documents with a real text layer, so
extraction is exact -- we are reading the characters the IRS embedded, not
guessing at pixels.  That is why this pipeline can promise that every number
traces to a literal string in the file.

Scanned or faxed transcripts have no text layer.  We detect that and say so
loudly rather than silently returning empty pages, because an empty parse
that looks like "no income documents found" is the most dangerous possible
failure mode for this tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Three or more dots in a row -- possibly separated by the spaces pdfplumber
# inserts between glyphs -- is always a cosmetic leader, never content.
# Collapsing them first means fields.py only has to handle one shape.
#
# The separator class is [ \t] and NOT \s: a leader that ends a line with no
# value after it ("Total Distribution:........") sits directly before a
# newline, and an \s here would swallow that newline and weld the next
# transcript line onto this one -- silently losing every field on it.
_LEADER_RUN = re.compile(r"(?:\.[ \t]*){3,}")

# Non-breaking and other exotic spaces that PDF text layers like to emit.
_ODD_SPACE = re.compile(r"[  -​﻿]")


@dataclass
class Page:
    number: int      # 1-based, matches a PDF viewer
    text: str
    char_count: int

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @property
    def has_text_layer(self) -> bool:
        # A transcript page with a real text layer runs to hundreds of
        # characters. A handful of stray characters means it is an image.
        return self.char_count >= 40


@dataclass
class Document:
    path: str
    pages: list[Page]
    warnings: list[str]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def lines_with_pages(self) -> list[tuple[int, str]]:
        """Every line paired with its 1-based page number, for traceability."""
        out: list[tuple[int, str]] = []
        for page in self.pages:
            for line in page.lines:
                out.append((page.number, line))
        return out


def clean_text(text: str) -> str:
    """Normalize a raw extracted page so the parsers see one consistent shape."""
    text = _ODD_SPACE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _LEADER_RUN.sub("....", text)
    # Trim trailing whitespace per line but keep leading indentation, which
    # carries column meaning in Account Transcript transaction tables.
    return "\n".join(line.rstrip() for line in text.split("\n"))


def extract_pdf(path: str | Path, *, layout: bool = False) -> Document:
    """Extract text from every page of ``path``.

    ``layout=True`` asks pdfplumber to preserve horizontal positioning with
    padding spaces.  It helps with column tables (Account Transcript
    transactions, 1095-A monthly grids) and hurts the dot-leader lines, so it
    is off by default and turned on only by the parsers that want it.
    """
    import pdfplumber  # imported lazily so --help works without the dep

    path = Path(path)
    warnings: list[str] = []
    pages: list[Page] = []

    try:
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    raw = page.extract_text(layout=layout) or ""
                except Exception as exc:  # one bad page must not lose the rest
                    raw = ""
                    warnings.append(f"page {index}: extraction failed ({exc})")
                text = clean_text(raw)
                pages.append(
                    Page(number=index, text=text, char_count=len(raw.strip()))
                )
    except Exception as exc:
        message = str(exc)
        if "password" in message.lower() or "encrypt" in message.lower():
            raise RuntimeError(
                f"{path.name} is password-protected. Remove the password "
                f"(open it in a PDF viewer and re-save) and try again."
            ) from exc
        raise RuntimeError(f"Could not open {path.name}: {exc}") from exc

    if not pages:
        warnings.append("PDF contains no pages")
    else:
        blank = [p.number for p in pages if not p.has_text_layer]
        if len(blank) == len(pages):
            warnings.append(
                "NO TEXT LAYER on any page -- this looks like a scan or photo "
                "of a transcript, not a PDF downloaded from IRS.gov. Nothing "
                "can be parsed from it. Either download the original from "
                "IRS.gov Get Transcript, or install the optional OCR extras "
                "(see requirements.txt) and re-run."
            )
        elif blank:
            warnings.append(
                f"pages {blank} have no text layer and were skipped -- "
                f"amounts on those pages are MISSING from this parse"
            )

    return Document(path=str(path), pages=pages, warnings=warnings)


def extract_text_only(path: str | Path, page: int | None = None) -> str:
    """Debug helper: the extracted text of one page, or all pages."""
    doc = extract_pdf(path)
    if page is None:
        return doc.text
    for p in doc.pages:
        if p.number == page:
            return p.text
    raise ValueError(f"page {page} not found (document has {len(doc.pages)})")
