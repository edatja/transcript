"""One parser module per IRS transcript product.

Every parser takes *text* (plus page numbers) rather than a file path, so it
can be tested against synthetic fixtures and never needs real taxpayer data.
"""

from .wage_income import parse_wage_and_income
from .account import parse_account_transcript
from .return_transcript import parse_return_transcript

__all__ = [
    "parse_wage_and_income",
    "parse_account_transcript",
    "parse_return_transcript",
]
