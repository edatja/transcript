"""Section 86 inclusion and the section 86(e) lump-sum election."""

from decimal import Decimal as D

import pytest

from irs_transcript.lump_sum import (
    AttributionYear,
    FilingStatus,
    compute_election,
    taxable_social_security,
    thresholds,
)


# --- the §86(a) inclusion formula -------------------------------------------

def test_below_the_base_amount_nothing_is_taxable():
    """MFJ, 20,000 other income, 20,000 benefits -> provisional 30,000."""
    r = taxable_social_security(benefits=D("20000"), other_income=D("20000"),
                            filing_status=FilingStatus.JOINT)
    assert r.provisional_income == D("30000")
    assert r.taxable == D("0")
    assert r.tier == "none"


def test_middle_tier_is_half_the_excess_over_the_base_amount():
    """MFJ, 30,000 other income, 20,000 benefits -> provisional 40,000.

    Between 32,000 and 44,000, so §86(a)(1): lesser of half the benefits
    (10,000) or half the excess over base (half of 8,000 = 4,000).
    """
    r = taxable_social_security(benefits=D("20000"), other_income=D("30000"),
                            filing_status=FilingStatus.JOINT)
    assert r.tier == "50%"
    assert r.taxable == D("4000.00")


def test_top_tier_adds_85_percent_plus_the_capped_middle_amount():
    """MFJ, 40,000 other income, 20,000 benefits -> provisional 50,000.

    §86(a)(2): 85% of (50,000 - 44,000) = 5,100, plus the lesser of the
    §86(a)(1) amount (9,000) and half the gap between the thresholds
    (half of 12,000 = 6,000) -> 11,100. Under the 85% cap of 17,000.
    """
    r = taxable_social_security(benefits=D("20000"), other_income=D("40000"),
                            filing_status=FilingStatus.JOINT)
    assert r.tier == "85%"
    assert r.taxable == D("11100.00")


def test_inclusion_never_exceeds_85_percent_of_benefits():
    r = taxable_social_security(benefits=D("50000"), other_income=D("500000"),
                            filing_status=FilingStatus.JOINT)
    assert r.taxable == D("42500.00")           # exactly 85%
    assert r.included_pct == D("85.0")


def test_single_thresholds_differ_from_joint():
    assert thresholds(FilingStatus.SINGLE) == (D("25000"), D("34000"))
    assert thresholds(FilingStatus.JOINT) == (D("32000"), D("44000"))


def test_married_filing_separately_living_together_has_zero_thresholds():
    """§86(c)(1)(C): both figures are zero, so benefits are taxed from
    the first dollar."""
    assert thresholds(FilingStatus.SEPARATE_TOGETHER) == (D("0"), D("0"))
    r = taxable_social_security(benefits=D("10000"), other_income=D("0"),
                                filing_status=FilingStatus.SEPARATE_TOGETHER)
    assert r.taxable > 0


def test_tax_exempt_interest_raises_provisional_income():
    """§86(b)(2)(B) adds it back, so 'tax-exempt' interest can still make
    benefits taxable."""
    without = taxable_social_security(benefits=D("20000"), other_income=D("20000"),
                                      filing_status=FilingStatus.JOINT)
    with_muni = taxable_social_security(benefits=D("20000"), other_income=D("20000"),
                                        filing_status=FilingStatus.JOINT,
                                        tax_exempt_interest=D("10000"))
    assert without.taxable == D("0")
    assert with_muni.taxable > 0


def test_zero_benefits_is_zero_not_an_error():
    r = taxable_social_security(benefits=D("0"), other_income=D("100000"),
                            filing_status=FilingStatus.JOINT)
    assert r.taxable == D("0")


def test_unknown_filing_status_is_rejected():
    with pytest.raises(ValueError, match="unknown filing status"):
        thresholds("married-ish")


# --- the §86(e) election ----------------------------------------------------

def _years(**overrides):
    base = [
        AttributionYear(year="2023", arrears=D("44256"), other_income=D("20000"),
                        filing_status=FilingStatus.JOINT),
        AttributionYear(year="2024", arrears=D("45672"), other_income=D("21136"),
                        filing_status=FilingStatus.JOINT),
    ]
    for y in base:
        for key, value in overrides.items():
            setattr(y, key, value)
    return base


def test_election_caps_inclusion_at_the_prior_year_increases():
    result = compute_election(
        total_benefits=D("120000"),
        current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=_years(),
    )
    # Without: the whole thing at the 85% cap.
    assert result.without_election.taxable == D("102000.00")
    # With: only the current-year portion plus the prior-year increases.
    assert result.with_election == (
        result.current_portion_only.taxable + result.ceiling
    )
    assert result.election_helps
    assert result.savings > 0


def test_ceiling_is_the_sum_of_each_year_s_increase():
    result = compute_election(
        total_benefits=D("120000"),
        current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=_years(),
    )
    assert result.ceiling == sum(y.increase for y in result.years)


def test_a_low_income_prior_year_produces_a_small_increase():
    """The 2024 year from the real fact pattern: 21,136 of other income and
    45,672 of arrears lands just under the 44,000 threshold."""
    r = taxable_social_security(benefits=D("45672"), other_income=D("21136"),
                            filing_status=FilingStatus.JOINT)
    assert r.provisional_income == D("43972.00")
    assert r.tier == "50%"
    assert r.taxable == D("5986.00")


def test_election_is_not_recommended_when_it_does_not_help():
    """A taxpayer whose prior years were high-income gains nothing."""
    result = compute_election(
        total_benefits=D("60000"),
        current_year_other_income=D("0"),
        current_year_filing_status=FilingStatus.JOINT,
        years=[AttributionYear(year="2024", arrears=D("30000"),
                               other_income=D("400000"),
                               filing_status=FilingStatus.JOINT)],
    )
    assert not result.election_helps
    assert any("does NOT reduce" in w for w in result.warnings)


def test_prior_year_benefits_already_received_are_stacked():
    """Arrears add on top of what that year already paid, which can push the
    year into a higher tier than the arrears alone would."""
    alone = compute_election(
        total_benefits=D("60000"), current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=[AttributionYear(year="2024", arrears=D("30000"),
                               other_income=D("30000"),
                               filing_status=FilingStatus.JOINT)],
    )
    stacked = compute_election(
        total_benefits=D("60000"), current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=[AttributionYear(year="2024", arrears=D("30000"),
                               other_income=D("30000"),
                               benefits_already_received=D("20000"),
                               filing_status=FilingStatus.JOINT)],
    )
    assert stacked.ceiling > alone.ceiling


# --- refusing to answer on partial data -------------------------------------

def test_a_missing_year_suppresses_the_bottom_line():
    """Omitting a year understates the ceiling, which makes the election look
    better than it is. The result must refuse to total."""
    years = _years()
    years[0].known = False
    result = compute_election(
        total_benefits=D("120000"),
        current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=years,
    )
    assert not result.complete
    assert result.unknown_years == ["2023"]
    assert result.savings == D("0")
    assert not result.election_helps
    assert any("INCOMPLETE" in w for w in result.warnings)


def test_known_years_still_compute_when_another_is_missing():
    years = _years()
    years[0].known = False
    result = compute_election(
        total_benefits=D("120000"), current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT, years=years,
    )
    known = [y for y in result.years if y.known]
    assert known[0].increase > 0


def test_worksheet_markdown_withholds_a_total_when_incomplete():
    from irs_transcript.report import build_lump_sum_markdown
    years = _years()
    years[0].known = False
    result = compute_election(
        total_benefits=D("120000"), current_year_other_income=D("200000"),
        current_year_filing_status=FilingStatus.JOINT, years=years,
    )
    markdown = build_lump_sum_markdown(result, "2025")
    assert "No bottom line yet" in markdown
    assert "Reduction in taxable income" not in markdown


def test_arrears_exceeding_total_benefits_is_flagged():
    result = compute_election(
        total_benefits=D("10000"), current_year_other_income=D("50000"),
        current_year_filing_status=FilingStatus.JOINT,
        years=[AttributionYear(year="2024", arrears=D("40000"),
                               other_income=D("10000"),
                               filing_status=FilingStatus.JOINT)],
    )
    assert any("exceed total benefits" in w for w in result.warnings)


# --- CSV round trip ---------------------------------------------------------

def test_csv_round_trip(tmp_path):
    from irs_transcript.report import read_lump_sum_csv
    path = tmp_path / "ls.csv"
    path.write_text(
        "# a comment line is ignored\n"
        "year,role,amount,your_magi_that_year,filing_status,"
        "ss_already_received_that_year,tax_exempt_interest\n"
        "2025,year_of_receipt,177414.00,196224.00,joint,0,0\n"
        "2024,prior_year,45672.00,21136.00,joint,0,0\n"
        "2023,prior_year,44256.00,,joint,0,0\n"
    )
    receipt, years = read_lump_sum_csv(path)
    assert receipt["total_benefits"] == D("177414.00")
    assert receipt["filing_status"] == "joint"
    assert len(years) == 2
    assert years[0].known is True and years[0].other_income == D("21136.00")
    # A blank MAGI means "not known", not zero.
    assert years[1].known is False


def test_csv_rejects_a_bad_filing_status(tmp_path):
    from irs_transcript.report import read_lump_sum_csv
    path = tmp_path / "bad.csv"
    path.write_text(
        "year,role,amount,your_magi_that_year,filing_status,"
        "ss_already_received_that_year,tax_exempt_interest\n"
        "2025,year_of_receipt,1000,1000,marriedish,0,0\n"
    )
    with pytest.raises(ValueError, match="filing_status"):
        read_lump_sum_csv(path)


def test_csv_requires_the_year_of_receipt_row(tmp_path):
    from irs_transcript.report import read_lump_sum_csv
    path = tmp_path / "noreceipt.csv"
    path.write_text(
        "year,role,amount,your_magi_that_year,filing_status,"
        "ss_already_received_that_year,tax_exempt_interest\n"
        "2024,prior_year,45672,21136,joint,0,0\n"
    )
    with pytest.raises(ValueError, match="year_of_receipt"):
        read_lump_sum_csv(path)


def test_template_is_prefilled_from_the_ssa_1099(tmp_path):
    """The arrears rows come straight off the transcript, so the preparer only
    has to add the prior-year income figures no transcript can supply."""
    from irs_transcript.models import IncomeDocument, ParsedTranscript, SourceRef
    from irs_transcript.report import write_lump_sum_template

    doc = IncomeDocument(
        form_type="SSA-1099", tax_year="2025",
        amounts={"social_security_benefits": D("177414.00")},
        raw_fields={
            "Pensions and Annuities (Total Benefits Paid)": "$177,414.00",
            "TY 2024 Payments": "$45,672.00",
            "TY 2023 Payments": "$44,256.00",
            "TY 2022 Payments": "$40,674.00",
        },
        source=SourceRef("t.pdf", 1),
    )
    result = ParsedTranscript(file="t.pdf", transcript_type="wage_and_income",
                              income_documents=[doc])
    path = write_lump_sum_template([result], tmp_path / "ls.csv")
    assert path is not None
    body = path.read_text()
    assert "2025,year_of_receipt,177414.00" in body
    assert "2024,prior_year,45672.00" in body
    assert "2022,prior_year,40674.00" in body


def test_no_template_when_there_are_no_prior_year_rows(tmp_path):
    from irs_transcript.models import IncomeDocument, ParsedTranscript
    from irs_transcript.report import write_lump_sum_template
    doc = IncomeDocument(form_type="SSA-1099", tax_year="2025",
                         amounts={"social_security_benefits": D("20000")})
    result = ParsedTranscript(file="t.pdf", transcript_type="wage_and_income",
                              income_documents=[doc])
    assert write_lump_sum_template([result], tmp_path / "ls.csv") is None


def test_positional_arguments_are_rejected():
    """Benefits and income are both money. A positional call could pass them
    the wrong way round and get a confident wrong answer, so the signature
    forbids it."""
    with pytest.raises(TypeError):
        taxable_social_security(D("20000"), D("30000"), FilingStatus.JOINT)
