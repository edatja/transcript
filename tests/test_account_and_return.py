"""Account Transcript and Return Transcript parsing."""

from decimal import Decimal

from irs_transcript.classify import TranscriptType, detect_type
from irs_transcript.parsers import parse_account_transcript, parse_return_transcript
from irs_transcript.parsers.account import payments_and_credits


# --- Account transcript -----------------------------------------------------

def test_account_header(account_lines):
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    assert acct.form_number == "1040"
    assert acct.tax_year == "2024"
    assert acct.filing_status == "Single"


def test_account_summary_figures(account_lines):
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    assert acct.summary_fields["adjusted_gross_income"] == Decimal("145320.00")
    assert acct.summary_fields["tax_per_return"] == Decimal("24118.00")
    assert acct.summary_fields["total_self_employment_tax"] == Decimal("3390.00")
    assert acct.account_balance == Decimal("0.00")


def test_two_pairs_on_one_line_are_both_captured(account_lines):
    """'ACCRUED INTEREST: 0.00 AS OF: Mar. 17, 2025' carries a value and a date."""
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    assert acct.accrued_interest == Decimal("0.00")
    assert acct.raw_fields["ACCRUED INTEREST AS OF"] == "Mar. 17, 2025"


def test_transactions_are_parsed(account_lines):
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    assert len(acct.transactions) == 7
    filed = [t for t in acct.transactions if t.code == "150"][0]
    assert filed.cycle == "20251805"
    assert filed.date == "05-05-2025"
    assert filed.amount == Decimal("24118.00")


def test_credit_signs_are_preserved_as_printed(account_lines):
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    withholding = [t for t in acct.transactions if t.code == "806"][0]
    assert withholding.amount == Decimal("-13340.00")


def test_estimated_payments_are_totalled(account_lines):
    """Estimated payments appear ONLY on an account transcript.

    A preparer relying on Wage & Income alone would miss them entirely.
    """
    acct = parse_account_transcript(account_lines, "account_2024.pdf")
    credits = payments_and_credits(acct)
    assert credits["estimated_payments"] == Decimal("8000.00")   # sign flipped
    assert credits["withholding"] == Decimal("13340.00")
    assert credits["payments_with_return"] == Decimal("2778.00")


def test_account_classification(account_lines):
    text = "\n".join(line for _p, line in account_lines)
    assert detect_type(text) == TranscriptType.ACCOUNT


# --- Return transcript ------------------------------------------------------

def test_return_header(return_lines):
    ret = parse_return_transcript(return_lines, "return_2023.pdf")
    assert ret.form_number == "1040"
    assert ret.tax_year == "2023"
    assert ret.filing_status == "Single"


def test_return_line_items(return_lines):
    ret = parse_return_transcript(return_lines, "return_2023.pdf")
    assert ret.line_items["wages_salaries_tips_etc"] == Decimal("96400.00")
    # A label containing its own colon must still split correctly.
    assert ret.line_items["taxable_interest_income_sch_b"] == Decimal("980.00")


def test_irs_adjustment_is_flagged_not_silently_merged(return_lines):
    """When PER COMPUTER differs from the reported figure, the IRS changed
    the return. That is the single most important thing on this transcript."""
    ret = parse_return_transcript(return_lines, "return_2023.pdf")
    adjusted = [w for w in ret.warnings if "adjusted_gross_income" in w]
    assert len(adjusted) == 1
    assert "114,450.00" in adjusted[0]
    assert "116,650.00" in adjusted[0]
    # Both figures survive; neither is thrown away.
    assert ret.line_items["adjusted_gross_income"] == Decimal("114450.00")
    assert ret.line_items["adjusted_gross_income__per_computer"] == \
        Decimal("116650.00")


def test_matching_per_computer_does_not_warn(return_lines):
    ret = parse_return_transcript(return_lines, "return_2023.pdf")
    assert not any("business_income" in w for w in ret.warnings)


def test_per_computer_only_figures_are_kept(return_lines):
    """STANDARD DEDUCTION appears only as PER COMPUTER on this fixture."""
    ret = parse_return_transcript(return_lines, "return_2023.pdf")
    assert ret.line_items["standard_deduction"] == Decimal("13850.00")


def test_return_classification(return_lines):
    text = "\n".join(line for _p, line in return_lines)
    assert detect_type(text) == TranscriptType.RETURN
