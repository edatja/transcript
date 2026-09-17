# IRS transcript → return tie-out

Pull the numbers out of IRS transcript PDFs on your own machine, then hand
Claude a small, clean digest to compare against the return you're preparing.

The PDF never goes to Claude. Only the digest does.

---

## Why it's split in two

Reading a PDF with an AI model is slow, expensive, and — worst of all — it can
misread a number. A model looking at `$1,240.00` in a wall of dots can get it
wrong, and a wrong number in a tax file is a real problem.

So the work is split:

**Stage 1 — your computer does the reading.** A Python library called
pdfplumber opens the PDF and reads the actual text characters the IRS embedded
in the file. This is exact, not interpretation. It costs nothing and uses no
AI tokens.

**Stage 2 — Claude does the thinking.** Claude reads the small summary files
from stage 1 and compares them to your draft return. That's the part that
needs judgment.

```
data/input/*.pdf  ──►  python3 run.py  ──►  data/output/  ──►  Claude
   (your PDFs)         (local, free)        (4 small files)    (reasoning)
```

---

## Setup (once)

```bash
python3 -m pip install -r requirements.txt
```

If you get an error mentioning `cryptography` or `pyo3_runtime`, your system
has an old copy of a library that pdfplumber needs. Fix it with:

```bash
python3 -m pip install --upgrade cryptography
```

---

## Using it

**1. Get your transcripts.** On IRS.gov, go to *Get Transcript* → *Get
Transcript Online*, or pull them from e-Services TDS if you have it. Download
them as PDFs. For preparing a return you usually want:

| Transcript | What it gives you |
|---|---|
| **Wage & Income** | Every W-2, 1099, 1098, 5498 and K-1 filed under that SSN. This is the one that catches missed income. |
| **Account** | Estimated payments, extension payments, refunds, prior-year credits. **These appear nowhere else.** |
| **Return** | A prior year's return exactly as the IRS posted it — including any changes the IRS made. |

**2. Drop them in.**

```bash
cp ~/Downloads/*.pdf data/input/
```

**3. Run it.**

```bash
python3 run.py
```

**4. Look at what came out** — four files in `data/output/`:

| File | What it's for |
|---|---|
| `summary.md` | Every document the IRS has, grouped by form type, with totals and review flags. **Start here.** |
| `rollup.md` | The same amounts, but grouped by which Form 1040 line they belong on. This is the tie-out sheet. |
| `crosscheck.csv` | Open in Excel or Google Sheets. One row per amount, with a blank column for your return's figure and a formula that shows the difference. |
| `transcripts.json` | Everything, including fields nothing else shows. For reference and archiving. |

**5. Hand it to Claude.**

> Read data/output/summary.md and data/output/rollup.md. Here are my draft
> return figures: [paste them]. What's unaccounted for?

If you're in Claude Code in this folder, just say *"review the transcripts
against my return"* — the `transcript-review` skill in `.claude/skills/`
takes it from there.

---

## What the output looks like

`rollup.md` gives you this:

| Return line | Transcript total | Sourced from | What the line is |
|---|---|---|---|
| **Form 1040 line 1a** | 100,750.00 | 2 × W-2 | Total amount from Form(s) W-2, box 1 |
| **Form 1040 line 2b** | 1,240.00 | 1 × 1099-INT | Taxable interest |
| **Form 1040 line 25a** | 9,860.00 | 2 × W-2 | Federal income tax withheld from Form(s) W-2 |
| **Schedule C line 1** | 24,000.00 | 1 × 1099-NEC | Gross receipts or sales |

So if line 1a on your draft says 98,400 and this says 100,750, you know
immediately that a W-2 is missing — and `summary.md` tells you which employer.

---

## Things worth knowing

**Every number is literal.** Nothing is estimated or inferred. If a box was
blank on the transcript, it comes out blank — not zero. Totals are plain sums.

**Differences are normal.** A return line legitimately differs from the
transcript total for lots of reasons — basis on a stock sale, a rollover, the
taxable portion of social security. The tool's job is to show you every
difference so you can confirm each one has a reason. It doesn't tell you the
return is wrong.

**Line numbers are a starting point.** Mappings follow the Form 1040 layout
used for tax years 2023–2025. Line numbering shifts between years — confirm
against the actual form.

**Transcripts are not complete.** Wage & Income transcripts for a tax year
aren't fully populated until around the middle of the following year. And
plenty of income never generates an information return at all. "Nothing
missing from the transcript" is not "nothing missing from the return."

**Your data stays local.** The tool makes no network calls. `data/input/` and
`data/output/` are gitignored, along with every `*.pdf`, so nothing with a
taxpayer's name in it lands in version control by accident.

---

## Troubleshooting

**"No PDFs found"** — they need to be in `data/input/`, ending in `.pdf`.

**"NO TEXT LAYER on any page"** — that PDF is a scan or a photo, not a real
IRS download, so there's no text to read. Get the original from IRS.gov. (An
optional OCR path is noted in `requirements.txt` if you truly can't.)

**"could not identify this as an IRS transcript"** — check what the extractor
actually read:

```bash
python3 run.py --dump-text data/input/yourfile.pdf --page 1
```

**A form parsed with no amounts** — the layout is one the parsers don't know
yet. Everything still lands in `transcripts.json` under `raw_fields`, so
nothing is lost. `CLAUDE.md` has the steps for adding it.

**Just want to know what these PDFs are?**

```bash
python3 run.py --classify data/input/*.pdf
```

---

## Development

```bash
python3 -m pytest -q        # 91 tests, all on synthetic fixtures
```

`CLAUDE.md` documents the layout, conventions, and how to add a new form type.
No real taxpayer data is ever committed — test fixtures are fabricated, and
the PDF fixtures are generated at test time rather than stored.
