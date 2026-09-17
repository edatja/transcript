"""Artifact rendering."""

from decimal import Decimal

from irs_transcript.models import IncomeDocument, ParsedTranscript, SourceRef
from irs_transcript.report import (
    GROUP_DETAIL_LIMIT,
    build_rollup_markdown,
    build_summary,
)
from irs_transcript.rollup import build_rollup


def _doc(form_type, payer, **amounts):
    return IncomeDocument(
        form_type=form_type,
        tax_year="2024",
        payer_name=payer,
        amounts={k: Decimal(str(v)) for k, v in amounts.items()},
        source=SourceRef("t.pdf", 1),
    )


def test_source_counts_are_documents_not_contributions():
    """A single 1099-INT feeding line 2b twice (box 1 and box 3) must not be
    rendered as two 1099-INTs -- that sends the preparer hunting for a form
    that does not exist."""
    doc = _doc("1099-INT", "FIRST HARBOR BANK",
               interest=1240, savings_bond_interest=500)
    markdown = build_rollup_markdown({"2024": build_rollup([doc], "2024")})
    assert "1099-INT ×1" in markdown
    assert "1099-INT ×2" not in markdown


def test_large_groups_are_aggregated_by_payer(wage_income_docs):
    many = [_doc("1099-B", "MERIDIAN BROKERAGE", gross_proceeds=1000)
            for _ in range(GROUP_DETAIL_LIMIT + 1)]
    result = ParsedTranscript(file="t.pdf", transcript_type="wage_and_income",
                              income_documents=many)
    summary = build_summary([result])
    assert "aggregated" in summary
    # One aggregate row, not one row per document.
    assert summary.count("MERIDIAN BROKERAGE") == 1


def test_small_groups_are_listed_individually():
    few = [_doc("W-2", f"EMPLOYER {i}", wages=1000) for i in range(3)]
    result = ParsedTranscript(file="t.pdf", transcript_type="wage_and_income",
                              income_documents=few)
    summary = build_summary([result])
    for i in range(3):
        assert f"EMPLOYER {i}" in summary


def test_extraction_warnings_are_surfaced_prominently():
    result = ParsedTranscript(
        file="t.pdf", transcript_type="wage_and_income",
        warnings=["pages [4, 5] have no text layer and were skipped"],
    )
    summary = build_summary([result])
    assert "Extraction warnings" in summary
    assert "no text layer" in summary


def test_zero_amounts_are_counted_not_listed():
    doc = _doc("1099-INT", "BANK", interest=100, bond_premium=0,
               market_discount=0)
    result = ParsedTranscript(file="t.pdf", transcript_type="wage_and_income",
                              income_documents=[doc])
    summary = build_summary([result])
    assert "interest **100.00**" in summary
    assert "2 other box(es) reported $0.00" in summary


def test_memo_amounts_are_shown_but_marked_as_excluded(wage_income_docs):
    markdown = build_rollup_markdown(
        {"2024": build_rollup(wage_income_docs, "2024")}
    )
    assert "NOT totalled" in markdown
    assert "qualified dividends: 2,900.00" in markdown


def test_csv_text_cells_cannot_become_spreadsheet_formulas(tmp_path):
    from irs_transcript.report import write_crosscheck
    doc = _doc("W-2", "=cmd|'/c calc'!A1", wages=1000)
    path = write_crosscheck(
        {"2024": build_rollup([doc], "2024")}, tmp_path / "c.csv"
    )
    body = path.read_text()
    assert "'=cmd" in body        # neutralised with a leading apostrophe
    assert "\n2024,W-2,=cmd" not in body
