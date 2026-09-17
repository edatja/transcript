"""Line-level parsing: the layer every parser is built on."""

from decimal import Decimal

import pytest

from irs_transcript.fields import (
    is_noise,
    normalize_label,
    parse_money,
    split_label_value,
)


@pytest.mark.parametrize("line,expected", [
    ("Federal Income Tax Withheld:....$5,000.00",
     ("Federal Income Tax Withheld", "$5,000.00")),
    # Long labels fill the line, leaving no room for dot leaders.
    ("Interest on US Savings Bonds and Treasury Obligations:$0.00",
     ("Interest on US Savings Bonds and Treasury Obligations", "$0.00")),
    # A field present but blank is a real state, not a parse failure.
    ("Total Distribution:....", ("Total Distribution", "")),
    # The label itself contains a colon.
    ("TAXABLE INTEREST INCOME: SCH B:....$980.00",
     ("TAXABLE INTEREST INCOME: SCH B", "$980.00")),
    # Quoting inside a label must survive.
    ('Code "W" Employer Contributions to a Health Savings Account:.$1,500.00',
     ('Code "W" Employer Contributions to a Health Savings Account',
      "$1,500.00")),
    ("Employer Identification Number (EIN):XX-XXX1234",
     ("Employer Identification Number (EIN)", "XX-XXX1234")),
    # A party section header: label, colon, nothing.
    ("Employer:", ("Employer", "")),
])
def test_split_label_value(line, expected):
    assert split_label_value(line) == expected


def test_split_returns_none_without_a_colon():
    assert split_label_value("ACME CORPORATION") is None
    assert split_label_value("") is None


@pytest.mark.parametrize("text,expected", [
    ("$50,000.00", Decimal("50000.00")),
    ("50,000.00", Decimal("50000.00")),
    ("-$600.00", Decimal("-600.00")),
    ("$-600.00", Decimal("-600.00")),
    ("($600.00)", Decimal("-600.00")),
    ("$0.00", Decimal("0.00")),
    ("$1,234,567.89", Decimal("1234567.89")),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "No Second Notice",
                                  "Original document", "Long-term", "7"])
def test_non_money_is_none_not_zero(text):
    """A missing amount must never become 0.00 -- that would fabricate a fact."""
    assert parse_money(text) is None


def test_zero_and_missing_stay_distinct():
    assert parse_money("$0.00") == Decimal("0")
    assert parse_money("") is None
    assert parse_money("$0.00") is not None


def test_normalize_label_collapses_punctuation_variants():
    a = normalize_label('Code "W" Employer Contributions')
    b = normalize_label("Code W Employer Contributions")
    assert a == b


@pytest.mark.parametrize("line", [
    "This Product Contains Sensitive Taxpayer Data",
    "Page 3 of 30",
    "Tracking Number: 100200300400",
    "Request Date: 03-15-2025",
    "SSN Provided: XXX-XX-4321",
    "",
])
def test_page_furniture_is_noise(line):
    assert is_noise(line)


def test_real_fields_are_not_noise():
    assert not is_noise("Wages, Tips and Other Compensation:....$50,000.00")
    assert not is_noise("ACME CORP")
