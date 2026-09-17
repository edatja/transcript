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

    return {
        "json": write_json(results, out_dir / "transcripts.json"),
        "summary": write_summary(results, out_dir / "summary.md"),
        "rollup": write_rollup(rollups, out_dir / "rollup.md"),
        "crosscheck": write_crosscheck(rollups, out_dir / "crosscheck.csv"),
    }
