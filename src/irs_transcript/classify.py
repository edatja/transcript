"""Identify which of the five IRS transcript products a PDF is.

The IRS issues these through Get Transcript / TDS, and each has a different
internal layout:

  Wage & Income   every information return filed UNDER the taxpayer's TIN
                  (W-2, 1099-*, 1098-*, 5498, K-1). The one you tie a return
                  to when you want to be sure nothing was missed.
  Return          the line items of a return AS THE IRS POSTED IT.
  Account         assessments, payments, credits, notices -- the transaction
                  code ledger. Where estimated payments and refunds live.
  Record of Acct  Return + Account in one document.
  Tax Compliance  filing-status-by-year summary, little dollar detail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class TranscriptType:
    WAGE_AND_INCOME = "wage_and_income"
    RETURN = "return"
    ACCOUNT = "account"
    RECORD_OF_ACCOUNT = "record_of_account"
    TAX_COMPLIANCE = "tax_compliance"
    UNKNOWN = "unknown"


# Order matters: Record of Account contains the words "Return Transcript" and
# "Account Transcript" inside it, so it has to be tested first.
_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (TranscriptType.RECORD_OF_ACCOUNT, re.compile(r"Record\s+of\s+Account", re.I)),
    (TranscriptType.WAGE_AND_INCOME, re.compile(r"Wage\s+and\s+Income\s+Transcript", re.I)),
    (TranscriptType.RETURN, re.compile(r"(?:Tax\s+)?Return\s+Transcript", re.I)),
    (TranscriptType.ACCOUNT, re.compile(r"Account\s+Transcript", re.I)),
    (TranscriptType.TAX_COMPLIANCE, re.compile(r"Tax\s+Compliance\s+Report", re.I)),
]

# Header metadata that appears on the first page of every product.
_HEADER_PATTERNS: dict[str, re.Pattern[str]] = {
    "request_date": re.compile(r"Request\s+Date:\s*(.+)", re.I),
    "response_date": re.compile(r"Response\s+Date:\s*(.+)", re.I),
    "tracking_number": re.compile(r"Tracking\s+Number:\s*(.+)", re.I),
    "taxpayer_tin": re.compile(r"(?:SSN|EIN|TIN)\s+Provided:\s*(.+)", re.I),
    "tax_period": re.compile(r"Tax\s+Period\s+(?:Requested|Ending):\s*(.+)", re.I),
}

# "December, 2024" / "Dec. 31, 2024" / "2024" / "12-31-2024"
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


@dataclass
class TranscriptHeader:
    transcript_type: str = TranscriptType.UNKNOWN
    request_date: str | None = None
    response_date: str | None = None
    tracking_number: str | None = None
    taxpayer_tin: str | None = None
    tax_period: str | None = None
    tax_years: list[str] = field(default_factory=list)


def detect_type(text: str) -> str:
    """Return the TranscriptType for a document's text."""
    # Only look at the front of the document. A Wage & Income transcript can
    # mention other product names deep inside a form block.
    head = "\n".join(text.splitlines()[:80])
    for kind, pattern in _TYPE_PATTERNS:
        if pattern.search(head):
            return kind
    # Fall back to a full scan before giving up.
    for kind, pattern in _TYPE_PATTERNS:
        if pattern.search(text):
            return kind
    return TranscriptType.UNKNOWN


def extract_years(text: str) -> list[str]:
    """Every distinct tax year named in a 'Tax Period' header, in order.

    Only the Tax Period lines are scanned -- not the whole document -- because
    form blocks contain dates (payment dates, "as of" dates) that are not tax
    years and would produce phantom years.
    """
    years: list[str] = []
    for line in text.splitlines():
        m = _HEADER_PATTERNS["tax_period"].search(line)
        if not m:
            continue
        found = _YEAR.search(m.group(1))
        if found and found.group(0) not in years:
            years.append(found.group(0))
    return years


def parse_header(text: str) -> TranscriptHeader:
    """Pull the product type and request metadata off the transcript header."""
    header = TranscriptHeader(transcript_type=detect_type(text))
    head_lines = text.splitlines()[:80]

    for field_name, pattern in _HEADER_PATTERNS.items():
        if field_name == "tax_period":
            continue
        for line in head_lines:
            m = pattern.search(line)
            if m:
                value = m.group(1).strip().strip(".").strip()
                if value:
                    setattr(header, field_name, value)
                break

    for line in head_lines:
        m = _HEADER_PATTERNS["tax_period"].search(line)
        if m:
            header.tax_period = m.group(1).strip()
            break

    header.tax_years = extract_years(text)
    return header


def describe(kind: str) -> str:
    """One-line plain-English description, for CLI output."""
    return {
        TranscriptType.WAGE_AND_INCOME:
            "Wage & Income -- information returns filed under this TIN",
        TranscriptType.RETURN:
            "Return Transcript -- line items of the return as posted",
        TranscriptType.ACCOUNT:
            "Account Transcript -- assessments, payments, credits ledger",
        TranscriptType.RECORD_OF_ACCOUNT:
            "Record of Account -- Return + Account combined",
        TranscriptType.TAX_COMPLIANCE:
            "Tax Compliance Report -- filing status by year",
        TranscriptType.UNKNOWN:
            "Unrecognized -- not an IRS transcript, or an unusual format",
    }.get(kind, kind)
