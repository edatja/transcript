"""Parsing of the ``Label:.....$Value`` lines that IRS transcripts are made of.

Almost every fact on an IRS transcript is printed as a label, a colon, a run
of dot leaders, and a value::

    Wages, Tips and Other Compensation:..................$50,000.00
    Federal Income Tax Withheld:.........................$5,000.00
    Distribution Code(s):................................7
    Employer Identification Number (EIN):XX-XXX1234

The dot run is cosmetic padding so values line up in the right margin.  When
a label is long enough to fill the line there are no dots at all, so both
shapes have to be handled.  This module is the single place that knows how.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# A label, a colon, one or more dot leaders, then the value.
# The label is non-greedy so we split at the FIRST colon that is immediately
# followed by dots -- that is unambiguously the leader, not a colon inside
# the label text.
_DOT_LEADER = re.compile(r"^(?P<label>.*?):\.+\s*(?P<value>.*)$")

# No dots: a colon followed by whitespace-or-nothing then the value.
# Used only as a fallback; we split on the LAST such colon because labels
# like 'Code "Q" Nontaxable Combat Pay' may contain punctuation but the
# value never contains a colon in these transcripts.
_PLAIN_COLON = re.compile(r"^(?P<label>.*):(?!\S*:)\s*(?P<value>.*)$")

# Money as the IRS prints it: $50,000.00  -$600.00  $0.00  50,000.00
# The sign may lead the dollar sign or follow it, and negatives sometimes
# appear in parentheses on older transcript formats.
_MONEY = re.compile(
    r"^\(?\s*(?P<sign>[-+])?\s*\$?\s*(?P<sign2>[-+])?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*\)?$"
)

# Lines that are page furniture, not data.
#
# The IRS reprints the request header at every page break, which lands in the
# MIDDLE of a form block whenever a block straddles a page. Those lines look
# like ordinary "Label: value" fields, so unless they are filtered here they
# terminate the payer section and the payer's NAME is lost. Filtering them is
# safe because no information return has a box by any of these names, and the
# document header is read from unfiltered text before parsing begins.
_NOISE = re.compile(
    r"^(?:"
    r"This Product Contains Sensitive Taxpayer Data"
    r"|Page\s+\d+\s+of\s+\d+"
    r"|Tracking\s+Number\s*:.*"
    r"|Re(?:quest|sponse)\s+Date\s*:.*"
    r"|(?:SSN|EIN|TIN)\s+Provided\s*:.*"
    r"|Tax\s+Period\s+(?:Requested|Ending)\s*:.*"
    # Browser print furniture. A transcript saved with File > Print carries
    # the browser's own header and footer on every page, and those land in
    # the middle of form blocks just like the IRS's own repeated header.
    # "2 of 3 9/18/2026, 10:29 AM" splits on the clock's colon into a
    # label/value pair, which ends the party section and loses the payer
    # NAME on the next line. No transcript field value is ever a URL.
    r"|\d+\s+of\s+\d+\s+\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}(?:\s*[AP]M)?"
    r"|.*https?://\S+.*"
    r"|-{3,}|={3,}|\.{3,}|_{3,}"
    r"|\s*"
    r")$",
    re.IGNORECASE,
)


def is_noise(line: str) -> bool:
    """True for page headers/footers/rules that carry no data."""
    return bool(_NOISE.match(line.strip()))


def split_label_value(line: str) -> tuple[str, str] | None:
    """Split one transcript line into ``(label, value)``.

    Returns ``None`` if the line has no ``label:value`` shape at all.

    >>> split_label_value("Federal Income Tax Withheld:....$5,000.00")
    ('Federal Income Tax Withheld', '$5,000.00')
    >>> split_label_value("Interest on US Savings Bonds:$0.00")
    ('Interest on US Savings Bonds', '$0.00')
    >>> split_label_value("Total Distribution:......")
    ('Total Distribution', '')
    """
    line = line.rstrip()
    if not line or ":" not in line:
        return None

    m = _DOT_LEADER.match(line)
    if not m:
        m = _PLAIN_COLON.match(line)
    if not m:
        return None

    label = m.group("label").strip()
    # A trailing run of dots belongs to the leader, not to the value.
    value = m.group("value").strip().strip(".").strip()
    if not label:
        return None
    return label, value


def parse_money(value: str | None) -> Decimal | None:
    """Parse an IRS-printed money string into ``Decimal``.

    Returns ``None`` when the field is blank or is not a number -- never 0,
    because "the transcript did not report this" and "the transcript reported
    zero" are different facts.

    >>> parse_money("$50,000.00")
    Decimal('50000.00')
    >>> parse_money("-$600.00")
    Decimal('-600.00')
    >>> parse_money("") is None
    True
    >>> parse_money("No Second Notice") is None
    True
    >>> parse_money("7") is None       # a distribution code, not $7.00
    True
    >>> parse_money("0.00")
    Decimal('0.00')
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")

    m = _MONEY.match(text)
    if not m:
        return None

    num = m.group("num").replace(",", "")

    # IRS transcripts always print money with a dollar sign, cents, or both.
    # A bare integer is an indicator or a code -- a 1099-R distribution code
    # "7", an exemption count "01", a posting cycle "20251805" -- and reading
    # one as $7.00 would invent an amount that is not on the transcript.
    has_dollar_sign = "$" in text
    has_cents = "." in num and len(num.split(".")[-1]) == 2
    if not (has_dollar_sign or has_cents):
        return None
    try:
        amount = Decimal(num)
    except InvalidOperation:
        return None

    if m.group("sign") == "-" or m.group("sign2") == "-" or negative:
        amount = -amount
    return amount


def normalize_label(label: str) -> str:
    """Canonical form of a label for alias lookup.

    Lowercases, drops punctuation and collapses whitespace so that
    ``Code "W" Employer Contributions to a Health Savings Account`` and
    ``Code W Employer Contributions to a Health Savings Account`` are the
    same key.  Real transcripts are inconsistent about quoting and hyphens.
    """
    text = label.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_field_lines(lines: list[str]) -> dict[str, str]:
    """Collect every ``label: value`` pair from a block of transcript lines.

    Later occurrences of the same label do not clobber earlier ones -- the
    second gets a ``" (2)"`` suffix.  Some forms legitimately repeat a label
    (e.g. multiple state rows on a W-2) and silently dropping one would lose
    money.
    """
    out: dict[str, str] = {}
    for raw in lines:
        if is_noise(raw):
            continue
        pair = split_label_value(raw)
        if pair is None:
            continue
        label, value = pair
        if label in out:
            n = 2
            while f"{label} ({n})" in out:
                n += 1
            label = f"{label} ({n})"
        out[label] = value
    return out
