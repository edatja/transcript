"""Command line interface.

The common case is one word::

    python3 run.py

which parses every PDF in ``data/input/`` and writes the artifacts to
``data/output/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_INPUT = Path("data/input")
DEFAULT_OUTPUT = Path("data/output")


def _collect(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.pdf")))
            paths.extend(sorted(path.glob("*.PDF")))
        elif path.is_file():
            paths.append(path)
        else:
            print(f"warning: {item} does not exist, skipping", file=sys.stderr)
    # A case-insensitive filesystem can yield the same file twice.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="irs-transcript",
        description=(
            "Extract IRS transcripts to structured artifacts, locally. "
            "No network, no API calls, no tokens."
        ),
        epilog=(
            "Typical use:  python3 run.py           "
            "(reads data/input/, writes data/output/)"
        ),
    )
    parser.add_argument(
        "inputs", nargs="*", default=[str(DEFAULT_INPUT)],
        help="PDF files or directories (default: data/input)",
    )
    parser.add_argument(
        "-o", "--output", default=str(DEFAULT_OUTPUT), type=Path,
        help="output directory (default: data/output)",
    )
    parser.add_argument(
        "--classify", action="store_true",
        help="just report what each PDF is, parse nothing",
    )
    parser.add_argument(
        "--dump-text", metavar="PDF",
        help="print a PDF's extracted text (for debugging parsers)",
    )
    parser.add_argument(
        "--page", type=int, default=None,
        help="with --dump-text, limit to one page number",
    )
    parser.add_argument(
        "--lump-sum", metavar="CSV",
        help="compute the section 86(e) social security lump-sum election "
             "from a filled-in lump_sum_input.csv",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="only print errors",
    )
    return parser


def _run_lump_sum(csv_path: Path, out_dir: Path, quiet: bool) -> int:
    """Compute the section 86(e) election from a filled-in worksheet CSV."""
    from .lump_sum import compute_election
    from .report import read_lump_sum_csv, write_lump_sum_worksheet

    if not csv_path.exists():
        print(
            f"{csv_path} not found.\n\n"
            f"Run `python3 run.py` first -- if the transcripts contain an "
            f"SSA-1099 with prior-year payments, it writes a pre-filled "
            f"template to data/output/lump_sum_input.csv. Fill in each year's "
            f"income figures, then run this again.",
            file=sys.stderr,
        )
        return 1

    try:
        receipt, years = read_lump_sum_csv(csv_path)
    except ValueError as exc:
        print(f"Could not read {csv_path.name}: {exc}", file=sys.stderr)
        return 1

    result = compute_election(
        total_benefits=receipt["total_benefits"],
        current_year_other_income=receipt["other_income"],
        current_year_filing_status=receipt["filing_status"],
        years=years,
        current_year_tax_exempt_interest=receipt["tax_exempt_interest"],
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = write_lump_sum_worksheet(
        result, out_dir / "lump_sum_worksheet.md", receipt["year"]
    )

    if not quiet:
        print()
        print(f"  Without the election: "
              f"{result.without_election.taxable:>12,.2f} taxable benefits")
        if result.complete:
            print(f"  With the election:    "
                  f"{result.with_election:>12,.2f} taxable benefits")
            print(f"  {'Reduction:':<21} {result.savings:>12,.2f}")
        else:
            missing = ", ".join(sorted(result.unknown_years))
            print(f"  With the election:    (not computable -- {missing} "
                  f"missing)")
        print()
        for warning in result.warnings:
            print(f"  ! {warning}")
        if result.warnings:
            print()
        print(f"Wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.dump_text:
        from .extract import extract_text_only
        print(extract_text_only(args.dump_text, args.page))
        return 0

    if args.lump_sum:
        return _run_lump_sum(Path(args.lump_sum), Path(args.output), args.quiet)

    paths = _collect(args.inputs)
    if not paths:
        where = ", ".join(args.inputs)
        print(
            f"No PDFs found in {where}.\n\n"
            f"Put your IRS transcript PDFs in {DEFAULT_INPUT}/ and run again.\n"
            f"Download them from IRS.gov -> Get Transcript -> Get Transcript "
            f"Online, or from your e-Services TDS account.",
            file=sys.stderr,
        )
        return 1

    from .classify import describe
    from .pipeline import process_file, process_paths
    from .report import write_all

    if args.classify:
        for path in paths:
            try:
                result = process_file(path)
                years = ", ".join(result.tax_years) or "year not stated"
                print(f"{path.name}: {describe(result.transcript_type)} "
                      f"[{years}, {result.pages} pages]")
            except Exception as exc:
                print(f"{path.name}: FAILED -- {exc}", file=sys.stderr)
        return 0

    if not args.quiet:
        print(f"Reading {len(paths)} PDF(s)...")

    results = process_paths(paths)
    written = write_all(results, args.output)

    failures = [r for r in results if r.transcript_type == "unreadable"]
    warned = [(r.file, w) for r in results for w in r.warnings]

    if not args.quiet:
        total_docs = sum(len(r.income_documents) for r in results)
        print()
        for result in results:
            bits = [describe(result.transcript_type)]
            if result.income_documents:
                bits.append(f"{len(result.income_documents)} information returns")
            if result.account:
                bits.append(f"{len(result.account.transactions)} transactions")
            if result.tax_return:
                bits.append(f"{len(result.tax_return.line_items)} posted lines")
            print(f"  {result.file}: {' | '.join(bits)}")
        print()
        if warned:
            print(f"{len(warned)} warning(s):")
            for name, warning in warned:
                print(f"  ! {name}: {warning}")
            print()
        print(f"Wrote {len(written)} artifact(s) to {args.output}/:")
        for name, path in written.items():
            print(f"  {path}")
        print()
        print("Next: hand data/output/summary.md and rollup.md to Claude, or "
              "open crosscheck.csv in a spreadsheet to tie out line by line.")
        if total_docs == 0 and not failures:
            print()
            print("NOTE: zero information returns parsed. If the transcripts "
                  "should contain some, run with --dump-text to see what the "
                  "extractor actually read.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
