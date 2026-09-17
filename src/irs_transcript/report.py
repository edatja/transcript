"""Write the four output artifacts.

  transcripts.json  everything, page-traceable. The archive of record.
  summary.md        compact digest -- this is what Claude reads.
  crosscheck.csv    a tie-out worksheet, one row per amount.
  rollup.md         totals grouped by the return line they belong to.

``summary.md`` exists specifically so a PDF never has to enter a model's
context.  A Wage & Income transcript runs to tens of thousands of tokens as
raw text; the same information lands here in roughly a tenth of that, because
zero-valued boxes are counted rather than listed and page furniture is gone.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .classify import TranscriptType, describe
from .fields import parse_money
from .models import ParsedTranscript
from .parsers.account import PAYMENT_CODES, payments_and_credits
from .rollup import Rollup, build_rollup, flag_review_items, withholding_summary

# Cells starting with these are treated as formulas by Excel and Sheets.
# Transcript text is IRS-generated, but a payer name beginning with '=' would
# still execute on open, so text cells get quoted. Numeric cells never are --
# that would break negative amounts.
_FORMULA_LEAD = ("=", "+", "@", "\t", "\r")


def _safe_text(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_LEAD):
        return "'" + text
    return text


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value:,.2f}"


def pretty_field(name: str) -> str:
    """'federal_withholding' -> 'federal withholding'."""
    return name.replace("_", " ")


# ---------------------------------------------------------------------------
# transcripts.json
# ---------------------------------------------------------------------------
def write_json(results: list[ParsedTranscript], path: Path) -> Path:
    payload = {
        "generated": date.today().isoformat(),
        "generator": "irs-transcript 0.1.0",
        "disclaimer": (
            "Every amount is a literal string read from the PDF text layer. "
            "Totals are plain sums of those values. Nothing is estimated."
        ),
        "files": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------
# Above this many documents of one form type, the digest aggregates by payer
# instead of listing each one. A brokerage year routinely has 60+ separate
# 1099-B blocks; listing them individually buries the return-relevant facts
# and is exactly the bloat this digest exists to avoid. Per-document detail
# stays in transcripts.json and crosscheck.csv.
GROUP_DETAIL_LIMIT = 12


def _amount_text(amounts: dict, zeros: int) -> str:
    parts = [f"{pretty_field(k)} **{v:,.2f}**" for k, v in sorted(amounts.items())]
    if zeros:
        parts.append(f"_{zeros} other box(es) reported $0.00_")
    return "; ".join(parts)


def _detail_rows(group: list) -> list[str]:
    lines = ["| Payer / employer | TIN | Reported amounts | Src |",
             "|---|---|---|---|"]
    for doc in group:
        nonzero = {k: v for k, v in doc.amounts.items() if v != 0}
        text = _amount_text(nonzero, len(doc.amounts) - len(nonzero))
        extras = []
        code = doc.raw_fields.get("Distribution Code(s)")
        if code:
            extras.append(f"dist code `{code}`")
        if doc.submission_type and \
                not doc.submission_type.lower().startswith("original"):
            extras.append(f"**{doc.submission_type}**")
        if extras:
            text = "; ".join(filter(None, [text, "; ".join(extras)]))
        page = doc.source.page if doc.source else "?"
        lines.append(
            f"| {doc.payer_name or '_(not stated)_'} "
            f"| {doc.payer_tin or ''} "
            f"| {text or '_no amounts parsed_'} "
            f"| p.{page} |"
        )
    return lines


def _aggregated_rows(group: list) -> list[str]:
    """Collapse a large group into one row per payer."""
    by_payer: dict[str, list] = {}
    for doc in group:
        by_payer.setdefault(doc.payer_name or "(payer not stated)", []).append(doc)

    lines = [
        f"_{len(group)} documents from {len(by_payer)} payer(s), aggregated. "
        f"Per-document detail is in `transcripts.json` and `crosscheck.csv`._",
        "",
        "| Payer / employer | Docs | Totals across those documents |",
        "|---|---|---|",
    ]
    for payer in sorted(by_payer):
        docs = by_payer[payer]
        totals: dict[str, Decimal] = {}
        for doc in docs:
            for key, value in doc.amounts.items():
                totals[key] = totals.get(key, Decimal("0")) + value
        nonzero = {k: v for k, v in totals.items() if v != 0}
        lines.append(
            f"| {payer} | {len(docs)} | {_amount_text(nonzero, 0) or '—'} |"
        )
    return lines


def _document_rows(documents) -> list[str]:
    lines: list[str] = []
    by_type: dict[str, list] = {}
    for doc in documents:
        by_type.setdefault(doc.form_type, []).append(doc)

    for form_type in sorted(by_type):
        group = by_type[form_type]
        lines.append(f"#### {form_type} — {len(group)} document(s)")
        lines.append("")
        if len(group) > GROUP_DETAIL_LIMIT:
            lines += _aggregated_rows(group)
        else:
            lines += _detail_rows(group)
        lines.append("")
    return lines


def _account_section(result: ParsedTranscript) -> list[str]:
    acct = result.account
    if acct is None:
        return []
    lines = [f"### Account transcript — {result.file}", ""]
    meta = [f"form {acct.form_number}" if acct.form_number else "",
            f"tax year {acct.tax_year}" if acct.tax_year else "",
            f"filing status {acct.filing_status}" if acct.filing_status else ""]
    meta_text = ", ".join(m for m in meta if m)
    if meta_text:
        lines += [meta_text, ""]

    if acct.summary_fields:
        lines += ["| Account figure | Amount |", "|---|---|"]
        for key, value in acct.summary_fields.items():
            lines.append(f"| {pretty_field(key)} | {value:,.2f} |")
        lines.append("")

    credits = payments_and_credits(acct)
    if credits:
        lines += ["**Payments and credits posted to the account**", "",
                  "| Category | Amount |", "|---|---|"]
        for key, value in credits.items():
            lines.append(f"| {pretty_field(key)} | {value:,.2f} |")
        lines += ["", "_Estimated payments and prior-year credits appear ONLY "
                  "here, never on a Wage & Income transcript._", ""]

    if acct.transactions:
        lines += ["<details><summary>Full transaction ledger "
                  f"({len(acct.transactions)} rows)</summary>", "",
                  "| Code | Explanation | Date | Amount |", "|---|---|---|---|"]
        for txn in acct.transactions:
            known = PAYMENT_CODES.get(txn.code, "")
            explanation = txn.explanation
            if known and known.lower() != explanation.lower():
                explanation = f"{explanation} _({known})_"
            lines.append(
                f"| {txn.code} | {explanation} | {txn.date or ''} "
                f"| {_money(txn.amount)} |"
            )
        lines += ["", "</details>", ""]
    return lines


def _return_section(result: ParsedTranscript) -> list[str]:
    ret = result.tax_return
    if ret is None:
        return []
    lines = [f"### Return transcript — {result.file}", ""]
    meta = ", ".join(m for m in [
        f"form {ret.form_number}" if ret.form_number else "",
        f"tax year {ret.tax_year}" if ret.tax_year else "",
        f"filing status {ret.filing_status}" if ret.filing_status else "",
    ] if m)
    if meta:
        lines += [meta, ""]

    nonzero = {k: v for k, v in ret.line_items.items() if v != 0}
    if nonzero:
        lines += [f"| Posted line item | Amount |", "|---|---|"]
        for key, value in nonzero.items():
            lines.append(f"| {pretty_field(key)} | {value:,.2f} |")
        zeros = len(ret.line_items) - len(nonzero)
        lines += ["", f"_{zeros} further line item(s) posted as $0.00._", ""]
    return lines


def build_summary(results: list[ParsedTranscript]) -> str:
    out: list[str] = [
        "# IRS transcript digest",
        "",
        f"Generated {date.today().isoformat()} from "
        f"{len(results)} transcript file(s).",
        "",
        "Every amount below was read literally from a PDF text layer. Totals "
        "are plain sums of those amounts. Nothing here is estimated, inferred "
        "or rounded. Boxes reported as $0.00 are counted rather than listed, "
        "to keep this digest small.",
        "",
        "## Sources",
        "",
        "| File | Product | Pages | Tax year(s) |",
        "|---|---|---|---|",
    ]
    for r in results:
        years = ", ".join(r.tax_years) or "—"
        out.append(
            f"| `{Path(r.file).name}` | {describe(r.transcript_type)} "
            f"| {r.pages} | {years} |"
        )
    out.append("")

    warnings = [(Path(r.file).name, w) for r in results for w in r.warnings]
    if warnings:
        out += ["## ⚠ Extraction warnings", "",
                "These affect how much of the transcript was readable. Resolve "
                "them before relying on the totals.", ""]
        out += [f"- `{name}`: {w}" for name, w in warnings]
        out.append("")

    all_docs = [d for r in results for d in r.income_documents]

    if all_docs:
        # file name -> who the transcript belongs to
        owners = {
            Path(r.file).name: (r.taxpayer_name or Path(r.file).name)
            for r in results
        }
        variants = {
            Path(r.file).name: r.taxpayer_name_variants for r in results
        }

        years = sorted({d.tax_year for d in all_docs if d.tax_year})
        for year in years or [None]:
            docs = [d for d in all_docs if d.tax_year == year]
            out += [f"## Tax year {year or '(not stated)'} — "
                    f"{len(docs)} information return(s)", ""]

            wh = withholding_summary(docs)
            out += [
                "**Federal withholding reported to the IRS** "
                "(all filers combined)", "",
                "| Source | 1040 line | Amount |", "|---|---|---|",
                f"| Form(s) W-2 | 25a | {wh['from_w2_line_25a']:,.2f} |",
                f"| Form(s) 1099 | 25b | {wh['from_1099_line_25b']:,.2f} |",
                f"| Other forms | 25c | {wh['from_other_line_25c']:,.2f} |",
                f"| **Total** | | **{wh['total']:,.2f}** |", "",
            ]

            flags = flag_review_items(docs)
            if flags:
                out += ["**Review flags**", ""]
                out += [f"- {f}" for f in flags]
                out.append("")

            # Group by source transcript. On a joint return each spouse's
            # documents must stay attributable to that spouse: a W-2 belongs
            # to one of them, and Schedule C / SE income has to be assigned to
            # the right person or the SE tax computes against the wrong record.
            by_file: dict[str, list] = {}
            for d in docs:
                key = d.source.file if d.source else "(unknown source)"
                by_file.setdefault(key, []).append(d)

            for file_name in sorted(by_file):
                group = by_file[file_name]
                owner = owners.get(file_name, file_name)
                heading = (f"### {owner} — {len(group)} information return(s)"
                           if len(by_file) > 1
                           else f"### Documents — {len(group)}")
                out += [heading, ""]

                if len(by_file) > 1:
                    alts = variants.get(file_name) or []
                    if alts:
                        out += [
                            f"_Also appears on these forms as: "
                            f"{', '.join(alts)}. Confirm the name the IRS has "
                            f"on file matches the return._", "",
                        ]

                counts: dict[str, int] = {}
                for d in group:
                    counts[d.form_type] = counts.get(d.form_type, 0) + 1
                inventory = ", ".join(
                    f"{k} ×{v}" if v > 1 else k
                    for k, v in sorted(counts.items())
                )
                out += [f"**On file:** {inventory}", ""]

                if len(by_file) > 1:
                    gwh = withholding_summary(group)
                    if gwh["total"] != 0:
                        out += [
                            f"**Withholding on these forms:** "
                            f"{gwh['total']:,.2f} "
                            f"(W-2 {gwh['from_w2_line_25a']:,.2f}, "
                            f"1099 {gwh['from_1099_line_25b']:,.2f})", "",
                        ]

                out += _document_rows(group)

    for r in results:
        out += _account_section(r)
        out += _return_section(r)

    doc_warnings = [(d.label, w) for d in all_docs for w in d.warnings]
    if doc_warnings:
        out += ["## Per-document parse notes", ""]
        out += [f"- {label}: {w}" for label, w in doc_warnings]
        out.append("")

    out += [
        "---",
        "",
        "Form and line references follow the Form 1040 layout used for tax "
        "years 2023-2025 and are a review aid only. Confirm each one against "
        "the form for the year being prepared.",
        "",
    ]
    return "\n".join(out)


def write_summary(results: list[ParsedTranscript], path: Path) -> Path:
    path.write_text(build_summary(results))
    return path


# ---------------------------------------------------------------------------
# rollup.md
# ---------------------------------------------------------------------------
def build_rollup_markdown(rollups: dict[str, Rollup]) -> str:
    out = [
        "# Return line roll-up",
        "",
        "What the transcripts say each return line should account for. These "
        "are sums of reported amounts, not conclusions about taxability -- a "
        "return line legitimately differs whenever basis, exclusions, "
        "rollovers, allocations or limits apply.",
        "",
    ]
    for year, rollup in sorted(rollups.items()):
        out += [f"## Tax year {year}", ""]

        nonzero = [e for e in rollup.lines if e.total != 0]
        zeros = [e for e in rollup.lines if e.total == 0]

        if nonzero:
            out += ["| Return line | Transcript total | Sourced from | "
                    "What the line is |", "|---|---|---|---|"]
            for entry in nonzero:
                # Count DISTINCT DOCUMENTS per form type, not contributions.
                # One 1099-INT can feed line 2b twice (box 1 interest and box 3
                # savings bond interest); reporting that as "1099-INT x2" would
                # tell the preparer to go looking for a second 1099-INT that
                # does not exist.
                seen: dict[str, set[int]] = {}
                for c in entry.contributions:
                    seen.setdefault(c.document.form_type, set()).add(
                        id(c.document)
                    )
                counts = {name: len(ids) for name, ids in seen.items()}
                sources = ", ".join(
                    f"{name} ×{n}" for name, n in sorted(counts.items())
                )
                out.append(
                    f"| **{entry.target}** | {entry.total:,.2f} "
                    f"| {sources} | {entry.target.description} |"
                )
            out.append("")

            notes = {n for e in nonzero for n in e.notes}
            if notes:
                out += ["**Notes on these lines**", ""]
                out += [f"- {n}" for n in sorted(notes)]
                out.append("")

        if zeros:
            labels = ", ".join(str(e.target) for e in zeros)
            out += [f"_Reported as $0.00: {labels}_", ""]

        if rollup.unmapped:
            out += ["**Reported but not mapped to a line** — these carry no "
                    "roll-up target and need the preparer's judgment:", ""]
            for c in rollup.unmapped:
                if c.amount == 0:
                    continue
                out.append(
                    f"- {c.document.form_type} "
                    f"{pretty_field(c.field_name)}: {c.amount:,.2f} "
                    f"({c.document.payer_name or 'payer not stated'})"
                )
            out.append("")

        memo_nonzero = [c for c in rollup.memo if c.amount != 0]
        if memo_nonzero:
            out += ["<details><summary>Memo amounts (deliberately NOT "
                    "totalled into any line)</summary>", ""]
            out += ["Adding these to income would double count them — they are "
                    "components of, or notes about, an amount already counted "
                    "above.", ""]
            for c in memo_nonzero:
                out.append(
                    f"- {c.document.form_type} "
                    f"{pretty_field(c.field_name)}: {c.amount:,.2f} "
                    f"({c.document.payer_name or 'payer not stated'})"
                )
            out += ["", "</details>", ""]
    return "\n".join(out)


def write_rollup(rollups: dict[str, Rollup], path: Path) -> Path:
    path.write_text(build_rollup_markdown(rollups))
    return path


# ---------------------------------------------------------------------------
# crosscheck.csv
# ---------------------------------------------------------------------------
CROSSCHECK_HEADER = [
    "tax_year", "form_type", "payer_name", "payer_tin",
    "transcript_field", "transcript_amount",
    "target_form", "target_line", "what_the_line_is",
    "amount_on_my_return", "difference", "reviewed", "notes", "source",
]


def write_crosscheck(rollups: dict[str, Rollup], path: Path) -> Path:
    """One row per mapped amount, with blank columns for the preparer.

    ``difference`` carries a spreadsheet formula so the worksheet is live the
    moment the preparer types their own figure into ``amount_on_my_return``.
    """
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CROSSCHECK_HEADER)
        row_number = 1
        for year, rollup in sorted(rollups.items()):
            for entry in rollup.lines:
                for c in entry.contributions:
                    row_number += 1
                    doc = c.document
                    writer.writerow([
                        _safe_text(year),
                        _safe_text(doc.form_type),
                        _safe_text(doc.payer_name),
                        _safe_text(doc.payer_tin),
                        _safe_text(pretty_field(c.field_name)),
                        f"{c.amount:.2f}",
                        _safe_text(entry.target.form),
                        _safe_text(entry.target.line),
                        _safe_text(entry.target.description),
                        "",  # amount_on_my_return -- preparer fills this
                        f"=IF(J{row_number}=\"\",\"\",J{row_number}-F{row_number})",
                        "",  # reviewed
                        _safe_text(entry.target.note),
                        _safe_text(doc.source),
                    ])
    return path


def write_all(
    results: list[ParsedTranscript], out_dir: Path
) -> dict[str, Path]:
    """Write every artifact and return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    all_docs = [d for r in results for d in r.income_documents]
    years = sorted({d.tax_year for d in all_docs if d.tax_year})
    rollups = {y: build_rollup(all_docs, y) for y in years}
    if not rollups and all_docs:
        rollups = {"(year not stated)": build_rollup(all_docs, None)}

    written = {
        "json": write_json(results, out_dir / "transcripts.json"),
        "summary": write_summary(results, out_dir / "summary.md"),
        "rollup": write_rollup(rollups, out_dir / "rollup.md"),
        "crosscheck": write_crosscheck(rollups, out_dir / "crosscheck.csv"),
    }
    # An SSA-1099 carrying prior-year rows means the §86(e) election is on the
    # table. Pre-fill the worksheet so the preparer only has to add the
    # prior-year income figures, which no transcript can supply.
    template = write_lump_sum_template(results, out_dir / "lump_sum_input.csv")
    if template is not None:
        written["lump_sum_template"] = template
    return written


# ---------------------------------------------------------------------------
# Section 86(e) lump-sum election
# ---------------------------------------------------------------------------
LUMP_SUM_HEADER = [
    "year", "role", "amount", "your_magi_that_year", "filing_status",
    "ss_already_received_that_year", "tax_exempt_interest",
]

_LUMP_SUM_NOTES = [
    "# Section 86(e) lump-sum election worksheet -- FILL IN THE BLANKS",
    "#",
    "# The 'year_of_receipt' row is the year the lump sum was PAID.",
    "#   amount                = TOTAL benefits on that year's SSA-1099",
    "#   your_magi_that_year   = that year's AGI with the benefits left out,",
    "#                           before the standard/itemized deduction",
    "# Each 'prior_year' row is a year the arrears are attributable to.",
    "#   amount                = the TY <year> Payments figure on the SSA-1099",
    "#   your_magi_that_year   = THAT year's AGI (from that year's return)",
    "#   ss_already_received   = benefits actually paid in that year, if any",
    "#",
    "# filing_status: joint, single, hoh, qss, mfs_apart, mfs_together",
    "# Leave tax_exempt_interest at 0 unless there was any.",
    "# Lines starting with # are ignored.",
]


def write_lump_sum_template(
    results: list[ParsedTranscript], path: Path
) -> Path | None:
    """Pre-fill a lump-sum worksheet from the SSA-1099 rows already parsed.

    Returns None when no SSA-1099 with prior-year payments was found, which
    means the election does not arise on these transcripts.
    """
    import re

    rows: list[list[str]] = []
    receipt_year = ""
    total_benefits = ""

    for result in results:
        for doc in result.income_documents:
            if doc.form_type not in ("SSA-1099", "RRB-1099"):
                continue
            prior: list[tuple[str, str]] = []
            for label, value in doc.raw_fields.items():
                m = re.match(r"^TY\s+(\d{4})\s+Payments$", label.strip(), re.I)
                if m and (value or "").strip():
                    amount = parse_money(value)
                    if amount is not None and amount != 0:
                        prior.append((m.group(1), f"{amount:.2f}"))
            if not prior:
                continue
            benefits = doc.amounts.get("social_security_benefits")
            receipt_year = doc.tax_year or ""
            total_benefits = f"{benefits:.2f}" if benefits is not None else ""
            rows.append([
                receipt_year, "year_of_receipt", total_benefits, "", "joint", "", "0",
            ])
            for year, amount in sorted(prior, reverse=True):
                rows.append([year, "prior_year", amount, "", "joint", "0", "0"])

    if not rows:
        return None

    with path.open("w", newline="") as handle:
        for note in _LUMP_SUM_NOTES:
            handle.write(note + "\n")
        writer = csv.writer(handle)
        writer.writerow(LUMP_SUM_HEADER)
        writer.writerows(rows)
    return path


def _num(value: str, label: str, row: int) -> Decimal:
    text = (value or "").strip().replace(",", "").replace("$", "")
    if not text:
        raise ValueError(
            f"row {row}: '{label}' is blank. Every figure is needed -- if it "
            f"is genuinely zero, type 0."
        )
    try:
        return Decimal(text)
    except Exception:
        raise ValueError(
            f"row {row}: '{label}' is {value!r}, which is not a number"
        ) from None


def read_lump_sum_csv(path: Path):
    """Load a filled-in worksheet. Returns the arguments for compute_election."""
    from .lump_sum import AttributionYear, FilingStatus

    lines = [
        line for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    reader = csv.DictReader(lines)
    receipt: dict | None = None
    years: list[AttributionYear] = []

    for number, row in enumerate(reader, start=2):
        role = (row.get("role") or "").strip().lower()
        status = (row.get("filing_status") or "").strip().lower()
        if status not in FilingStatus.ALL:
            raise ValueError(
                f"row {number}: filing_status {status!r} is not one of "
                f"{', '.join(sorted(FilingStatus.ALL))}"
            )
        if role == "year_of_receipt":
            if receipt is not None:
                raise ValueError("more than one 'year_of_receipt' row")
            receipt = {
                "year": (row.get("year") or "").strip(),
                "total_benefits": _num(row.get("amount"), "amount", number),
                "other_income": _num(
                    row.get("your_magi_that_year"), "your_magi_that_year", number
                ),
                "filing_status": status,
                "tax_exempt_interest": _num(
                    row.get("tax_exempt_interest") or "0",
                    "tax_exempt_interest", number,
                ),
            }
        elif role == "prior_year":
            magi_raw = (row.get("your_magi_that_year") or "").strip()
            years.append(AttributionYear(
                year=(row.get("year") or "").strip(),
                arrears=_num(row.get("amount"), "amount", number),
                # Blank means "not known yet", which is different from zero.
                known=bool(magi_raw),
                other_income=(
                    _num(magi_raw, "your_magi_that_year", number)
                    if magi_raw else Decimal("0")
                ),
                filing_status=status,
                benefits_already_received=_num(
                    row.get("ss_already_received_that_year") or "0",
                    "ss_already_received_that_year", number,
                ),
                tax_exempt_interest=_num(
                    row.get("tax_exempt_interest") or "0",
                    "tax_exempt_interest", number,
                ),
            ))
        else:
            raise ValueError(
                f"row {number}: role {role!r} must be 'year_of_receipt' or "
                f"'prior_year'"
            )

    if receipt is None:
        raise ValueError("no 'year_of_receipt' row found")
    if not years:
        raise ValueError("no 'prior_year' rows found -- nothing to elect over")
    return receipt, years


def build_lump_sum_markdown(result, receipt_year: str = "") -> str:
    def money(value: Decimal) -> str:
        return f"{value:,.2f}"

    out = [
        f"# Section 86(e) lump-sum election — benefits received {receipt_year}",
        "",
        "A retroactive award pays several years of benefits at once. Taxed all "
        "in the year of receipt, it usually lands in the 85% inclusion tier. "
        "The election caps the inclusion at what those arrears would have "
        "added to income in the years they were *for*.",
        "",
        "**It is a ceiling, not an amendment.** The earlier years are not "
        "reopened, not recomputed and not amended. The whole payment still "
        "reports in the year of receipt.",
        "",
        "## The benefits",
        "",
        "| | Amount |",
        "|---|---|",
        f"| Total on the SSA-1099 | **{money(result.total_benefits)}** |",
        f"| Attributable to earlier years | {money(result.arrears_total)} |",
        f"| Attributable to {receipt_year or 'the year of receipt'} | "
        f"{money(result.current_year_portion)} |",
        "",
        "## Without the election — everything taxed in the year of receipt",
        "",
        "| | Amount |",
        "|---|---|",
    ]
    w = result.without_election
    out += [
        f"| Modified AGI | {money(w.modified_agi)} |",
        f"| + one-half of benefits | {money(w.benefits * Decimal('0.5'))} |",
        f"| **Provisional income** | **{money(w.provisional_income)}** |",
        f"| Base amount / adjusted base amount | {money(w.base_amount)} / "
        f"{money(w.adjusted_base_amount)} |",
        f"| Tier reached | **{w.tier}** |",
        f"| **Taxable benefits** | **{money(w.taxable)}** ({w.included_pct}% "
        f"of benefits) |",
        "",
        "## With the election",
        "",
        "### Step 1 — the portion attributable to the year of receipt",
        "",
        "Taxed normally, on that year's income.",
        "",
        "| | Amount |",
        "|---|---|",
    ]
    c = result.current_portion_only
    out += [
        f"| Benefits attributable to the year of receipt | "
        f"{money(c.benefits)} |",
        f"| Provisional income | {money(c.provisional_income)} |",
        f"| Tier reached | {c.tier} |",
        f"| **Taxable** | **{money(c.taxable)}** |",
        "",
        "### Step 2 — the increase each earlier year would have seen",
        "",
        "Each year is recomputed as if its share of the arrears had been paid "
        "then. The **increase** is what §86(e) measures.",
        "",
        "| Year | Arrears | That year's MAGI | Provisional w/ arrears | Tier "
        "| Taxable before | Taxable after | **Increase** |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for y in sorted(result.years, key=lambda z: z.year):
        if not y.known:
            out.append(
                f"| {y.year} | {money(y.arrears)} | _not supplied_ | — | — "
                f"| — | — | **not yet computable** |"
            )
            continue
        out.append(
            f"| {y.year} | {money(y.arrears)} | {money(y.other_income)} "
            f"| {money(y.after.provisional_income)} | {y.after.tier} "
            f"| {money(y.before.taxable)} | {money(y.after.taxable)} "
            f"| **{money(y.increase)}** |"
        )
    label = ("Ceiling so far (INCOMPLETE)" if not result.complete
             else "Ceiling (§86(e)(1))")
    out += [
        f"| | | | | | | **{label}** | **{money(result.ceiling)}** |",
        "",
        "## Result",
        "",
    ]
    if not result.complete:
        missing = ", ".join(sorted(result.unknown_years))
        out += [
            f"**No bottom line yet — {missing} still missing.**",
            "",
            "Each missing year can only add to the ceiling, so reporting a "
            "total now would make the election look better than it is. The "
            "per-year rows above are correct for the years that are filled "
            "in; supply the rest and re-run.",
            "",
            f"For reference, without any election the whole "
            f"{money(result.total_benefits)} produces "
            f"**{money(result.without_election.taxable)}** of taxable "
            f"benefits.",
            "",
        ]
    else:
        out += [
            "| | Taxable benefits |",
            "|---|---|",
            f"| Without the election | "
            f"{money(result.without_election.taxable)} |",
            f"| With the election (step 1 + step 2) | "
            f"**{money(result.with_election)}** |",
            f"| **Reduction in taxable income** | "
            f"**{money(result.savings)}** |",
            "",
        ]
    if result.election_helps:
        out += [
            f"**Make the election.** It removes {money(result.savings)} from "
            f"taxable income. That is a reduction in TAXABLE INCOME, not in "
            f"tax — the cash saving is that figure times the marginal rate.",
            "",
        ]
    else:
        out += [
            "**Do not make the election.** On these figures it does not help. "
            "It is elective, so simply leave it off.",
            "",
        ]
    if result.warnings:
        out += ["## Warnings", ""]
        out += [f"- {w}" for w in result.warnings]
        out.append("")
    out += [
        "---",
        "",
        "Every figure above comes from the SSA-1099 as parsed, plus the "
        "prior-year figures entered in the worksheet CSV. Confirm each "
        "prior-year MAGI against that year's filed return before relying on "
        "this. The thresholds are §86(c)(1) and §86(c)(2); the inclusion "
        "formula is §86(a)(1) and §86(a)(2); attribution follows "
        "§86(e)(2)(A). This is a computation, not tax advice.",
        "",
    ]
    return "\n".join(out)


def write_lump_sum_worksheet(result, path: Path, receipt_year: str = "") -> Path:
    path.write_text(build_lump_sum_markdown(result, receipt_year))
    return path
