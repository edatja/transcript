"""Local, deterministic IRS transcript extraction for tax return tie-out.

Stage 1 of a two-stage pipeline: this package turns transcript PDFs into small
structured artifacts on your own machine, with no network access and no model
tokens.  Stage 2 is Claude reasoning over those artifacts.
"""

__version__ = "0.1.0"

from .models import (
    AccountTranscript,
    IncomeDocument,
    ParsedTranscript,
    ReturnTranscript,
)
from .pipeline import process_file, process_paths, process_text

__all__ = [
    "__version__",
    "AccountTranscript",
    "IncomeDocument",
    "ParsedTranscript",
    "ReturnTranscript",
    "process_file",
    "process_paths",
    "process_text",
]
