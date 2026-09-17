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
        "--quiet", action="store_true", help="only print errors",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.dump_text:
        from .extract import extract_text_only
        print(extract_text_only(args.dump_text, args.page))
        return 0

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
