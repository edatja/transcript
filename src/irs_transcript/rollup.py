"""Aggregate parsed documents into per-return-line totals.

This is the step that turns "here are 34 information returns" into "line 1a
should be at least $100,750 across 2 W-2s", which is the form a preparer can
actually tie a draft return to.

Every total carries the list of documents that produced it, so a mismatch can
be traced to a payer in one step instead of re-reading the transcript.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .mapping import LineTarget, is_memo, line_for, refine_1099r
from .models import IncomeDocument


@dataclass
class Contribution:
    document: IncomeDocument
    field_name: str
    amount: Decimal


@dataclass
class RollupLine:
    target: LineTarget
    total: Decimal = Decimal("0")
    contributions: list[Contribution] = field(default_factory=list)
    notes: set[str] = field(default_factory=set)

    @property
    def key(self) -> tuple[str, str]:
        return (self.target.form, self.target.line)


@dataclass
class Rollup:
    tax_year: str | None
    lines: list[RollupLine] = field(default_factory=list)
    unmapped: list[Contribution] = field(default_factory=list)
    memo: list[Contribution] = field(default_factory=list)
    document_counts: dict[str, int] = field(default_factory=dict)

    def total_for(self, form: str, line: str) -> Decimal:
        for entry in self.lines:
            if entry.target.form == form and entry.target.line == line:
                return entry.total
        return Decimal("0")


# Form 1040 order, so the report reads down the return rather than at random.
_FORM_ORDER = [
    "Form 1040", "Schedule 1", "Schedule B", "Schedule C", "Schedule D",
    "Form 8949", "Schedule E", "Schedule F", "Schedule SE", "Schedule A",
    "Schedule 3", "Form 2441", "Form 8863", "Form 8889", "Form 8962",
    "Form 8606", "Form 8995", "Form 6251", "Form 5329", "Form 4137",
    "Form 982", "Form 1116",
]


def _sort_key(entry: RollupLine) -> tuple[int, str]:
    form = entry.target.form
    rank = _FORM_ORDER.index(form) if form in _FORM_ORDER else len(_FORM_ORDER)
    # "1a" before "2b" before "25a": sort on the LEADING digit run only.
    # Trailing text matters ("4a/4b (IRA)" must sort with 4, not with 4456),
    # so only the digits before the first non-digit are numeric.
    line = entry.target.line
    m = re.match(r"(\d+)(.*)", line)
    if m:
        return (rank, f"{int(m.group(1)):03d}{m.group(2)}")
    return (rank, f"999{line}")


def build_rollup(
    documents: list[IncomeDocument], tax_year: str | None = None
) -> Rollup:
    """Group every mapped amount onto the return line it belongs to."""
    if tax_year is not None:
        documents = [d for d in documents if d.tax_year == tax_year]

    rollup = Rollup(tax_year=tax_year)
    by_key: dict[tuple[str, str], RollupLine] = {}
    counts: dict[str, int] = defaultdict(int)

    for doc in documents:
        counts[doc.form_type] += 1
        for field_name, amount in doc.amounts.items():
            contribution = Contribution(doc, field_name, amount)

            if is_memo(field_name):
                rollup.memo.append(contribution)
                continue

            target = line_for(doc.form_type, field_name)
            if target is None:
                rollup.unmapped.append(contribution)
                continue

            # A 1099-R lands on line 4 or line 5 depending on whether the
            # payer flagged it as an IRA. Resolve it per document.
            if doc.form_type == "1099-R" and field_name == "gross_distribution":
                target = LineTarget(
                    target.form, refine_1099r(doc), target.description,
                    target.note,
                )

            entry = by_key.get((target.form, target.line))
            if entry is None:
                entry = RollupLine(target=target)
                by_key[(target.form, target.line)] = entry
                rollup.lines.append(entry)
            entry.total += amount
            entry.contributions.append(contribution)
            if target.note:
                entry.notes.add(target.note)

    rollup.lines.sort(key=_sort_key)
    rollup.document_counts = dict(sorted(counts.items()))
    return rollup


def withholding_summary(documents: list[IncomeDocument]) -> dict[str, Decimal]:
    """Federal withholding split the way Form 1040 lines 25a/25b/25c split it."""
    out = {
        "from_w2_line_25a": Decimal("0"),
        "from_1099_line_25b": Decimal("0"),
        "from_other_line_25c": Decimal("0"),
    }
    for doc in documents:
        amount = doc.amounts.get("federal_withholding")
        if amount is None:
            continue
        if doc.form_type in ("W-2",):
            out["from_w2_line_25a"] += amount
        elif doc.form_type.startswith("1099"):
            out["from_1099_line_25b"] += amount
        else:
            out["from_other_line_25c"] += amount
    out["total"] = sum(out.values(), Decimal("0"))
    return out


def flag_review_items(documents: list[IncomeDocument]) -> list[str]:
    """Situations that reliably cause return errors, called out by name.

    These are pattern checks on what the transcript shows -- they never assert
    what the return should say, only that a preparer should look.
    """
    flags: list[str] = []
    types = {d.form_type for d in documents}

    if "1095-A" in types:
        flags.append(
            "1095-A present: Form 8962 is required. A return with marketplace "
            "coverage and no Form 8962 is routinely rejected or adjusted."
        )
    if "1099-B" in types or "1099-S" in types:
        flags.append(
            "Broker or real estate proceeds present: transcripts report "
            "PROCEEDS, and basis is often absent. Proceeds are not gain -- "
            "Form 8949 needs basis from the taxpayer's own records."
        )
    if "1099-K" in types and ("1099-NEC" in types or "1099-MISC" in types):
        flags.append(
            "Both 1099-K and 1099-NEC/MISC present: the same revenue is "
            "commonly reported on both. Tie gross receipts to the books, not "
            "to the sum of the forms, or income will be overstated."
        )
    if "5498" in types and "1099-R" in types:
        flags.append(
            "5498 and 1099-R both present: check for a rollover or Roth "
            "conversion. A rollover reported as taxable is a common overpayment."
        )
    if "1098-T" in types:
        flags.append(
            "1098-T present: box amounts are what the school billed or "
            "received, not necessarily what qualifies. Reconcile to amounts "
            "actually paid in the tax year before claiming a credit."
        )

    corrected = [d for d in documents
                 if (d.submission_type or "").lower().startswith("corrected")]
    for doc in corrected:
        flags.append(
            f"CORRECTED form: {doc.label} is marked '{doc.submission_type}'. "
            f"Confirm the return uses the corrected figures."
        )

    for doc in documents:
        code = (doc.raw_fields.get("Distribution Code(s)") or "").strip()
        if doc.form_type == "1099-R" and code in {"1", "J", "S"}:
            flags.append(
                f"1099-R from {doc.payer_name or 'unknown payer'} has "
                f"distribution code '{code}' (early distribution). Form 5329 "
                f"may be needed unless an exception applies."
            )
    return flags
