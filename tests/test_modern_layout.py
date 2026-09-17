"""The layout real IRS transcripts actually use.

Every case here comes from a defect found when the first real transcripts went
through the pipeline. The older fixture uses dot leaders; current transcripts
saved from the Get Transcript web viewer use plain "Label: value" spacing and
different label wording, and several of these differences silently dropped
money rather than failing loudly.
"""

from decimal import Decimal

import pytest

from irs_transcript.mapping import (
    distribution_codes,
    distribution_meanings,
    ira_indicator,
    refine_1099r,
)
from irs_transcript.parsers import parse_wage_and_income
from irs_transcript.rollup import flag_review_items, withholding_summary

from conftest import load_lines


@pytest.fixture(scope="module")
def docs():
    return parse_wage_and_income(
        load_lines("wage_income_modern_2025.txt"), "modern.pdf"
    )


def one(docs, form_type):
    found = [d for d in docs if d.form_type == form_type]
    assert found, f"no {form_type} parsed"
    return found[0]


def test_all_blocks_parse(docs):
    assert len(docs) == 5


def test_issuer_provider_is_a_payer_section(docs):
    """1099-NEC uses 'Issuer/Provider:' where older transcripts used 'Payer:'."""
    nec = one(docs, "1099-NEC")
    assert nec.payer_name == "RIVERSTONE TITLE LLC"
    assert nec.payer_tin == "38-0000001"


def test_federal_id_number_is_recognised_as_a_tin(docs):
    """'Issuer's/Provider's Federal ID Number' -- not 'Identification Number'.

    When this was unrecognised it closed the party section, so the payer's
    NAME on the following line was never captured.
    """
    nec = one(docs, "1099-NEC")
    assert nec.payer_name is not None
    assert nec.recipient_name == "JORDAN SAMPLE"


def test_1098_roles_are_not_inverted(docs):
    """A 1098 inverts the generic role words: the bank is 'Recipient/Lender'
    and the taxpayer is 'Payer/Borrower'. Matching on 'Payer' first filed the
    taxpayer's own SSN as the lender's EIN."""
    f1098 = one(docs, "1098")
    assert f1098.payer_name == "CASCADIA BANK, N. A."
    assert f1098.payer_tin == "94-0000002"
    assert f1098.recipient_name == "JORDAN SAMPLE"
    # An EIN, not the borrower's SSN.
    assert not f1098.payer_tin.startswith("XXX")


def test_mortgage_principal_spelling_variant(docs):
    """The transcript prints 'Outstanding mortgage principle'."""
    f1098 = one(docs, "1098")
    assert f1098.amounts["outstanding_mortgage_principal"] == \
        Decimal("156096.00")


def test_ssa_benefits_label_variant(docs):
    """'Pensions and Annuities (Total Benefits Paid)' is social security."""
    ssa = one(docs, "SSA-1099")
    assert ssa.amounts["social_security_benefits"] == Decimal("177414.00")


def test_tax_withheld_is_federal_withholding(docs):
    """1099-R blocks label withholding 'Tax Withheld'.

    Missing this reported $0 of 1099 withholding and would have cost the
    taxpayer the whole credit on line 25b.
    """
    withheld = withholding_summary(docs)
    assert withheld["from_1099_line_25b"] == Decimal("15000.00")


def test_sep_indicator_prose_means_ira(docs):
    r = [d for d in docs if d.form_type == "1099-R"]
    ira, pension = r[0], r[1]
    assert ira_indicator(ira) is True
    assert ira_indicator(pension) is False
    assert refine_1099r(ira).startswith("4a/4b")
    assert refine_1099r(pension).startswith("5a/5b")


def test_distribution_codes_are_gathered(docs):
    r = [d for d in docs if d.form_type == "1099-R"]
    assert distribution_codes(r[0]) == "1"
    assert distribution_codes(r[1]) == "G"
    assert "Early Distribution" in distribution_meanings(r[0])[0]
    # "Not significant" is padding for the unused second code position.
    assert all("Not significant" not in m for m in distribution_meanings(r[0]))


def test_early_distribution_is_flagged(docs):
    flags = flag_review_items(docs)
    early = [f for f in flags if "EARLY DISTRIBUTION" in f]
    assert len(early) == 1
    assert "5329" in early[0]
    assert "100,000.00" in early[0]


def test_rollover_is_flagged(docs):
    flags = flag_review_items(docs)
    assert any("ROLLOVER" in f and "NOT taxable" in f for f in flags)


def test_taxable_amount_not_determined_is_flagged(docs):
    flags = flag_review_items(docs)
    assert any("TAXABLE AMOUNT NOT DETERMINED" in f for f in flags)


def test_ssa_lump_sum_is_flagged(docs):
    """Prior-year SSA payments open the section 86(e) election, which can be
    worth a lot versus taxing the whole arrears in the year received."""
    flags = flag_review_items(docs)
    lump = [f for f in flags if "LUMP-SUM" in f]
    assert len(lump) == 1
    assert "2022, 2023, 2024" in lump[0]


def test_prior_year_payments_are_not_added_to_benefits(docs):
    """The TY-year rows break down the total; adding them would double it."""
    ssa = one(docs, "SSA-1099")
    assert ssa.amounts["social_security_benefits"] == Decimal("177414.00")
    assert "TY 2022 Payments" in ssa.raw_fields
