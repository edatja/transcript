"""Parser for the IRS Return Transcript.

A Return Transcript shows the line items of a return as the IRS posted it.
Most lines appear twice::

    ADJUSTED GROSS INCOME:....................$164,940.00
    ADJUSTED GROSS INCOME PER COMPUTER:.......$164,940.00

The plain line is what the taxpayer reported.  "PER COMPUTER" is what the
IRS's own math produced.  When the two differ, the IRS changed the return --
that is exactly the kind of thing a preparer needs flagged, so differences
become warnings rather than being quietly averaged or dropped.
"""

from __future__ import annotations

import re

from ..fields import parse_money, split_label_value
from ..models import ReturnTranscript, SourceRef

_PER_COMPUTER = re.compile(r"\s+PER\s+COMPUTER$", re.IGNORECASE)
_FORM_NUMBER = re.compile(r"FORM\s+NUMBER:\s*(?P<v>\S+)", re.IGNORECASE)
_FILING_STATUS = re.compile(r"FILING\s+STATUS:\s*(?P<v>.+)", re.IGNORECASE)
_PERIOD = re.compile(
    r"Tax\s+Period\s+(?:Ending|Requested):\s*(?P<v>.+)", re.IGNORECASE
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _key(label: str) -> str:
    """Stable snake_case key for a return-transcript line label."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", label.strip().lower())
    return text.strip("_")


def parse_return_transcript(
    lines_with_pages: list[tuple[int, str]], source_file: str
) -> ReturnTranscript:
    """Parse a Return Transcript into its posted line items."""
    first_page = lines_with_pages[0][0] if lines_with_pages else 1
    ret = ReturnTranscript(source=SourceRef(file=source_file, page=first_page))
    per_computer: dict[str, object] = {}

    for _page, raw in lines_with_pages:
        line = raw.rstrip()
        if not line.strip():
            continue

        if not ret.form_number:
            m = _FORM_NUMBER.search(line)
            if m:
                ret.form_number = m.group("v").strip()
        if not ret.filing_status:
            m = _FILING_STATUS.search(line)
            if m:
                ret.filing_status = m.group("v").strip()
        if not ret.tax_year:
            m = _PERIOD.search(line)
            if m:
                y = _YEAR.search(m.group("v"))
                if y:
                    ret.tax_year = y.group(0)

        pair = split_label_value(line)
        if pair is None:
            continue
        label, value = pair
        if not value:
            continue
        ret.raw_fields[label] = value

        amount = parse_money(value)
        if amount is None:
            continue

        base = _PER_COMPUTER.sub("", label)
        key = _key(base)
        if _PER_COMPUTER.search(label):
            per_computer[key] = amount
        else:
            ret.line_items[key] = amount

    # A PER COMPUTER figure with no taxpayer-reported counterpart is still a
    # real number the IRS used; keep it rather than discarding it.
    for key, amount in per_computer.items():
        reported = ret.line_items.get(key)
        if reported is None:
            ret.line_items[key] = amount  # type: ignore[assignment]
        elif reported != amount:
            ret.warnings.append(
                f"IRS ADJUSTED '{key}': return reported {reported:,.2f} but "
                f"IRS computed {amount:,.2f} (difference "
                f"{amount - reported:+,.2f}) -- the IRS figure governs"
            )
            ret.line_items[f"{key}__per_computer"] = amount  # type: ignore[assignment]

    if not ret.line_items:
        ret.warnings.append(
            "no numeric line items parsed -- unexpected Return Transcript layout"
        )
    return ret
