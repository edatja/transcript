"""Wage & Income transcript parsing."""

from decimal import Decimal

import pytest

from irs_transcript.classify import TranscriptType, detect_type
from irs_transcript.parsers import parse_wage_and_income
from irs_transcript.parsers.wage_income import total

from conftest import FIXTURES


def by_type(docs, form_type):
    return [d for d in docs if d.form_type == form_type]


def test_every_form_block_is_found(wage_income_docs):
    assert len(wage_income_docs) == 11


def test_form_types_are_identified(wage_income_docs):
    found = sorted({d.form_type for d in wage_income_docs})
    assert found == [
        "1098", "1098-E", "1099-DIV", "1099-G", "1099-INT", "1099-NEC",
        "1099-R", "5498", "SSA-1099", "W-2",
    ]


def test_longer_form_codes_win_over_their_prefixes(wage_income_docs):
    """1098-E must not be parsed as 1098, nor W-2G as W-2."""
    assert len(by_type(wage_income_docs, "1098")) == 1
    assert len(by_type(wage_income_docs, "1098-E")) == 1


def test_w2_amounts(wage_income_docs):
    w2 = by_type(wage_income_docs, "W-2")
    assert len(w2) == 2
    assert w2[0].payer_name == "NORTHWIND TRADING LLC"
    assert w2[0].payer_tin == "XX-XXX1111"
    assert w2[0].amounts["wages"] == Decimal("88450.00")
    assert w2[0].amounts["federal_withholding"] == Decimal("9120.00")
    assert w2[0].amounts["hsa_employer_contributions"] == Decimal("1500.00")
    assert total(w2, "wages") == Decimal("100750.00")


def test_payer_and_recipient_are_not_confused(wage_income_docs):
    nec = by_type(wage_income_docs, "1099-NEC")[0]
    assert nec.payer_name == "ORCHID DESIGN CO"
    assert nec.payer_tin == "XX-XXX3333"
    assert nec.recipient_name == "PAT SAMPLE"
    assert nec.recipient_tin == "XXX-XX-4321"


def test_ssa_pensions_label_maps_to_social_security(wage_income_docs):
    """SSA-1099 prints its benefit under the label 'Pensions and Annuities'.

    Treating that as pension income would put it on 1040 line 5a instead of
    6a and change the taxable amount entirely.
    """
    ssa = by_type(wage_income_docs, "SSA-1099")[0]
    assert ssa.amounts["social_security_benefits"] == Decimal("9600.00")
    assert "gross_distribution" not in ssa.amounts


def test_blank_fields_are_absent_not_zero(wage_income_docs):
    r = by_type(wage_income_docs, "1099-R")[0]
    # "Taxable Amount Not Determined:" is blank on this fixture.
    assert r.raw_fields["Taxable Amount Not Determined"] == ""
    assert "taxable_amount_not_determined" not in r.amounts


def test_indicators_are_kept_as_text(wage_income_docs):
    r = by_type(wage_income_docs, "1099-R")[0]
    assert r.raw_fields["Distribution Code(s)"] == "7"
    assert r.submission_type == "Original document"


def test_unmapped_labels_are_still_preserved(wage_income_docs):
    """CLAUDE.md rule 4: unknown is preserved, never dropped."""
    w2 = by_type(wage_income_docs, "W-2")[0]
    assert "Third Party Sick Pay Indicator" in w2.raw_fields


def test_tax_year_attaches_to_every_document(wage_income_docs):
    assert {d.tax_year for d in wage_income_docs} == {"2024"}


def test_clean_parse_produces_no_warnings(wage_income_docs):
    noisy = [(d.label, d.warnings) for d in wage_income_docs if d.warnings]
    assert noisy == []


def test_classification(wage_income_lines):
    text = "\n".join(line for _p, line in wage_income_lines)
    assert detect_type(text) == TranscriptType.WAGE_AND_INCOME


# --- regression tests -------------------------------------------------------

def test_leader_run_does_not_swallow_the_following_line():
    """Regression: a dot leader with no value sits against the newline.

    Collapsing leaders with an \\s-based pattern welded the next line onto it
    and silently deleted every field on that line.
    """
    from irs_transcript.extract import clean_text
    text = clean_text(
        "Form 1099-NEC\n"
        "Account Number (Optional):..........................\n"
        "Non-Employee Compensation:..........................$24,000.00\n"
    )
    assert "Non-Employee Compensation" in text.splitlines()[2]
    docs = parse_wage_and_income(
        [(1, line) for line in text.splitlines()], "x.pdf"
    )
    assert docs[0].amounts["nonemployee_comp"] == Decimal("24000.00")


def test_page_header_inside_a_block_does_not_lose_the_payer():
    """Regression: the IRS reprints its header at every page break.

    When that lands between 'Payer:' and the payer's name, an unfiltered
    header line ended the payer section and the name was lost.
    """
    lines = [
        "Form 1099-INT",
        "Payer:",
        "This Product Contains Sensitive Taxpayer Data",
        "Tracking Number: 100200300400",
        "Page 4 of 30",
        "Payer's Federal Identification Number (FIN):XX-XXX4444",
        "FIRST HARBOR BANK",
        "Interest:....$1,240.00",
    ]
    docs = parse_wage_and_income([(1, line) for line in lines], "x.pdf")
    assert docs[0].payer_name == "FIRST HARBOR BANK"
    assert docs[0].payer_tin == "XX-XXX4444"
    assert docs[0].amounts["interest"] == Decimal("1240.00")


def test_a_form_name_inside_a_data_line_does_not_start_a_block():
    lines = [
        "Form W-2 Wage and Tax Statement",
        "Wages, Tips and Other Compensation:....$50,000.00",
        "Wages from Form 8919:....$0.00",
    ]
    docs = parse_wage_and_income([(1, line) for line in lines], "x.pdf")
    assert len(docs) == 1
