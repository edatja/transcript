# IRS transcript layouts

Notes for parser work. Everything here describes how the IRS *prints* these
documents, which is what the parsers have to cope with.

## The five products

| Product | Contains | Parser |
|---|---|---|
| Wage & Income | Every information return filed under the TIN | `parsers/wage_income.py` |
| Return | Line items of a return as the IRS posted it | `parsers/return_transcript.py` |
| Account | Assessment / payment / credit ledger | `parsers/account.py` |
| Record of Account | Return + Account in one document | both, over the whole text |
| Tax Compliance Report | Filing status by year, little dollar detail | not parsed |

Detection is by header text (`classify.py`). **Record of Account must be
tested first** — it contains the literal strings "Return Transcript" and
"Account Transcript" inside it, so testing in any other order mislabels it.

## The dot-leader line

Nearly every fact is printed as a label, a colon, cosmetic dot leaders, and a
value right-aligned to the margin:

```
Wages, Tips and Other Compensation:..................$50,000.00
Federal Income Tax Withheld:.........................$5,000.00
Distribution Code(s):................................7
```

Three shapes have to be handled, and all three occur:

1. **Dots present** — the normal case.
2. **No dots** — the label is long enough to fill the line:
   `Interest on US Savings Bonds and Treasury Obligations:$0.00`
3. **Dots, no value** — the box exists and is blank:
   `Total Distribution:................................`

Shape 3 is the dangerous one. The leader run ends flush against the newline,
so any leader-collapsing pattern that treats `\s` as a separator will eat the
newline and weld the next line onto this one — silently deleting every field
on it. `extract.py` uses `[ \t]` deliberately, and
`test_leader_run_does_not_swallow_the_following_line` guards it.

## Money

Always printed with a dollar sign, cents, or both:
`$50,000.00`, `-$600.00`, `0.00`. Credits on Account Transcripts print with a
leading minus, and the transcript says so in its own header:

```
--- ANY MINUS SIGN SHOWN BELOW SIGNIFIES A CREDIT AMOUNT ---
```

Signs are preserved exactly as printed; nothing is flipped during parsing.
`payments_and_credits()` flips them only when presenting a positive
"amount paid" figure.

A bare integer is **never** money — it is a distribution code, an exemption
count, a posting cycle, an indicator. `parse_money` requires a `$` or exactly
two decimal places for this reason.

## Wage & Income block structure

```
Form W-2 Wage and Tax Statement          <- block header, no colon
Employer:                                <- party section, colon, no value
Employer Identification Number (EIN):XX-XXX1234
NORTHWIND TRADING LLC                    <- name: first non-label line
400 HARBOR ST                            <- address lines follow
SEATTLE, WA 98101
Employee:                                <- second party section
Employee's Social Security Number:XXX-XX-4321
PAT SAMPLE
Submission Type:....Original document    <- first data field ends the party
Wages, Tips and Other Compensation:....$88,450.00
```

Blocks are delimited only by the next block header. A header is a line that
starts with `Form ` (or `Schedule K-1`) and **contains no colon** — the colon
test is what stops a data line mentioning a form name from starting a
spurious block.

Party section names vary by form: Employer/Employee, Payer/Recipient,
Lender/Borrower, Trustee/Participant, Filer/Transferor, Marketplace/Covered
Individual. Both sets are listed in `wage_income.py`.

The TIN can appear before or after the name. Both orders occur; the parser
takes the first non-label line in the section as the name regardless.

### Page breaks land inside blocks

The IRS reprints its request header at every page break, which frequently
falls in the middle of a form block:

```
Payer:
This Product Contains Sensitive Taxpayer Data
Tracking Number: 100200300400
Page 4 of 30
Payer's Federal Identification Number (FIN):XX-XXX4444
FIRST HARBOR BANK
```

`Tracking Number: ...` looks exactly like a data field. Unless it is filtered
as page furniture it ends the payer section and the payer's **name is lost**.
`fields.is_noise` filters these;
`test_page_header_inside_a_block_does_not_lose_the_payer` guards it.

### Form code prefixes collide

`1098-E` starts with `1098`. `W-2G` starts with `W-2`. `5498-SA` starts with
`5498`. The regex alternation in `_FORM_HEADER` lists longer codes first —
reordering it silently mislabels forms.

### Labels do not carry box numbers

The IRS spells box names out in prose, and the prose varies between form types
and tax years. `aliases.py` maps them to stable keys. Notable traps:

- **SSA-1099 prints its benefit as `Pensions and Annuities`.** It is social
  security (1040 line 6a), not pension income (line 5a). The taxable
  calculation is completely different. This is why `aliases.py` supports
  form-scoped overrides.
- **1099-MISC box 7 became 1099-NEC in 2020.** Older transcripts carry
  `Non-Employee Compensation` on a 1099-MISC.
- **1099-DIV** prints `Ordinary Dividend` (singular) on some years and
  `Total Ordinary Dividends` on others.

## Return Transcript: PER COMPUTER

Most lines appear twice:

```
ADJUSTED GROSS INCOME:....................$114,450.00
ADJUSTED GROSS INCOME PER COMPUTER:.......$116,650.00
```

The plain line is what the taxpayer reported. `PER COMPUTER` is the IRS's own
recomputation. **When they differ, the IRS changed the return** — which is
usually the most important fact on the document. The parser keeps both and
emits a warning; it never averages or picks one silently.

Some lines appear *only* as PER COMPUTER. Those are kept under the base key.

Labels can contain their own colon: `TAXABLE INTEREST INCOME: SCH B:....$980.00`.
The dot-leader split handles this because it splits at the first colon
followed by dots, not at the first colon.

## Account Transcript: the transaction ledger

```
CODE  EXPLANATION OF TRANSACTION      CYCLE     DATE        AMOUNT
150   Tax return filed                20251805  05-05-2025  $24,118.00
806   W-2 or 1099 withholding                   04-15-2025  -$13,340.00
660   Estimated tax payment                     06-15-2024  -$4,000.00
```

Cycle is often blank. The explanation is free text and its width varies, so
the row regex makes cycle, date and amount optional and matches the
explanation non-greedily.

Codes that matter for return preparation are in `PAYMENT_CODES`. The ones a
preparer must not miss:

| Code | Meaning |
|---|---|
| 806 | W-2 / 1099 withholding credit |
| 660 | Estimated tax payment |
| 670 | Subsequent payment |
| 610 | Remittance with return |
| 706 / 710 | Prior-year credit applied |
| 716 | Credit applied to next year |
| 846 | Refund issued |

**Estimated payments exist only here.** A preparer working from a Wage &
Income transcript alone will miss every one of them.

Some summary lines carry two pairs:

```
ACCRUED INTEREST: 0.00 AS OF: Mar. 17, 2025
```

`_strip_as_of` splits the trailing date off before the label/value split.

## Masking

Transcripts mask identifiers: `XXX-XX-1234`, `XX-XXX1234`. The last four
digits are real, which is enough to match a payer between documents but not
enough to reconstruct a TIN. Parsers keep the masked string verbatim.


---

# Layout variants found in real transcripts

Everything above was written from the classic dot-leader layout. Transcripts
saved from the current IRS *Get Transcript* web viewer differ in ways that each
dropped data silently until fixed. All are covered by
`tests/test_modern_layout.py`.

## Viewer chrome is baked into the PDF

A transcript saved from the browser carries the viewer's own "Done" and
"Print" buttons, drawn at the same vertical position as a transcript line.
pdfplumber interleaves the glyphs into that line:

```
RecDiopnieent'Psr inItdentification Number
FATDCoAn eFiliPnrgin tRequirement
EmpDloonyeee'sP rSinotcial Security Number
```

A corrupted label matches no pattern, so the field vanishes without a warning.
`extract._chrome_fonts` identifies the overlay **by font** — the transcript
body is monospace and its headings serif, while the buttons use the browser UI
font — and drops a font only when everything drawn in it on that page is
chrome words. A payer genuinely named "PRINT AND DESIGN DONE RIGHT LLC" is
therefore safe.

## Plain spacing instead of dot leaders

Current transcripts print `Label: value` with a single space and no leaders.
The `_PLAIN_COLON` fallback in `fields.py` handles this; both shapes occur in
the wild and both must keep working.

## Combined party headers, with inverted roles

```
Issuer/Provider:          <- 1099-NEC payer
Recipient/Lender:         <- 1098 PAYER (the bank receives the interest)
Payer/Borrower:           <- 1098 RECIPIENT (the taxpayer pays it)
```

A 1098 inverts the generic role words. Matching on "Payer" first files the
**taxpayer's own SSN as the lender's EIN**. `_is_party_header` therefore
resolves the specific role (`lender`, `borrower`) before the generic one
(`payer`, `recipient`, `payee`, `filer`).

## "Federal ID Number", not "Identification Number"

1099-NEC blocks print `Issuer's/Provider's Federal ID Number`. When that was
not recognised as a TIN label it was treated as ordinary data, which closed
the party section — so the payer's **name on the next line was never read**,
and the form showed as "(payer not stated)".

## Withholding labelled "Tax Withheld"

1099-R blocks label withholding simply `Tax Withheld`. Missing this reported
**$0 of 1099 withholding** on a transcript that had five figures of it — a
credit the taxpayer would have lost off line 25b.

## Distribution codes, spelled out

```
Distribution Code Value: Early Distribution, no known exception (in most cases, under age 59)
Distribution Code: 1
Distribution Code Value: Not significant
Distribution Code:
Tax Amount Undetermined Code: Tax amount not determined
Total Distribution Code: Not checked
SEP Indicator: IRA/SEP/SIMP box checked
```

Both code positions are always printed; the unused one reads "Not significant"
and must be discarded. The IRA/SEP/SIMPLE box arrives as prose
("box checked" / "box not checked") rather than 1/0 — and it is what decides
1040 line 4 versus line 5.

## SSA-1099 arrears rows

```
Pensions and Annuities (Total Benefits Paid): $177,414.00
TY 2022 Payments: $41,000.00
TY 2023 Payments: $43,000.00
TY 2024 Payments: $45,000.00
Trust Fund Indicator: Disability
```

The `TY <year> Payments` rows **break down** the total — they are not
additional benefits, and summing them would double the income. They signal a
lump-sum award, which opens the section 86(e) election. The label carries a
year, so it is matched by pattern in `flag_review_items` rather than aliased.

## Forms that legitimately carry no dollars

A 5498 can report only codes and an RMD date. That is not a parse failure, and
the per-document note says so rather than implying an unsupported layout.
