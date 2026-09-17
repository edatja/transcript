"""Shared fixtures.

Every fixture here is synthetic. No real taxpayer document is ever committed
to this repository -- see CLAUDE.md rule 3.
"""

from pathlib import Path

import pytest

from irs_transcript.extract import clean_text

FIXTURES = Path(__file__).parent / "fixtures"


def load_lines(name: str) -> list[tuple[int, str]]:
    """Fixture text as (page, line) pairs, cleaned the way extraction cleans."""
    text = clean_text((FIXTURES / name).read_text())
    # Page 1 throughout: page numbering is exercised by the PDF round-trip test.
    return [(1, line) for line in text.splitlines()]


@pytest.fixture
def wage_income_lines():
    return load_lines("wage_income_2024.txt")


@pytest.fixture
def account_lines():
    return load_lines("account_2024.txt")


@pytest.fixture
def return_lines():
    return load_lines("return_2023.txt")


@pytest.fixture
def wage_income_docs(wage_income_lines):
    from irs_transcript.parsers import parse_wage_and_income
    return parse_wage_and_income(wage_income_lines, "wage_income_2024.pdf")
