"""End-to-end: text -> real PDF -> pdfplumber -> parsers -> artifacts.

The parsers are unit-tested against text, but what breaks in production is
PDF extraction. This test builds a genuine PDF and puts it through the whole
pipeline, so glyph spacing, leader runs and page breaks stay covered.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from irs_transcript.pipeline import process_file
from irs_transcript.report import write_all

from conftest import FIXTURES
from make_fixture_pdf import text_to_pdf


@pytest.fixture(scope="module")
def transcript_pdf(tmp_path_factory):
    """A real PDF built from the fixture text, in a temp dir.

    Built rather than committed so this repository never contains a PDF --
    the habit that keeps real taxpayer documents out of version control.
    """
    out = tmp_path_factory.mktemp("pdfs") / "wage_income_2024.pdf"
    return text_to_pdf((FIXTURES / "wage_income_2024.txt").read_text(), out)


def test_pdf_has_a_text_layer(transcript_pdf):
    from irs_transcript.extract import extract_pdf
    doc = extract_pdf(transcript_pdf)
    assert doc.warnings == []
    assert all(p.has_text_layer for p in doc.pages)


def test_pipeline_over_a_real_pdf(transcript_pdf):
    result = process_file(transcript_pdf)
    assert result.transcript_type == "wage_and_income"
    assert result.tax_years == ["2024"]
    assert result.taxpayer_tin == "XXX-XX-4321"
    assert len(result.income_documents) == 11
    assert result.warnings == []


def test_amounts_survive_the_pdf_round_trip(transcript_pdf):
    result = process_file(transcript_pdf)
    w2 = [d for d in result.income_documents if d.form_type == "W-2"]
    assert sum(d.amounts["wages"] for d in w2) == Decimal("100750.00")


def test_multi_page_source_pages_are_recorded(transcript_pdf):
    """A number must be traceable to the page a PDF viewer shows."""
    result = process_file(transcript_pdf)
    pages = {d.source.page for d in result.income_documents}
    assert pages == {1, 2, 3}
    assert all(d.source.file == "wage_income_2024.pdf"
               for d in result.income_documents)


def test_all_four_artifacts_are_written(transcript_pdf, tmp_path):
    result = process_file(transcript_pdf)
    written = write_all([result], tmp_path)
    assert set(written) == {"json", "summary", "rollup", "crosscheck"}
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0


def test_summary_is_smaller_than_the_raw_pdf_text_for_a_full_transcript(
    tmp_path_factory, tmp_path
):
    """The digest must shrink a realistic transcript, not just a toy one.

    A brokerage year with dozens of 1099-B blocks is the case that matters:
    it is where raw text is worst and where aggregation earns its keep.
    """
    from irs_transcript.extract import extract_pdf

    block = (FIXTURES / "wage_income_2024.txt").read_text()
    body = block.split("Form W-2", 1)[1]
    big = block + ("\nForm W-2" + body) * 12       # ~140 information returns
    pdf = text_to_pdf(big, tmp_path_factory.mktemp("big") / "big.pdf")

    raw_chars = len(extract_pdf(pdf).text)
    result = process_file(pdf)
    written = write_all([result], tmp_path)
    digest = (written["summary"].read_text() + written["rollup"].read_text())

    assert len(digest) < raw_chars / 3


def test_json_amounts_are_strings_not_floats(transcript_pdf, tmp_path):
    """JSON floats would reintroduce binary rounding into a tax figure."""
    import json
    result = process_file(transcript_pdf)
    written = write_all([result], tmp_path)
    payload = json.loads(written["json"].read_text())
    amounts = payload["files"][0]["income_documents"][0]["amounts"]
    assert all(isinstance(v, str) for v in amounts.values())


def test_crosscheck_has_a_row_per_contribution(transcript_pdf, tmp_path):
    import csv
    result = process_file(transcript_pdf)
    written = write_all([result], tmp_path)
    with written["crosscheck"].open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["amount_on_my_return"] == ""    # preparer fills this in
    assert any(r["transcript_field"] == "wages" for r in rows)


def test_unreadable_pdf_is_reported_not_crashed(tmp_path):
    bad = tmp_path / "not_a_pdf.pdf"
    bad.write_bytes(b"this is not a PDF at all")
    from irs_transcript.pipeline import process_paths
    results = process_paths([bad])
    assert results[0].transcript_type == "unreadable"
    assert results[0].warnings and "FAILED" in results[0].warnings[0]


def test_image_only_pdf_warns_loudly(tmp_path):
    """Silent empty output is the most dangerous failure this tool can have."""
    empty = text_to_pdf("", tmp_path / "scan.pdf")
    from irs_transcript.extract import extract_pdf
    doc = extract_pdf(empty)
    assert any("NO TEXT LAYER" in w for w in doc.warnings)


def test_viewer_chrome_is_stripped_before_parsing(tmp_path):
    """Transcripts saved from the IRS web viewer carry its button labels.

    They are drawn at the same vertical position as a transcript line, so
    pdfplumber interleaves the glyphs and produces corruption such as
    "RecDiopnieent'Psr inItdentification Number" -- which matches no label
    pattern, so the field is dropped without any warning.
    """
    from irs_transcript.extract import extract_pdf

    text = (
        "Wage and Income Transcript\n"
        "Tax Period Requested: December, 2025\n"
        "Form 1099-NEC Nonemployee Compensation\n"
        "Issuer/Provider:\n"
        "Issuer's/Provider's Federal ID Number: 38-0000001\n"
        "RIVERSTONE TITLE LLC\n"
        "Recipient:\n"
        "Recipient's Identification Number: XXX-XX-9999\n"
        "JORDAN SAMPLE\n"
        "Non-Employee Compensation: $18,480.00\n"
    )
    pdf = text_to_pdf(text, tmp_path / "chrome.pdf", overlay=(7, "Done Print"))
    extracted = extract_pdf(pdf).text

    assert "Done" not in extracted and "Print" not in extracted
    # The apostrophe is normalised away because the generator's Courier
    # encoding renders ' as U+2019; the parsers match on words, not quotes.
    assert "Identification Number" in extracted
    assert "RIVERSTONE TITLE LLC" in extracted

    result = process_file(pdf)
    doc = result.income_documents[0]
    assert doc.payer_name == "RIVERSTONE TITLE LLC"
    assert doc.amounts["nonemployee_comp"] == Decimal("18480.00")


def test_chrome_filter_keeps_a_font_that_carries_real_content(tmp_path):
    """The filter must not drop a font just because chrome words appear in it.

    It only drops a font when EVERYTHING drawn in that font is chrome.
    """
    from irs_transcript.extract import extract_pdf

    text = (
        "Wage and Income Transcript\n"
        "Tax Period Requested: December, 2025\n"
        "Form W-2 Wage and Tax Statement\n"
        "Employer:\n"
        "Employer Identification Number (EIN): 35-0000009\n"
        "PRINT AND DESIGN DONE RIGHT LLC\n"
        "Wages, Tips and Other Compensation: $50,000.00\n"
    )
    pdf = text_to_pdf(text, tmp_path / "keep.pdf")
    extracted = extract_pdf(pdf).text
    assert "PRINT AND DESIGN DONE RIGHT LLC" in extracted

    result = process_file(pdf)
    assert result.income_documents[0].payer_name == \
        "PRINT AND DESIGN DONE RIGHT LLC"
