# CLAUDE.md

Project instructions for Claude Code working in this repository.

## What this project is

A two-stage pipeline for reviewing IRS transcripts against a tax return being prepared.

```
IRS transcript PDFs                (data/input/)
        |
   STAGE 1 -- LOCAL, DETERMINISTIC, ZERO TOKENS
   pdfplumber extraction + regex parsers      (src/irs_transcript/)
        |
   Structured artifacts             (data/output/)
     - transcripts.json    full structured data, every field, page-traceable
     - summary.md          compact human/LLM-readable digest
     - crosscheck.csv      one row per income document, for tie-out
     - rollup.md           totals mapped to Form 1040 / schedule lines
        |
   STAGE 2 -- CLAUDE REASONING
   Claude reads ONLY the small artifacts, never the PDFs
   (.claude/skills/transcript-review/SKILL.md)
```

**The whole point of Stage 1 is that PDFs never enter the context window.**

Measured on synthetic transcripts of realistic shape:

| Transcript | Raw PDF text | summary.md + rollup.md |
|---|---|---|
| 72 forms, 30 pages (brokerage year) | ~13,800 tokens | ~1,800 tokens (13%) |
| 11 forms, 3 pages | ~1,300 tokens | ~2,000 tokens (149%) |

The digest is *larger* than raw text for a small transcript, because it adds
line mappings, totals and review flags that the raw text does not contain.
The saving scales with transcript size, and the reason to use it is not only
size: the extractor reads the exact characters the IRS embedded, which a model
reading dot-leader columns may not. Above `GROUP_DETAIL_LIMIT` documents of one
form type, `summary.md` aggregates by payer instead of listing each one --
that is what keeps a 60-block 1099-B year small.

## Hard rules

1. **Never read a transcript PDF into context.** Do not `Read` a file in
   `data/input/`, do not pipe `pdftotext` output into your context, do not
   paste transcript text into a message. Run the parser and read the
   artifacts in `data/output/` instead. If the parser fails on a PDF, fix
   the parser — do not work around it by reading the PDF.
2. **Never invent, infer, or "reasonably estimate" a dollar amount.** Every
   number in an artifact must trace to a literal string in the PDF. If a
   field is absent, emit `null` — not `0`, not a guess.
3. **Never commit taxpayer data.** `data/input/` and `data/output/` are
   gitignored. Test fixtures are synthetic only (see `tests/fixtures/`).
   If you need a new fixture, write a fake one; never copy a real transcript.
4. **Parsers are additive.** When a PDF has a field we don't recognize, it
   still lands in `raw_fields` verbatim. Unknown is preserved, never dropped.
5. **Mappings are review aids, not tax advice.** `mapping.py` suggests which
   Form 1040 line a transcript amount usually feeds. The preparer decides.
   Say so in any output that presents a mapping.

## Commands

```bash
# Setup (once)
python3 -m pip install -r requirements.txt

# Parse everything in data/input/ -> data/output/
python3 run.py

# Parse specific files / a different output dir
python3 run.py data/input/wage_income_2024.pdf -o data/output

# Just check what a PDF is without full parsing
python3 run.py --classify data/input/*.pdf

# See the raw extracted text of one page (debugging parsers only)
python3 run.py --dump-text data/input/foo.pdf --page 3

# Tests (synthetic fixtures, no real data)
python3 -m pytest -q
```

## Layout

| Path | Purpose |
|---|---|
| `run.py` | Thin entry point. `python3 run.py` is the one command a user needs. |
| `src/irs_transcript/extract.py` | pdfplumber -> page text. The only file that touches a PDF. |
| `src/irs_transcript/classify.py` | Detects transcript type (Wage & Income / Account / Return / Record of Account). |
| `src/irs_transcript/fields.py` | The dot-leader `Label:....$Value` line parser shared by all parsers. |
| `src/irs_transcript/aliases.py` | Printed label -> normalized field key. `FIELD_ALIASES` lives here. |
| `src/irs_transcript/parsers/` | One module per transcript type. |
| `src/irs_transcript/pipeline.py` | extract -> classify -> parse. Takes text, so it is testable. |
| `src/irs_transcript/mapping.py` | Normalized field -> Form 1040 / schedule line table. |
| `src/irs_transcript/rollup.py` | Aggregates documents into per-line totals. |
| `src/irs_transcript/report.py` | Writes the four output artifacts. |
| `src/irs_transcript/models.py` | Dataclasses. Amounts are `Decimal` or `None`, never `float`. |
| `tests/fixtures/` | Synthetic transcript text. Safe to commit. |
| `tests/make_fixture_pdf.py` | Builds a real PDF from fixture text, no dependency. Keeps the pdfplumber path tested without committing a PDF. |
| `.claude/skills/transcript-review/` | The Stage 2 reasoning procedure. |
| `docs/transcript-formats.md` | Notes on real IRS transcript layouts, for parser work. |

## Code conventions

- Money is `decimal.Decimal`. Never `float` — `0.1 + 0.2` problems are not
  acceptable in a tax tool.
- A missing value is `None`. A real zero is `Decimal("0")`. Keep them distinct.
- Every parsed document carries `source_file` and `source_page` so any number
  can be traced back to a page for eyeballing.
- Parsers take **text**, not paths. That keeps them testable with fixtures.
- No network calls. Ever. This tool runs offline on taxpayer data.

## When adding support for a new form type

1. Add a synthetic sample block to `tests/fixtures/`.
2. Add the form code to `_FORM_HEADER` in `parsers/wage_income.py` --
   **longer codes before their prefixes** (`1098-E` before `1098`).
3. Add its printed labels to `_BY_FORM` in `aliases.py`.
4. Add the normalized field -> 1040 line row to `mapping.py`.
5. Add a test asserting the amounts parse and the rollup lands on the right line.

## Before trusting a parse of a real transcript

Real transcripts vary more than the classic layout suggests. After parsing a
new one, check `summary.md` for:

- a payer shown as `_(not stated)_` -- a party-section or TIN-label variant
- `no dollar amounts on this form` -- either a codes-only form (fine) or a
  label variant (not fine)
- withholding totalling 0.00 when a 1099-R or W-2 is present
- garbled labels, which mean viewer chrome slipped past the font filter

`docs/transcript-formats.md` has the variants found so far and what each one
broke. Every one of them lost data silently rather than failing loudly, which
is why the per-document parse notes exist.
