"""Where each transcript amount usually lands on a Form 1040.

This is a REVIEW AID, not tax advice and not a substitute for the preparer's
judgment.  It answers "if this 1099 exists, which line of the return should
show it?" so that a missing line is obvious.  It does not know about basis,
nontaxable portions, allocations between spouses, passive loss limits, or
any of the dozens of reasons a reported amount legitimately differs from the
amount that lands on a return.

Line references are for the Form 1040 layout used for tax years 2023-2025.
Line numbering has moved between years -- confirm against the actual form
for the year being prepared.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineTarget:
    form: str            # "Form 1040", "Schedule 1", "Schedule B", ...
    line: str            # "1a", "2b", "25a", "Part I"
    description: str
    note: str = ""

    def __str__(self) -> str:
        return f"{self.form} line {self.line}"


# (form_type, normalized_field) -> target. Checked first.
_SPECIFIC: dict[tuple[str, str], LineTarget] = {
    # --- Wages -------------------------------------------------------------
    ("W-2", "wages"): LineTarget(
        "Form 1040", "1a", "Total amount from Form(s) W-2, box 1"),
    ("W-2", "federal_withholding"): LineTarget(
        "Form 1040", "25a", "Federal income tax withheld from Form(s) W-2"),
    ("W-2", "ss_tax_withheld"): LineTarget(
        "Schedule 3", "11", "Excess social security tax withheld",
        "Only if total SS tax across employers exceeds the annual maximum."),
    ("W-2", "dependent_care_benefits"): LineTarget(
        "Form 2441", "Part III", "Dependent care benefits",
        "Form 2441 must be filed even if the benefit is fully excludable."),
    ("W-2", "hsa_employer_contributions"): LineTarget(
        "Form 8889", "9", "Employer contributions to an HSA (box 12 code W)",
        "Reduces the deductible HSA contribution on Form 8889."),
    ("W-2", "combat_pay"): LineTarget(
        "Form 1040", "1i", "Nontaxable combat pay election",
        "Elective -- can increase EIC and the additional child tax credit."),
    ("W-2", "allocated_tips"): LineTarget(
        "Form 4137", "1", "Allocated tips",
        "Unreported tips are subject to social security and Medicare tax."),
    ("W-2G", "gambling_winnings"): LineTarget(
        "Schedule 1", "8b", "Gambling income"),
    ("W-2G", "federal_withholding"): LineTarget(
        "Form 1040", "25c", "Federal income tax withheld from other forms"),

    # --- Self-employment ---------------------------------------------------
    ("1099-NEC", "nonemployee_comp"): LineTarget(
        "Schedule C", "1", "Gross receipts or sales",
        "Flows to Schedule 1 line 3 and Schedule SE."),
    ("1099-MISC", "nonemployee_comp"): LineTarget(
        "Schedule C", "1", "Gross receipts or sales (pre-2020 box 7)"),
    ("1099-MISC", "rents"): LineTarget(
        "Schedule E", "3", "Rents received",
        "Schedule C instead if this is a trade or business."),
    ("1099-MISC", "royalties"): LineTarget(
        "Schedule E", "4", "Royalties received"),
    ("1099-MISC", "other_income"): LineTarget(
        "Schedule 1", "8z", "Other income"),
    ("1099-MISC", "medical_health_payments"): LineTarget(
        "Schedule C", "1", "Gross receipts or sales"),
    ("1099-MISC", "fishing_boat_proceeds"): LineTarget(
        "Schedule C", "1", "Gross receipts or sales"),
    ("1099-MISC", "crop_insurance_proceeds"): LineTarget(
        "Schedule F", "6a", "Crop insurance proceeds"),
    ("1099-MISC", "attorney_gross_proceeds"): LineTarget(
        "Schedule C", "1", "Gross proceeds paid to an attorney",
        "Gross proceeds, not necessarily income -- often a client settlement."),
    ("1099-K", "gross_payment_card_transactions"): LineTarget(
        "Schedule C", "1", "Gross receipts or sales",
        "Frequently overlaps 1099-NEC/MISC from the same payers. Do not "
        "double count; reconcile to the books, not to the sum of the forms."),

    # --- Interest and dividends -------------------------------------------
    ("1099-INT", "interest"): LineTarget(
        "Form 1040", "2b", "Taxable interest (Schedule B Part I if > $1,500)"),
    ("1099-INT", "tax_exempt_interest"): LineTarget(
        "Form 1040", "2a", "Tax-exempt interest"),
    ("1099-INT", "savings_bond_interest"): LineTarget(
        "Form 1040", "2b", "Interest on US savings bonds / Treasury obligations",
        "May be excludable via Form 8815 if used for higher education."),
    ("1099-INT", "early_withdrawal_penalty"): LineTarget(
        "Schedule 1", "18", "Penalty on early withdrawal of savings"),
    ("1099-INT", "private_activity_bond_interest"): LineTarget(
        "Form 6251", "2g", "Private activity bond interest (AMT preference)"),
    ("1099-OID", "original_issue_discount"): LineTarget(
        "Form 1040", "2b", "Taxable interest -- OID"),
    ("1099-OID", "other_periodic_interest"): LineTarget(
        "Form 1040", "2b", "Taxable interest"),
    ("1099-DIV", "ordinary_dividends"): LineTarget(
        "Form 1040", "3b", "Ordinary dividends (Schedule B Part II if > $1,500)"),
    ("1099-DIV", "qualified_dividends"): LineTarget(
        "Form 1040", "3a", "Qualified dividends",
        "A subset of line 3b, not additional income."),
    ("1099-DIV", "capital_gain_distributions"): LineTarget(
        "Form 1040", "7", "Capital gain distributions",
        "Can go straight to 1040 line 7 if no other capital transactions."),
    ("1099-DIV", "section_199a_dividends"): LineTarget(
        "Form 8995", "6", "REIT dividends for the QBI deduction"),
    ("1099-DIV", "exempt_interest_dividends"): LineTarget(
        "Form 1040", "2a", "Tax-exempt interest"),
    ("1099-DIV", "foreign_tax_paid"): LineTarget(
        "Schedule 3", "1", "Foreign tax credit (Form 1116 if over the limit)"),
    ("1099-INT", "foreign_tax_paid"): LineTarget(
        "Schedule 3", "1", "Foreign tax credit (Form 1116 if over the limit)"),

    # --- Capital transactions ---------------------------------------------
    ("1099-B", "gross_proceeds"): LineTarget(
        "Form 8949", "Part I/II", "Proceeds from broker transactions",
        "Totals to Schedule D, then Form 1040 line 7. Basis is often NOT "
        "reported to the IRS -- proceeds alone are not gain."),
    ("1099-B", "cost_basis"): LineTarget(
        "Form 8949", "column (e)", "Cost or other basis"),
    ("1099-S", "gross_proceeds"): LineTarget(
        "Form 8949", "Part II", "Proceeds from a real estate transaction",
        "Principal residence may be excludable under section 121, but the "
        "sale still needs reporting when a 1099-S was issued."),

    # --- Retirement --------------------------------------------------------
    ("1099-R", "gross_distribution"): LineTarget(
        "Form 1040", "4a or 5a", "IRA distributions (4a) or pensions (5a)",
        "Which line depends on the IRA/SEP/SIMPLE indicator on the form."),
    ("1099-R", "taxable_amount"): LineTarget(
        "Form 1040", "4b or 5b", "Taxable amount of the distribution",
        "Check the distribution code for early-distribution penalty "
        "(Form 5329) and for rollovers, which are not taxable."),
    ("1099-R", "federal_withholding"): LineTarget(
        "Form 1040", "25b", "Federal income tax withheld from Form(s) 1099"),
    ("SSA-1099", "social_security_benefits"): LineTarget(
        "Form 1040", "6a", "Social security benefits",
        "Taxable portion on 6b is 0-85% depending on provisional income."),
    ("RRB-1099", "social_security_benefits"): LineTarget(
        "Form 1040", "6a", "Railroad retirement tier 1 benefits"),
    ("5498", "ira_contributions"): LineTarget(
        "Schedule 1", "20", "IRA deduction",
        "Deductibility depends on workplace plan coverage and MAGI."),
    ("5498", "roth_conversion"): LineTarget(
        "Form 8606", "Part II", "Roth conversion",
        "Should correspond to a 1099-R with a conversion distribution code."),
    ("5498", "rollover_contributions"): LineTarget(
        "Form 1040", "4b/5b", "Rollover",
        "Confirm the matching 1099-R is excluded from taxable income."),
    ("5498", "fmv_account"): LineTarget(
        "Form 8606", "Part I", "Year-end IRA value",
        "Needed for the pro-rata rule when there is any nondeductible basis."),

    # --- Government payments ----------------------------------------------
    ("1099-G", "unemployment_compensation"): LineTarget(
        "Schedule 1", "7", "Unemployment compensation"),
    ("1099-G", "state_tax_refund"): LineTarget(
        "Schedule 1", "1", "Taxable state/local income tax refund",
        "Taxable only to the extent the tax was deducted and gave a benefit "
        "in the prior year -- zero for prior-year standard deduction filers."),
    ("1099-G", "taxable_grants"): LineTarget(
        "Schedule 1", "8z", "Other income -- taxable grants"),
    ("1099-G", "agriculture_payments"): LineTarget(
        "Schedule F", "4b", "Agricultural program payments"),

    # --- Deductions and credits -------------------------------------------
    ("1098", "mortgage_interest"): LineTarget(
        "Schedule A", "8a", "Home mortgage interest and points",
        "Limited if the loan exceeds the acquisition debt cap."),
    ("1098", "points_paid"): LineTarget(
        "Schedule A", "8a", "Points paid on purchase of principal residence"),
    ("1098", "mortgage_insurance_premiums"): LineTarget(
        "Schedule A", "8d", "Mortgage insurance premiums",
        "Deductibility has lapsed and been revived repeatedly -- verify for "
        "the year being prepared."),
    ("1098", "real_estate_taxes"): LineTarget(
        "Schedule A", "5b", "State and local real estate taxes",
        "Part of the SALT cap."),
    ("1098-E", "student_loan_interest"): LineTarget(
        "Schedule 1", "21", "Student loan interest deduction",
        "Capped at $2,500 and phased out by MAGI."),
    ("1098-T", "qualified_tuition_payments"): LineTarget(
        "Form 8863", "Part III", "Qualified education expenses",
        "The 1098-T alone is not sufficient substantiation -- reconcile to "
        "what was actually paid in the year."),
    ("1098-T", "scholarships_or_grants"): LineTarget(
        "Form 8863", "Part III", "Scholarships/grants reducing expenses",
        "Excess over qualified expenses may be taxable income."),
    ("1098-C", "vehicle_gross_proceeds"): LineTarget(
        "Schedule A", "12", "Noncash charitable contribution",
        "Form 8283 required over $500."),

    # --- Health accounts ---------------------------------------------------
    ("1099-SA", "gross_distribution"): LineTarget(
        "Form 8889", "14a", "HSA distributions",
        "Nontaxable to the extent used for qualified medical expenses."),
    ("5498-SA", "hsa_contributions"): LineTarget(
        "Form 8889", "2", "HSA contributions made",
        "Includes employer contributions already in W-2 box 12 code W -- "
        "do not deduct those twice."),
    ("1095-A", "marketplace_advance_ptc"): LineTarget(
        "Form 8962", "11-23", "Advance premium tax credit",
        "Form 8962 is REQUIRED whenever a 1095-A exists. Omitting it is one "
        "of the most common causes of a rejected or adjusted return."),
    ("1095-A", "marketplace_premium"): LineTarget(
        "Form 8962", "11-23 column (a)", "Enrollment premiums"),
    ("1095-A", "marketplace_slcsp"): LineTarget(
        "Form 8962", "11-23 column (b)", "Second lowest cost silver plan"),

    # --- Other -------------------------------------------------------------
    ("1099-C", "debt_cancelled"): LineTarget(
        "Schedule 1", "8c", "Cancellation of debt",
        "May be excludable under section 108 -- Form 982."),
    ("1099-Q", "gross_distribution"): LineTarget(
        "Form 1040", "n/a", "Qualified education program distribution",
        "Not reported at all if fully used for qualified expenses; the "
        "earnings portion is taxable otherwise."),
    ("1099-PATR", "patronage_dividends"): LineTarget(
        "Schedule F", "3a", "Patronage dividends",
        "Schedule C instead if not a farm."),
    ("1042-S", "gross_income_1042s"): LineTarget(
        "Form 1040", "varies", "US source income of a foreign person",
        "Character of the income determines the line."),
}

# Applied to any form the specific table does not cover.
_BY_FIELD: dict[str, LineTarget] = {
    "federal_withholding": LineTarget(
        "Form 1040", "25b", "Federal income tax withheld from Form(s) 1099"),
    "state_withholding": LineTarget(
        "Schedule A", "5a", "State and local income taxes",
        "Part of the SALT cap."),
    "interest": LineTarget("Form 1040", "2b", "Taxable interest"),
    "ordinary_dividends": LineTarget("Form 1040", "3b", "Ordinary dividends"),
    "qualified_dividends": LineTarget("Form 1040", "3a", "Qualified dividends"),
    "royalties": LineTarget("Schedule E", "4", "Royalties"),
    "k1_ordinary_business_income": LineTarget(
        "Schedule E", "Part II", "Partnership / S corporation income"),
    "k1_rental_real_estate_income": LineTarget(
        "Schedule E", "Part II", "Rental real estate income from a K-1"),
    "k1_guaranteed_payments": LineTarget(
        "Schedule E", "Part II", "Guaranteed payments",
        "Subject to self-employment tax on Schedule SE."),
    "k1_short_term_capital_gain": LineTarget(
        "Schedule D", "5", "Short-term gain from a K-1"),
    "k1_long_term_capital_gain": LineTarget(
        "Schedule D", "12", "Long-term gain from a K-1"),
    "k1_self_employment_earnings": LineTarget(
        "Schedule SE", "2", "Self-employment earnings from a K-1"),
}

# Amounts that must NOT be added into income totals: they are components of,
# or memoranda about, another figure. Rolling these up would double count.
MEMO_FIELDS = {
    "qualified_dividends",          # subset of ordinary dividends
    "ss_wages", "ss_tips", "medicare_wages",   # not income lines themselves
    "ss_tax_withheld", "medicare_tax_withheld",
    "cost_basis",                   # offsets proceeds, is not income
    "employer_health_coverage_cost",
    "fmv_account", "outstanding_mortgage_principal",
    "deferred_comp", "roth_401k", "roth_403b", "roth_457b",
    "taxable_amount",               # reported alongside gross_distribution
    "investment_expenses",
    "marketplace_premium", "marketplace_slcsp",
}


def line_for(form_type: str, field: str) -> LineTarget | None:
    """Best-known return line for ``field`` as reported on ``form_type``."""
    key = "K-1" if form_type.startswith("K-1") else form_type
    return _SPECIFIC.get((key, field)) or _BY_FIELD.get(field)


# The IRA/SEP/SIMPLE box is printed in several ways depending on the transcript
# vintage: a bare "1"/"0", or prose like "IRA/SEP/SIMP box checked".
_IRA_LABELS = ("IRA/SEP/SIMPLE Indicator", "SEP Indicator", "IRA Indicator")


def ira_indicator(doc) -> bool | None:
    """True if the 1099-R came from an IRA, False if not, None if unstated."""
    for label in _IRA_LABELS:
        raw = (doc.raw_fields.get(label) or "").strip()
        if not raw:
            continue
        low = raw.lower()
        if "not checked" in low or "box not checked" in low:
            return False
        if "checked" in low:
            return True
        if raw in {"0", "0.00"}:
            return False
        return True
    return None


def distribution_codes(doc) -> str:
    """Every distribution code letter/number printed on a 1099-R, joined.

    Transcripts print the code in one field and its meaning in another, and
    repeat both for the second code position, so several labels are gathered.
    """
    codes: list[str] = []
    for label, value in doc.raw_fields.items():
        if not label.lower().startswith("distribution code"):
            continue
        if label.lower().startswith("distribution code value"):
            continue
        text = (value or "").strip()
        if text and text not in codes:
            codes.append(text)
    return "".join(codes)


def distribution_meanings(doc) -> list[str]:
    """The prose meanings the transcript prints for the distribution codes."""
    out: list[str] = []
    for label, value in doc.raw_fields.items():
        if not label.lower().startswith("distribution code value"):
            continue
        text = (value or "").strip()
        if text and text.lower() != "not significant" and text not in out:
            out.append(text)
    return out


def refine_1099r(doc) -> str:
    """Pick 1040 line 4 (IRA) vs line 5 (pension) for a 1099-R."""
    indicator = ira_indicator(doc)
    if indicator is True:
        return "4a/4b (IRA)"
    if indicator is False:
        return "5a/5b (pension/annuity)"
    return "4a/4b or 5a/5b (IRA indicator not stated)"


def is_memo(field: str) -> bool:
    """True if the field must be excluded from income roll-up totals."""
    return field in MEMO_FIELDS
