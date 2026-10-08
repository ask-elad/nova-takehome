# 02 — Extractor behaviour (`grader/extract.py`)

Source reviewed: `/home/askeladd/Documents/AAtakeHome/nova-takehome/grader/extract.py`  
Outputs examined: `out/text/data_scenarios/batch_01/`, `out/text/data_scenarios/batch_02/`,
`out/text/data_exam/batch_01/`

---

## 1. What `pages_of` returns per document kind

### `.eml`

`email_lines()` produces **exactly one page**. The header block is:

```
From: <display name> <<addr>>
To: <raw To: header, verbatim>
Date: <ISO-8601 UTC, e.g. 2034-10-02T09:21:00Z>
Subject: <subject>
<blank line>
<plain-text body lines>
Attachments: file1.pdf, file2.xlsx
```

The `Cc:` line is only emitted when the message has a Cc header.  
The `Attachments:` line is only emitted when there is at least one attachment; filenames are
`get_filename()` results joined by `", "`.  
The body uses `msg.get_body(preferencelist=("plain",))` — the plain-text part only, with CRLF
normalised to LF.

Example (`out/text/data_scenarios/batch_01/0001.eml.txt`):
```
From: Joaquin Rathbone <joaquin.rathbone@tarrowby.example>
To: isolde.pembroke@quillmere.example
Date: 2034-10-02T09:21:00Z
Subject: Executed agreement TBX-US-EXP-01
...
Attachments: MSA-TBX-US-EXP-01.pdf
```

### PDF (text layer present)

`_reading_order()` calls `page.get_text("words")`, which returns each word with its bounding box
`(x0, y0, x1, y1, text, ...)`.  Words are sorted by **vertical mid-point** `(y1+y3)/2` (i.e.
`(y0+y1)/2` in PyMuPDF's coordinate system), then horizontally within the same baseline.  The
grouping tolerance is **2.5 px**: if the current word's mid-point is within 2.5 px of the last
group's mid-point, it joins that group; otherwise a new group is started.

Each baseline group is then sorted by `w[0]` (left edge `x0`) and its words are joined with a
single space.  Groups are joined with `\n`.

`pdf_pages()` returns one string per PDF page.  Pages in the dump files are separated by
`--- page N ---` markers (added by the dumper, not by `pages_of` itself).

### XLSX

`xlsx_pages()` iterates `wb.worksheets` (all sheets, including hidden ones, in sheet-tab order).
Each sheet becomes one page.  For each row, empty cells are **dropped** (`if t != ""`), and the
remaining cell texts are joined with `" | "`.  Rows where every cell is empty are also dropped.

`_cell_text()` converts values:

| Value type | Output |
|---|---|
| `None` | `""` (cell dropped) |
| `datetime` | `v.date().isoformat()` → `YYYY-MM-DD` |
| `date` | `v.isoformat()` → `YYYY-MM-DD` |
| `int / float / Decimal` | Decimal-formatted to `dp` decimal places where `dp = len(fmt.split(".")[1])` if `"."` in format, else 0 |
| `bool` | Passed through `str()` (bool is excluded from numeric branch) |
| other | `str(v)` |

The **format prefix** feature: if the cell's `number_format` starts with `"<text>"` (a
double-quoted literal), that text is prepended to the output.  This is how the AP register
produces `due 2035-01-10` — the due-date cells carry a format like `"due "YYYY-MM-DD`.

### Scanned PDF (image-only)

`pdf_is_image_only()` opens the PDF with PyMuPDF and tests whether **every page** returns an
empty string from `p.get_text().strip()`.  If so, it returns `True`.

When `Mailbox.pages()` detects a scan, it still calls `pdf_pages()` on it — which returns one
entry per page (each entry is an empty string or near-empty).  The `is_scan` flag is returned
alongside.  `Mailbox.check()` skips quote verification for scans and only validates that the
cited page number is in range.

No scanned PDFs were found in the scenario or exam dumps (all PDF `.txt` outputs contain real
text).  The DGD files (e.g. `DGD-TX55747635.pdf`, `DGD-TX69361253.pdf`) have text layers and
produce normal single-page output.

---

## 2. Line order in invoice tables

Invoice PDFs (e.g. `TX-US-2034-0379.pdf`, `TX-US-2035-0184.pdf`) render each invoice line as a
single horizontal text line.  Because the baseline tolerance is 2.5 px and all cells in a row
share the same baseline, the entire row lands in one group and columns come out **left-to-right in
reading order**, space-separated:

```
1 TX46602456 2034-11-17 Air freight USS2-INW2 299 kg 2.84 849.16
```

No column reordering or splitting was observed in any invoice table.  Multi-shipment invoices
(e.g. `TX-US-2035-0184.pdf` with 24 line items and 6 shipments) remain on one PDF page and each
row appears as one text line.

---

## 3. Annex tables (multi-column rate schedules)

Annex A rate tables in the MSA PDFs render as flat, one-row-per-line output with no column
merging issues.  Each row in the PDF has its own baseline and all columns share it, so the output
is:

```
Lane Weight band P1 rate P2 rate
USS2-INW2 minimum charge 47.00 47.00
USS2-INW2 0-44.5 kg 3.33 3.32
USS2-INW2 45-99.5 kg 3.08 3.06
```

(from `out/text/data_scenarios/batch_01/0001.eml#MSA-TBX-US-EXP-01.pdf.txt`, page 8)

The header row (`Lane Weight band P1 rate P2 rate`) is part of the text output.  The table spans
many rows but remains on a single PDF page; the extractor keeps them all together on that page.

Similarly, Annex C (fuel surcharge) and Annex D (accessorials) come out as clean two- or
four-column tables, one row per line.

Annex F (exchange rates) renders as `Month INR per 1 USD` header followed by `2035-01 78.84`
etc., one month per line.

---

## 4. Excel rows in detail

### Tracking export (`tracking-2034-10-01.xlsx`, `tracking-2030-01-01.xlsx`)

Single sheet, one page.  Header row:
```
AWB | Event | Date | Station | Reason code
```
Data rows (dates are `YYYY-MM-DD`, reason codes are the string `"-"` when empty — note this is a
literal dash string in the cell, not an empty cell, so it does appear):
```
TX23827044 | PICKED_UP | 2034-11-04 | USS2 | -
```

### AP register (`ap-register-2035-05-31.xlsx`, `ap-register-2030-08-31.xlsx`)

Single sheet, one page.  Header:
```
Invoice no. | Invoice date | Due date | Amount | Status | Paid date
```
Data rows:
```
TX-US-2034-0379 | 2034-11-26 | due 2035-01-10 | USD 1243.96 | paid | 2035-01-03
```

Key formatting points:
- **Due date** uses a format-string prefix `"due "` followed by a date format, producing
  `due 2035-01-10` as the cell text.
- **Amount** cells include the currency prefix (e.g. `"USD "`) from the format string, producing
  `USD 1243.96`.
- **Paid date** for open invoices is `"-"` (literal dash string, not empty), so it appears in the
  output.
- Dates are always ISO `YYYY-MM-DD`, regardless of any locale.

### Statement of account XLSX (`TX-ST-203411.xlsx` etc.)

Single sheet, one page.  The `" | "` separator appears inside merged-style header rows too
(because the sheet itself uses separate columns):
```
Statement date 2034-12-01 | Due date 2035-01-15
Charge | Reference | Quantity | Rate | Amount
Monthly account fee | 2034-11 | 1 month | 350.28 | 350.28
Total USD | 1426.50
```

---

## 5. Quoting traps

### Wrapped PDF lines

The `norm()` function (`" ".join(s.split())`) collapses all whitespace including newlines.  The
comment in `extract.py` says "a long line wraps at a space in a PDF" — `found()` uses
`norm(quote) in norm(page_text)`.  This means a quote that spans a visual line-wrap in the source
PDF is safe **as long as no extra words intervene**.  However, a quote that spans two distinct
PDF baselines (more than 2.5 px apart) will have a `\n` between them; `norm()` collapses that
`\n` to a space, so it still matches provided the word sequence is preserved.

**Risk**: If a long contract sentence is split across two baselines (common in body text), the
entire multi-line passage can be quoted as one string — but only if the candidate quotes the text
exactly as it appears in the dump (with the newline becoming a space).

### Exam invoice — comma-separated numbers and `DD/MM/YYYY` dates

The exam invoices (Caldrith carrier, `CDU-*` / `CDI-*` files) format amounts with thousands
separators and dates as `DD/MM/YYYY`:

```
USC1-INW1 CA93971959 Air freight 771 kg 6.79 5,235.09 17/07/2030
USC1-INW1 CA93971959 Fuel surcharge 5,235.09 21.79% 1,140.73 17/07/2030
```

(from `out/text/data_exam/batch_01/0012.eml#CDU-3051268.pdf.txt`)

This means:
- Amounts in quotes must include the comma (e.g. `5,235.09` not `5235.09`).
- Dates in quotes must use `DD/MM/YYYY` (e.g. `17/07/2030` not `2030-07-17`).
- The `Charges USD 49,988.69` footer line also uses a comma.
- For the Caldrith India invoices (`CDI-*`), amounts have both thousands separators and the
  `INR` prefix in the footer: `Charges INR 54,710.92`.

The scenario invoices (Tarrowby carrier, `TX-US-*` / `TXI-*`) use no thousands separators and
ISO dates — a completely different visual style.

### Exam invoice — "Collected" column

Caldrith invoices have an extra `Collected` column at the end of each line item containing the
pickup date in `DD/MM/YYYY`.  The extractor outputs it as part of the same line:

```
USE2-INS2 CA51959332 Air freight 299 kg 5.69 1,701.31 19/05/2030
```

A quote from the Caldrith invoice body must include the `Collected` date to be an exact
substring match, **or** must be a substring that does not reach the end of the line.

### AP register — "due " prefix and "USD " prefix

Quoting the due-date field from the AP register requires including the `due ` prefix:
`due 2035-01-10`, not `2035-01-10`.  Quoting the amount requires the `USD ` prefix:
`USD 1243.96`.  These come from cell format strings via `_cell_text()`.

### Header row mixed into data

XLSX pages include column headers as the first row of output.  A citation to page 1 of a
tracking XLSX will produce a page whose `norm()` content includes the header
`AWB | Event | Date | Station | Reason code` followed immediately by data rows.  Quotes that
accidentally contain only a portion of the header row text will still match.

### Empty-cell skipping in XLSX

`_cell_text()` returns `""` for `None` cells, and `xlsx_pages()` filters them out before
joining.  This means a trailing empty cell at row end is silently dropped, and the row has one
fewer `|`-segment than the header row.  An open invoice's `Paid date` column would be dropped if
the cell were empty — but in the actual files the cell contains a literal `"-"` string (not
`None`), so it is retained.

### `norm()` whitespace collapsing — helps and hides

`norm()` is applied to both the quote and the page text in `found()`.  This means:
- Multiple spaces between words are collapsed — safe for quoting.
- Leading/trailing whitespace in quotes is collapsed — safe.
- Newlines (from PDF baseline breaks) become spaces — allows quoting across lines.
- But it also hides any difference between single-space-separated and multi-space-separated
  column data; the extractor's own output already uses single spaces between PDF words, so this
  is rarely a practical issue.

---

## 6. The scanned PDF

No image-only PDF was found in either the scenario or exam output directories.  All `.txt` dump
files contain real extracted text.  The `pdf_is_image_only()` function would return `True` for a
PDF where every page yields an empty `get_text()`, but no such file exists in the current
mailboxes.  When a scan is encountered at runtime, `Mailbox.check()` skips quote verification
and only validates the page number against `len(pages)`.
