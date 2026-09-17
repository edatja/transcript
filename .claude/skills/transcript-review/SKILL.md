---
name: transcript-review
description: Review IRS transcripts against a tax return being prepared. Use when the user asks to check, tie out, cross-reference, reconcile or review transcripts against a draft return, mentions a Wage & Income / Account / Return transcript, asks "did I miss any income?", or drops transcript PDFs into data/input/. Also use when they ask what income the IRS has on file for a taxpayer.
---

# Reviewing IRS transcripts against a return

## The rule that matters most

**Never read a transcript PDF into context.** Run the extractor and read its
artifacts. A transcript PDF is tens of thousands of tokens of dot leaders and
repeated page headers; the digest it produces is a fraction of that and is
easier to reason over. More importantly, the extractor is exact where reading
is not — it reads the characters the IRS embedded in the file.

If a PDF fails to parse, fix the parser. Do not work around it by reading the
PDF.

## Step 1 — extract

```bash
python3 run.py
```

Reads every PDF in `data/input/`, writes to `data/output/`:

| Artifact | Read it when |
|---|---|
| `summary.md` | Always. Start here. Every document, grouped, with warnings. |
| `rollup.md` | Always. Transcript totals grouped by the return line they feed. |
| `crosscheck.csv` | The user wants a worksheet, or you need per-document rows. |
| `transcripts.json` | Only when you need a specific raw field. It is large. |

**Read the warnings first.** A transcript that partly failed to extract will
produce totals that look complete and are not. Warnings appear at the top of
`summary.md`. Resolve them before reasoning about any number.

## Step 2 — establish what you are comparing

Ask for the draft return's figures if they are not already provided. You need,
at minimum: filing status, the 1040 income lines (1a, 2a/2b, 3a/3b, 4a/4b,
5a/5b, 6a/6b, 7, 8), total payments (25a/25b/25c, 26), and which schedules are
attached.

Do not proceed on a guess about what the return says. "The return probably
shows X" is not a comparison.

## Step 3 — the four checks

**1. Completeness — is every transcript document on the return?**
Go form by form through `summary.md`. For each one, find where it appears on
the return. A W-2 with no matching wages, a 1099-NEC with no Schedule C, a
1099-R with no line 4/5 entry: each is a missing item until explained.

This is the check that catches the expensive errors. The IRS matches these
documents automatically and issues a CP2000 when one is unaccounted for.

**2. Amounts — does each line tie?**
Compare `rollup.md` totals to the return. Differences are common and often
correct. What matters is that each one has a *reason*:

| Difference | Usually legitimate because |
|---|---|
| Line 1a below W-2 total | rarely — W-2 box 1 totals should tie exactly |
| Line 2b below 1099-INT total | some interest is tax-exempt (goes to 2a) |
| Line 4b/5b below gross distribution | rollover, basis, or QCD |
| Line 7 unrelated to 1099-B proceeds | proceeds are not gain; basis applies |
| Schedule C gross above 1099 totals | cash and unreported-to-IRS receipts |
| Schedule C gross below 1099 totals | investigate — this direction is a risk |
| Line 6b below SSA benefits | only 0–85% of benefits are taxable |

**3. Payments — is every credit claimed?**
Withholding is in `summary.md`, split by 1040 line. Estimated payments,
extension payments and prior-year credits are **only** on an Account
Transcript — if the user has not provided one, say so explicitly. A missed
estimated payment is money left on the table.

**4. Review flags**
`summary.md` has a "Review flags" section. Work each one. They cover the
patterns that most often produce an adjusted return — a 1095-A without Form
8962, a corrected form, 1099-K and 1099-NEC double counting.

## Step 4 — report

Lead with what needs action. Structure:

1. **Unaccounted for** — transcript documents with no home on the return.
2. **Differences needing a reason** — amounts that do not tie, with the
   likely explanation and what would confirm it.
3. **Credits to verify** — withholding and payments.
4. **Confirmed** — what ties. Brief; a list of line numbers is enough.
5. **Not checkable from what you have** — be explicit about this.

Cite figures as `line 1a: transcript 100,750 vs return 98,400`. Name the payer
when pointing at a specific document.

## Hard limits on what you may say

- **Never state a figure that is not in an artifact.** No estimating, no
  "approximately", no filling a gap with a plausible number.
- **A difference is a question, not a finding.** You can see what was reported
  to the IRS. You cannot see basis, rollovers, exclusions, allocations between
  spouses, or the taxpayer's own records. Say "this needs a reason", not "this
  is wrong".
- **The line mappings are a review aid.** They follow the Form 1040 layout for
  tax years 2023–2025 and can be wrong for an unusual fact pattern. The
  preparer decides.
- **Absence of a transcript document is not absence of income.** Wage & Income
  transcripts are incomplete until roughly mid-year for the prior tax year,
  and some income is never reported on an information return at all. Never
  conclude "all income is accounted for" — say what the transcripts covered
  and when they were pulled (the request date is in `summary.md`).
- **You are not the preparer.** Surface, quantify, and explain. Do not decide.

## If the transcripts are missing something

- No Account Transcript → estimated payments and prior-year credits are
  invisible. Say so; do not assume there were none.
- Only one tax year → carryovers, prior-year state refunds and installment
  items cannot be checked.
- `summary.md` shows a "NO TEXT LAYER" warning → the PDF is a scan. Ask for
  the original from IRS.gov Get Transcript. Do not try to read the image.
