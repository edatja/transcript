"""Roll-up, mapping and double-counting protection."""

from decimal import Decimal

from irs_transcript.mapping import is_memo, line_for
from irs_transcript.rollup import build_rollup, flag_review_items, withholding_summary


def test_wages_roll_up_to_line_1a(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    assert rollup.total_for("Form 1040", "1a") == Decimal("100750.00")


def test_withholding_splits_by_1040_line(wage_income_docs):
    wh = withholding_summary(wage_income_docs)
    assert wh["from_w2_line_25a"] == Decimal("9860.00")     # 9120 + 740
    assert wh["from_1099_line_25b"] == Decimal("3480.00")   # 3000 + 480
    assert wh["total"] == Decimal("13340.00")


def test_qualified_dividends_are_not_added_to_income():
    """Qualified dividends are a SUBSET of ordinary dividends, not extra
    income. Totalling both would overstate income by the qualified amount."""
    assert is_memo("qualified_dividends")


def test_1099r_taxable_amount_is_not_double_counted():
    """Gross distribution and taxable amount describe the same money."""
    assert is_memo("taxable_amount")


def test_memo_fields_stay_out_of_line_totals(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    memo_fields = {c.field_name for c in rollup.memo}
    assert "qualified_dividends" in memo_fields
    # 3b carries ordinary dividends only, not ordinary + qualified.
    assert rollup.total_for("Form 1040", "3b") == Decimal("3400.00")


def test_memo_amounts_are_still_reported_not_discarded(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    qualified = [c for c in rollup.memo
                 if c.field_name == "qualified_dividends"]
    assert qualified[0].amount == Decimal("2900.00")


def test_1099r_ira_indicator_picks_line_4_or_line_5(wage_income_docs):
    """An IRA distribution belongs on 1040 line 4, a pension on line 5."""
    rollup = build_rollup(wage_income_docs, "2024")
    pension = [e for e in rollup.lines if "pension" in e.target.line]
    assert pension and pension[0].total == Decimal("15000.00")


def test_ssa_benefits_land_on_line_6a(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    assert rollup.total_for("Form 1040", "6a") == Decimal("9600.00")


def test_nec_routes_to_schedule_c(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    assert rollup.total_for("Schedule C", "1") == Decimal("24000.00")


def test_every_total_names_its_source_documents(wage_income_docs):
    """A mismatch must be traceable to a payer without re-reading the PDF."""
    rollup = build_rollup(wage_income_docs, "2024")
    line_1a = [e for e in rollup.lines
               if e.target.form == "Form 1040" and e.target.line == "1a"][0]
    payers = {c.document.payer_name for c in line_1a.contributions}
    assert payers == {"NORTHWIND TRADING LLC", "CASCADE STAFFING INC"}


def test_lines_are_ordered_down_the_return(wage_income_docs):
    rollup = build_rollup(wage_income_docs, "2024")
    f1040 = [e.target.line for e in rollup.lines
             if e.target.form == "Form 1040"]
    assert f1040[0] == "1a"
    assert f1040.index("2b") < f1040.index("25a")


def test_withholding_from_1099_does_not_land_on_line_25a():
    from irs_transcript.models import IncomeDocument
    doc = IncomeDocument(form_type="1099-R", tax_year="2024",
                         amounts={"federal_withholding": Decimal("3000")})
    assert line_for("1099-R", "federal_withholding").line == "25b"


def test_1095a_forces_a_form_8962_flag():
    from irs_transcript.models import IncomeDocument
    docs = [IncomeDocument(form_type="1095-A", tax_year="2024")]
    flags = flag_review_items(docs)
    assert any("8962" in f for f in flags)


def test_corrected_forms_are_flagged():
    from irs_transcript.models import IncomeDocument
    docs = [IncomeDocument(form_type="W-2", payer_name="ACME",
                           submission_type="Corrected document")]
    assert any("CORRECTED" in f for f in flag_review_items(docs))


def test_1099k_overlap_is_flagged():
    from irs_transcript.models import IncomeDocument
    docs = [IncomeDocument(form_type="1099-K"),
            IncomeDocument(form_type="1099-NEC")]
    flags = flag_review_items(docs)
    assert any("1099-K" in f and "overstated" in f for f in flags)
