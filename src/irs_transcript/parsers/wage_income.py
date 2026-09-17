"""Parser for the IRS Wage & Income Transcript.

This is the transcript that answers "did I miss any income?".  It lists every
information return third parties filed under the taxpayer's TIN: W-2s, the
whole 1099 family, 1098s, 5498s, K-1s, SSA-1099.

Document shape
--------------
The transcript is a run of form blocks.  Each block starts with a bare form
title line (no colon), then a payer party, then a recipient party, then the
money fields as dot-leader lines::

    Form W-2 Wage and Tax Statement
    Employer:
    Employer Identification Number (EIN):XX-XXX1234
    ACME CORP
    123 MAIN ST
    ANYTOWN, ST 12345
    Employee:
    Employee's Social Security Number:XXX-XX-1234
    JOHN DOE
    Submission Type:....................................Original document
    Wages, Tips and Other Compensation:.................$50,000.00
    Federal Income Tax Withheld:........................$5,000.00

Blocks are delimited only by the next form title, so segmentation is the
first job and everything else follows from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from decimal import Decimal

from ..aliases import field_for, indicator_for
from ..fields import is_noise, parse_money, split_label_value
from ..models import IncomeDocument, SourceRef

# A form block header: starts the line, names a form, carries no colon.
# Longer codes must precede their prefixes (W-2G before W-2, 1098-E before
# 1098, 5498-SA before 5498) or the shorter one wins and mislabels the block.
_FORM_HEADER = re.compile(
    r"^\s*Form\s+(?P<code>"
    r"W-2G|W-2"
    r"|1099-[A-Z]{1,4}"
    r"|1098-[A-Z]|1098"
    r"|1095-[ABC]"
    r"|5498-[A-Z]{2,3}|5498"
    r"|SSA-1099|RRB-1099"
    r"|1042-S"
    r")\b",
    re.IGNORECASE,
)

_K1_HEADER = re.compile(
    r"^\s*Schedule\s+K-1\s*\(?\s*Form\s+(?P<code>1065|1120-?S|1041)\s*\)?",
    re.IGNORECASE,
)

# Party section headers. The line is just the word and a colon.
_PAYER_SECTIONS = {
    "employer", "payer", "payer s name", "filer", "lender", "trustee",
    "issuer", "creditor", "servicer", "insurer", "corporation",
    "partnership", "estate or trust", "marketplace", "donee",
    "payer of record", "plan administrator", "service provider",
}
_RECIPIENT_SECTIONS = {
    "employee", "recipient", "borrower", "payer borrower", "student",
    "participant", "beneficiary", "payee", "debtor", "winner",
    "transferor", "covered individual", "recipient s name", "shareholder",
    "partner", "account holder",
}

# Any label naming a TIN, on either side of the transaction.
_TIN_LABEL = re.compile(
    r"identification\s+number|social\s+security\s+number|\bEIN\b|\bFIN\b"
    r"|\bTIN\b|taxpayer\s+id",
    re.IGNORECASE,
)

_TAX_PERIOD = re.compile(r"Tax\s+Period\s+(?:Requested|Ending):\s*(.+)", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass
class _Party:
    name: str | None = None
    tin: str | None = None
    address: list[str] = dc_field(default_factory=list)


@dataclass
class _Block:
    form_type: str
    lines: list[str]
    page: int
    tax_year: str | None


def _form_code(line: str) -> str | None:
    """Return the normalized form code if ``line`` is a block header."""
    if ":" in line:
        # Headers never carry a colon; a colon means this is a data line that
        # happens to mention a form name.
        return None
    m = _FORM_HEADER.match(line)
    if m:
        return m.group("code").upper().replace("SSA-1099", "SSA-1099")
    m = _K1_HEADER.match(line)
    if m:
        code = m.group("code").upper().replace("1120S", "1120-S")
        return f"K-1 ({code})"
    return None


def _segment(lines_with_pages: list[tuple[int, str]]) -> list[_Block]:
    """Split the document into one block per information return."""
    blocks: list[_Block] = []
    current: _Block | None = None
    tax_year: str | None = None

    for page, line in lines_with_pages:
        period = _TAX_PERIOD.search(line)
        if period:
            found = _YEAR.search(period.group(1))
            if found:
                tax_year = found.group(0)
            # A tax period line is header furniture, not block content.
            continue

        code = _form_code(line)
        if code:
            current = _Block(form_type=code, lines=[], page=page, tax_year=tax_year)
            blocks.append(current)
            continue

        if current is not None and not is_noise(line):
            current.lines.append(line)

    return blocks


def _is_party_header(label: str, value: str) -> str | None:
    """'payer' / 'recipient' if this label opens a party section."""
    if value.strip():
        return None  # a party header has nothing after the colon
    key = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    if key in _PAYER_SECTIONS:
        return "payer"
    if key in _RECIPIENT_SECTIONS:
        return "recipient"
    return None


def _parse_block(block: _Block, source_file: str) -> IncomeDocument:
    doc = IncomeDocument(
        form_type=block.form_type,
        tax_year=block.tax_year,
        source=SourceRef(file=source_file, page=block.page),
    )
    payer, recipient = _Party(), _Party()
    parties = {"payer": payer, "recipient": recipient}
    active: str | None = None
    duplicated: set[str] = set()

    for raw in block.lines:
        pair = split_label_value(raw)

        if pair is None:
            # A line with no colon inside a party section is the party's name
            # (first one) or an address line (the rest).
            text = raw.strip()
            if active and text:
                party = parties[active]
                if party.name is None:
                    party.name = text
                else:
                    party.address.append(text)
            continue

        label, value = pair

        party_kind = _is_party_header(label, value)
        if party_kind:
            active = party_kind
            continue

        if active and _TIN_LABEL.search(label):
            parties[active].tin = value or None
            continue

        # Any other labelled field ends the party section.
        active = None

        # Keep the literal text of every field, mapped or not.
        key = label
        if key in doc.raw_fields:
            n = 2
            while f"{key} ({n})" in doc.raw_fields:
                n += 1
            key = f"{key} ({n})"
        doc.raw_fields[key] = value

        indicator = indicator_for(label)
        if indicator == "submission_type":
            doc.submission_type = value or None
            continue
        if indicator == "account_number":
            doc.account_number = value or None
            continue

        normalized = field_for(block.form_type, label)
        if not normalized:
            continue
        amount = parse_money(value)
        if amount is None:
            continue
        if normalized in doc.amounts:
            # Legitimately happens when a form carries per-state rows; summing
            # is right there. Flagged either way so the preparer can look.
            doc.amounts[normalized] += amount
            duplicated.add(normalized)
        else:
            doc.amounts[normalized] = amount

    for name in sorted(duplicated):
        doc.warnings.append(
            f"'{name}' appeared more than once in this block and the values "
            f"were summed to {doc.amounts[name]:.2f} -- verify against the PDF"
        )

    doc.payer_name = payer.name
    doc.payer_tin = payer.tin
    doc.recipient_name = recipient.name
    doc.recipient_tin = recipient.tin
    if payer.address:
        doc.raw_fields["_payer_address"] = ", ".join(payer.address)
    if recipient.address:
        doc.raw_fields["_recipient_address"] = ", ".join(recipient.address)

    if not doc.amounts:
        doc.warnings.append(
            "no recognized dollar amounts in this block -- it may be an "
            "unsupported form layout; check raw_fields"
        )
    return doc


def parse_wage_and_income(
    lines_with_pages: list[tuple[int, str]], source_file: str
) -> list[IncomeDocument]:
    """Parse a Wage & Income transcript into one IncomeDocument per form."""
    return [_parse_block(b, source_file) for b in _segment(lines_with_pages)]


def total(documents: list[IncomeDocument], field_name: str) -> Decimal:
    """Sum one normalized field across documents. Missing values contribute 0."""
    out = Decimal("0")
    for doc in documents:
        value = doc.amounts.get(field_name)
        if value is not None:
            out += value
    return out
