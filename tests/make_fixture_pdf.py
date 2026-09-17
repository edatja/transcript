"""Turn a fixture .txt into a real PDF, with no third-party dependency.

Why this exists: the parsers are unit-tested against text, but the thing that
actually breaks in production is PDF extraction -- glyph spacing, dot leaders,
line ordering. Testing against a genuine PDF that pdfplumber has to open keeps
that path honest.

Writing raw PDF is ugly but it means the test suite needs no PDF *writer*
dependency, and a synthetic fixture is the only kind of transcript that may
ever be committed to this repository.

Usage:
    python3 tests/make_fixture_pdf.py tests/fixtures/wage_income_2024.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

PAGE_WIDTH, PAGE_HEIGHT = 612, 792
MARGIN_X, MARGIN_TOP = 36, 756
FONT_SIZE, LEADING = 8, 9.6
LINES_PER_PAGE = int((MARGIN_TOP - 36) / LEADING)


def _escape(text: str) -> str:
    """PDF string literals escape backslash and both parentheses.

    Note: the base-14 Courier encoding maps the ASCII apostrophe to U+2019, so
    text extracted back out carries a curly quote. That is a property of this
    generator, not of real transcripts -- and it is harmless, because the
    parsers match labels on words and normalise punctuation away.
    """
    return (
        text.replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )


def _overlay_stream(line_index: int, text: str) -> str:
    """Draw viewer chrome in a different font, overlapping a transcript line.

    Reproduces what the IRS Get Transcript web viewer bakes in when a
    transcript is saved from the browser: button labels drawn at the same
    vertical position as a transcript line, whose glyphs pdfplumber then
    interleaves into that line's text.
    """
    y = MARGIN_TOP - line_index * LEADING
    return (
        f"\nBT /F2 {FONT_SIZE + 2} Tf {MARGIN_X + 60} {y} Td "
        f"({_escape(text)}) Tj ET"
    )


def _content_stream(lines: list[str], overlay: tuple[int, str] | None = None
                    ) -> bytes:
    parts = [f"BT /F1 {FONT_SIZE} Tf {LEADING} TL {MARGIN_X} {MARGIN_TOP} Td"]
    for line in lines:
        # Tj draws the line, T* advances one leading. An empty line still
        # advances, which preserves the blank lines between form blocks.
        parts.append(f"({_escape(line)}) Tj T*")
    parts.append("ET")
    body = "\n".join(parts)
    if overlay is not None:
        body += _overlay_stream(*overlay)
    return body.encode("latin-1", errors="replace")


def text_to_pdf(text: str, out_path: Path,
                overlay: tuple[int, str] | None = None) -> Path:
    all_lines = text.splitlines()
    pages = [
        all_lines[i:i + LINES_PER_PAGE]
        for i in range(0, max(len(all_lines), 1), LINES_PER_PAGE)
    ] or [[]]

    objects: list[bytes] = []          # 1-indexed on write
    page_ids = [3 + 2 * i for i in range(len(pages))]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    )

    font_id = 3 + 2 * len(pages)
    overlay_font_id = font_id + 1
    for index, page_lines in enumerate(pages):
        content_id = page_ids[index] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_id} 0 R "
            f"/F2 {overlay_font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        # The overlay belongs on whichever page holds that line.
        page_overlay = None
        if overlay is not None:
            start = index * LINES_PER_PAGE
            if start <= overlay[0] < start + LINES_PER_PAGE:
                page_overlay = (overlay[0] - start, overlay[1])
        stream = _content_stream(page_lines, page_overlay)
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    # A DIFFERENT font, which is exactly how the chrome filter identifies it.
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()

    out_path.write_bytes(bytes(out))
    return out_path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for item in argv:
        src = Path(item)
        dst = src.with_suffix(".pdf")
        text_to_pdf(src.read_text(), dst)
        print(f"{src} -> {dst} ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
