"""Data model for parsed IRS transcripts.

Money is always ``Decimal`` or ``None``.  Never ``float`` -- binary floating
point cannot represent 0.10 exactly and a tax tool must not accumulate that
error.  ``None`` means "the field was not present"; ``Decimal("0")`` means
"the transcript literally said $0.00".  Those are different facts and the
distinction is preserved all the way to the output artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any


def _jsonable(value: Any) -> Any:
    """Convert Decimals to strings so JSON round-trips without float drift."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass
class SourceRef:
    """Where a parsed value physically came from, so it can be eyeballed."""

    file: str
    page: int  # 1-based, matches what a PDF viewer shows

    def __str__(self) -> str:
        return f"{self.file} p.{self.page}"


@dataclass
class IncomeDocument:
    """One information return (W-2, 1099-*, 1098-*, 5498, K-1, ...) as it
    appears on a Wage & Income transcript."""

    form_type: str                       # "W-2", "1099-NEC", "1098", ...
    tax_year: str | None = None          # "2024"
    payer_name: str | None = None
    payer_tin: str | None = None         # masked on transcripts: XX-XXX1234
    recipient_name: str | None = None
    recipient_tin: str | None = None     # masked: XXX-XX-1234
    submission_type: str | None = None   # "Original document" / "Corrected"
    account_number: str | None = None

    # Normalized, machine-comparable amounts. Keys come from FIELD_ALIASES.
    amounts: dict[str, Decimal] = field(default_factory=dict)

    # Every label:value pair exactly as printed, including ones we don't map.
    # Nothing the transcript said is ever dropped.
    raw_fields: dict[str, str] = field(default_factory=dict)

    source: SourceRef | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Short human identifier, e.g. 'W-2 / ACME CORP'."""
        who = self.payer_name or "(payer not stated)"
        return f"{self.form_type} / {who}"

    def amount(self, key: str) -> Decimal | None:
        return self.amounts.get(key)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amounts"] = _jsonable(self.amounts)
        d["source"] = str(self.source) if self.source else None
        d["label"] = self.label
        return d


@dataclass
class AccountTransaction:
    """A single line from the TRANSACTIONS table of an Account Transcript."""

    code: str                    # "150", "806", "610", ...
    explanation: str             # "Tax return filed"
    cycle: str | None = None     # "20241405"
    date: str | None = None      # "04-15-2024" as printed
    amount: Decimal | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amount"] = _jsonable(self.amount)
        return d


@dataclass
class AccountTranscript:
    """IRS Account Transcript: assessments, payments, credits, notices."""

    tax_year: str | None = None
    form_number: str | None = None            # "1040"
    filing_status: str | None = None
    account_balance: Decimal | None = None
    accrued_interest: Decimal | None = None
    accrued_penalty: Decimal | None = None
    summary_fields: dict[str, Decimal] = field(default_factory=dict)
    transactions: list[AccountTransaction] = field(default_factory=list)
    raw_fields: dict[str, str] = field(default_factory=dict)
    source: SourceRef | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["account_balance"] = _jsonable(self.account_balance)
        d["accrued_interest"] = _jsonable(self.accrued_interest)
        d["accrued_penalty"] = _jsonable(self.accrued_penalty)
        d["summary_fields"] = _jsonable(self.summary_fields)
        d["transactions"] = [t.to_dict() for t in self.transactions]
        d["source"] = str(self.source) if self.source else None
        return d


@dataclass
class ReturnTranscript:
    """IRS Return Transcript: the line items of a return as the IRS posted it.

    This is the single most useful artifact for tie-out when amending or
    checking a prior year, because it is the return *as filed and posted*.
    """

    tax_year: str | None = None
    form_number: str | None = None
    filing_status: str | None = None
    line_items: dict[str, Decimal] = field(default_factory=dict)
    raw_fields: dict[str, str] = field(default_factory=dict)
    source: SourceRef | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["line_items"] = _jsonable(self.line_items)
        d["source"] = str(self.source) if self.source else None
        return d


@dataclass
class ParsedTranscript:
    """Everything extracted from one PDF file."""

    file: str
    transcript_type: str          # see classify.TranscriptType
    pages: int = 0
    tax_years: list[str] = field(default_factory=list)
    taxpayer_tin: str | None = None
    request_date: str | None = None
    income_documents: list[IncomeDocument] = field(default_factory=list)
    account: AccountTranscript | None = None
    tax_return: ReturnTranscript | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "transcript_type": self.transcript_type,
            "pages": self.pages,
            "tax_years": self.tax_years,
            "taxpayer_tin": self.taxpayer_tin,
            "request_date": self.request_date,
            "income_documents": [d.to_dict() for d in self.income_documents],
            "account": self.account.to_dict() if self.account else None,
            "tax_return": self.tax_return.to_dict() if self.tax_return else None,
            "warnings": self.warnings,
        }
