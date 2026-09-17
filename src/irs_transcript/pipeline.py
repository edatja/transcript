"""Tie extraction, classification and parsing together.

``process_text`` is the real work and takes a string, so the whole pipeline is
testable against fixtures.  ``process_file`` is the thin wrapper that opens a
PDF first.
"""

from __future__ import annotations

from pathlib import Path

from .classify import TranscriptType, parse_header
from .extract import extract_pdf
from .models import ParsedTranscript
from .parsers import (
    parse_account_transcript,
    parse_return_transcript,
    parse_wage_and_income,
)


def process_text(
    lines_with_pages: list[tuple[int, str]],
    source_file: str,
    pages: int = 1,
    extra_warnings: list[str] | None = None,
) -> ParsedTranscript:
    """Classify and parse an already-extracted transcript."""
    text = "\n".join(line for _page, line in lines_with_pages)
    header = parse_header(text)

    result = ParsedTranscript(
        file=source_file,
        transcript_type=header.transcript_type,
        pages=pages,
        tax_years=header.tax_years,
        taxpayer_tin=header.taxpayer_tin,
        request_date=header.request_date,
        warnings=list(extra_warnings or []),
    )

    kind = header.transcript_type
    if kind == TranscriptType.WAGE_AND_INCOME:
        result.income_documents = parse_wage_and_income(
            lines_with_pages, source_file
        )
        if not result.income_documents:
            result.warnings.append(
                "classified as Wage & Income but no form blocks were found -- "
                "the transcript may genuinely be empty (no information returns "
                "filed for this year), or the layout is unrecognized"
            )
    elif kind == TranscriptType.ACCOUNT:
        result.account = parse_account_transcript(lines_with_pages, source_file)
    elif kind == TranscriptType.RETURN:
        result.tax_return = parse_return_transcript(lines_with_pages, source_file)
    elif kind == TranscriptType.RECORD_OF_ACCOUNT:
        # Contains both products; run both parsers over the whole document
        # rather than trying to guess the split point.
        result.tax_return = parse_return_transcript(lines_with_pages, source_file)
        result.account = parse_account_transcript(lines_with_pages, source_file)
    else:
        result.warnings.append(
            "could not identify this as an IRS transcript -- nothing parsed. "
            "Expected a PDF from IRS.gov Get Transcript or a TDS delivery."
        )

    # Fall back to years found inside the parsed content when the header did
    # not state one.
    if not result.tax_years:
        found = {d.tax_year for d in result.income_documents if d.tax_year}
        for obj in (result.account, result.tax_return):
            if obj is not None and obj.tax_year:
                found.add(obj.tax_year)
        result.tax_years = sorted(y for y in found if y)

    for obj in (result.account, result.tax_return):
        if obj is not None:
            result.warnings.extend(obj.warnings)

    return result


def process_file(path: str | Path) -> ParsedTranscript:
    """Extract and parse one transcript PDF."""
    path = Path(path)
    doc = extract_pdf(path)
    return process_text(
        doc.lines_with_pages,
        source_file=path.name,
        pages=len(doc.pages),
        extra_warnings=doc.warnings,
    )


def process_paths(paths: list[Path]) -> list[ParsedTranscript]:
    """Parse several PDFs, keeping going when one fails."""
    results: list[ParsedTranscript] = []
    for path in paths:
        try:
            results.append(process_file(path))
        except Exception as exc:
            results.append(
                ParsedTranscript(
                    file=path.name,
                    transcript_type="unreadable",
                    warnings=[f"FAILED: {exc}"],
                )
            )
    return results
