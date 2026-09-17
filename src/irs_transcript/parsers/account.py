"""Parser for the IRS Account Transcript.

The Account Transcript is the IRS's ledger for one taxpayer, one form, one
period.  Its value for return preparation is the TRANSACTIONS table, which is
where estimated tax payments, extension payments, withholding credits,
refunds and offsets actually live -- none of which appear on a Wage & Income
transcript.

Transaction rows look like::

    CODE  EXPLANATION OF TRANSACTION      CYCLE     DATE        AMOUNT
    150   Tax return filed                20251805  05-05-2025  $24,118.00
    806   W-2 or 1099 withholding                   04-15-2025  -$13,340.00
    660   Estimated tax payment                     06-15-2024  -$4,000.00

A leading minus means a CREDIT to the taxpayer (a payment or withholding),
which the transcript states in its own header line.  We preserve the sign
exactly as printed and do not flip it.
"""

from __future__ import annotations

import re
from decimal import Decimal

from ..fields import parse_money, split_label_value
from ..models import AccountTransaction, AccountTranscript, SourceRef

# 150 / 806 / 610 ... then explanation, optional 8-digit cycle, optional
# MM-DD-YYYY date, optional money. Explanation is non-greedy so it stops at
# the cycle or date rather than swallowing them.
_TRANSACTION = re.compile(
    r"^\s*(?P<code>\d{3})\s+"
    r"(?P<explanation>\S.*?)"
    r"(?:\s+(?P<cycle>\d{8}))?"
    r"(?:\s+(?P<date>\d{2}-\d{2}-\d{4}))?"
    r"(?:\s+(?P<amount>-?\$?-?[\d,]+\.\d{2}))?"
    r"\s*$"
)

# "ACCRUED INTEREST: 0.00 AS OF: Mar. 17, 2025" carries two pairs on one line.
# The trailing "AS OF" is metadata about the first value, not a value itself.
_AS_OF = re.compile(r"\s+AS\s+OF:\s*(?P<as_of>.+)$", re.IGNORECASE)

_SUMMARY_MONEY_LABELS = {
    "account balance": "account_balance",
    "accrued interest": "accrued_interest",
    "accrued penalty": "accrued_penalty",
    "adjusted gross income": "adjusted_gross_income",
    "taxable income": "taxable_income",
    "tax per return": "tax_per_return",
    "se taxable income taxpayer": "se_taxable_income_taxpayer",
    "se taxable income spouse": "se_taxable_income_spouse",
    "total self employment tax": "total_self_employment_tax",
}

_FORM_NUMBER = re.compile(r"FORM\s+NUMBER:\s*(?P<v>\S+)", re.IGNORECASE)
_FILING_STATUS = re.compile(r"FILING\s+STATUS:\s*(?P<v>.+)", re.IGNORECASE)
_TAX_PERIOD = re.compile(r"TAX\s+PERIOD:\s*(?P<v>.+)", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

# Codes whose amounts are payments/credits a preparer must account for.
PAYMENT_CODES = {
    "150": "Tax return filed (tax assessed)",
    "170": "Estimated tax penalty",
    "276": "Failure to pay tax penalty",
    "300": "Additional tax assessed by examination",
    "290": "Additional tax assessed",
    "291": "Prior tax abated",
    "420": "Examination of tax return",
    "424": "Examination request indicator",
    "430": "Estimated tax declaration",
    "460": "Extension of time to file",
    "570": "Additional account action pending",
    "571": "Resolved additional account action",
    "610": "Remittance with return",
    "611": "Remittance with return - dishonored",
    "660": "Estimated tax payment",
    "666": "Estimated tax credit transfer in",
    "670": "Subsequent payment",
    "706": "Credit applied from prior year",
    "710": "Overpayment credit applied from prior year",
    "716": "Credit applied to next year",
    "764": "Earned income credit",
    "766": "Credit to your account / refundable credit",
    "768": "Earned income credit",
    "806": "W-2 or 1099 withholding credit",
    "807": "Reduced or removed W-2/1099 withholding",
    "826": "Credit transferred out to another period",
    "846": "Refund issued",
    "971": "Notice issued",
}


def _strip_as_of(line: str) -> tuple[str, str | None]:
    m = _AS_OF.search(line)
    if not m:
        return line, None
    return line[: m.start()], m.group("as_of").strip()


def parse_account_transcript(
    lines_with_pages: list[tuple[int, str]], source_file: str
) -> AccountTranscript:
    """Parse an Account Transcript's summary fields and transaction ledger."""
    first_page = lines_with_pages[0][0] if lines_with_pages else 1
    acct = AccountTranscript(source=SourceRef(file=source_file, page=first_page))
    in_transactions = False

    for _page, raw in lines_with_pages:
        line = raw.rstrip()
        if not line.strip():
            continue

        if re.match(r"^\s*TRANSACTIONS\s*$", line, re.IGNORECASE):
            in_transactions = True
            continue
        # The table's own header row, not data.
        if in_transactions and re.match(
            r"^\s*CODE\s+EXPLANATION", line, re.IGNORECASE
        ):
            continue

        if not acct.form_number:
            m = _FORM_NUMBER.search(line)
            if m:
                acct.form_number = m.group("v").strip()
        if not acct.filing_status:
            m = _FILING_STATUS.search(line)
            if m:
                acct.filing_status = m.group("v").strip()
        if not acct.tax_year:
            m = _TAX_PERIOD.search(line)
            if m:
                y = _YEAR.search(m.group("v"))
                if y:
                    acct.tax_year = y.group(0)

        if in_transactions:
            m = _TRANSACTION.match(line)
            if m and (m.group("date") or m.group("amount")):
                acct.transactions.append(
                    AccountTransaction(
                        code=m.group("code"),
                        explanation=m.group("explanation").strip(),
                        cycle=m.group("cycle"),
                        date=m.group("date"),
                        amount=parse_money(m.group("amount")),
                    )
                )
                continue

        body, as_of = _strip_as_of(line)
        pair = split_label_value(body)
        if pair is None:
            continue
        label, value = pair
        label = label.strip()
        if label and value:
            acct.raw_fields[label] = value
        if as_of:
            acct.raw_fields[f"{label} AS OF"] = as_of

        key = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        field_name = _SUMMARY_MONEY_LABELS.get(key)
        if field_name:
            amount = parse_money(value)
            if amount is not None:
                acct.summary_fields[field_name] = amount
                if field_name in ("account_balance", "accrued_interest",
                                  "accrued_penalty"):
                    setattr(acct, field_name, amount)

    if not acct.transactions:
        acct.warnings.append(
            "no transaction rows parsed -- if the PDF has a TRANSACTIONS "
            "table, the column layout differs from the expected one"
        )
    return acct


def payments_and_credits(acct: AccountTranscript) -> dict[str, Decimal]:
    """Total the transaction codes that represent money the taxpayer paid.

    Credits print as negatives on the transcript, so the sign is flipped here
    to give a positive "amount paid" a preparer can compare to a return.
    """
    buckets: dict[str, Decimal] = {}
    groups = {
        "withholding": {"806"},
        "estimated_payments": {"660", "666", "430"},
        "payments_with_return": {"610", "670"},
        "prior_year_credit_applied": {"706", "710"},
        "refundable_credits": {"764", "766", "768"},
        "refund_issued": {"846"},
        "applied_to_next_year": {"716"},
    }
    for name, codes in groups.items():
        total = Decimal("0")
        seen = False
        for txn in acct.transactions:
            if txn.code in codes and txn.amount is not None:
                total += txn.amount
                seen = True
        if seen:
            buckets[name] = -total if total < 0 else total
    return buckets
