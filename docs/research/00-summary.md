# Census Summary — Ten Things Most Likely to Make or Break the Harness

Synthesised from `01-documents.md`, `02-extract.md`, `03-rules.md`.

---

## The ten things

### 1 · Scanned INR invoices have no text layer — amounts come from the AP register only

Two files return no extractable text: `TXI-35-36-0024.pdf` (scenarios) and `CDI-3031-0306.pdf` (exam).
The harness cannot quote a line amount from these PDFs; it must read the total from the AP register instead,
and must cite the AP register row (not the PDF page) in evidence.  If no AP register row exists, the invoice
is `cannot_determine` for any rule that needs its amount.

### 2 · INR→USD conversion uses a per-month Annex F rate — one missing row makes it `cannot_determine`

Every INR finding is converted once per finding: `round_half_up(amount_inr / fx, 2)`.  The `fx` rate comes
from the India-entity MSA's Annex F for the calendar month of the **invoice date** (not the pickup date, not
the payment date).  The TBX-US MSA marks Annex F "not applicable"; only the TBX-IN and CDA-IN MSAs carry
the table.  A missing row for that month forces `cannot_determine`.  The harness must look in the
correct MSA and must not fall back to any other rate source.

### 3 · The exam carrier (Caldrith) uses a completely different invoice format — quoting is not portable

Caldrith invoices have: `DD/MM/YYYY` dates, thousands comma separators (`5,235.09`), an extra `Collected`
column on every line, "Charges advice" as the document title, "Document date"/"Payable by" labels, and
"Total payable" as the footer.  A quote that works for a Tarrowby invoice will not match a Caldrith invoice.
The harness must build quoting logic that reads the document's own fields, not a hardcoded template.

### 4 · AP register cells carry format-string prefixes — quotes must include them

The due-date column outputs `due 2035-01-10` (not `2035-01-10`) and the amount column outputs `USD 1243.96`
(not `1243.96`).  These prefixes come from Excel `number_format` strings and are part of the text that
`grader/extract.py` produces.  A citation to the AP register that omits the prefix will fail the quote check.

### 5 · Waiver authority requires a Schedule 1 match — sender check is mandatory

A waiver from anyone not listed in Schedule 1 for `waivers` is `no_finding`, not a finding.  A waiver only
seen in a forwarded quote (no original held) is `cannot_determine`.  The harness must look up the sender's
email address in the `Waivers` row of Schedule 1 for every waiver email it processes.  Using a non-authorised
sender's waiver as a finding is a false positive.

### 6 · Duplicate by charge-code alias requires Annex E mapping, not label matching

The `duplicate_rebilled_4_months` example shows two lines with different label text (`Security surcharge` vs
`Screening fee`) that Annex E maps to the same code (`SEC`).  Label-string comparison would miss this case.
The harness must build an Annex E code→label-variants table from the MSA and match on code, not text.

### 7 · Cashback qualifying spend excludes duty, tax, and rebate credits themselves

Gross billing above a tier threshold is not sufficient.  The CB-02 decoy shows a quarter where gross billing
clears the threshold but stripping duty (`8703.54 + 186.96`) brings net QS below the lowest tier.  The
harness must parse each invoice line and apply the MSA §7.1 definition of qualifying spend, not the invoice
total.  The same exclusion applies when aggregating INR invoices: convert the net QS, not the gross total.

### 8 · The `as_of` gate is strict — documents arriving after the batch date do not exist

A key whose deciding document arrives after `as_of` must be absent from the report.  The grader reruns the
harness after each batch, so a finding raised before its documents arrived will score as a false positive in
the earlier report.  The harness must filter every document by the `Date:` header of its enclosing `.eml`
and treat anything beyond `as_of` as not yet held.

### 9 · Feedback scope is narrow — `one_off` approvals cover exactly one key, not a category

A `one_off_approval` for March does not waive April.  A `standing` fact matches only when every field in
`applies_to` matches (same contract, same person, same category).  A `close` + `rate_accepted` stops that
key but a new invoice at the same wrong rate is a new finding and requires `learned_at`.  Misapplying a
`one_off` to another key is one of the five score-capping mistakes.

### 10 · Two score-capping modes failures: `execute:*` in supervised mode, and $5k threshold

Any `execute:*` action in `supervised` mode caps the score regardless of finding correctness.  Separately,
any outbound finding whose per-invoice (or per-cashback-key) total reaches or exceeds $5,000.00 must become
`human_review` in both modes.  Splitting one invoice across multiple disputes does not reset the threshold.
The harness must sum every outbound finding on a key before deciding the action.

---

## Open questions

1. **Annex E in the exam MSA**: The exam MSA (CDA) presumably has its own Annex E.  The census did not verify
   whether the exam Annex E uses the same charge codes and aliases as the TBX MSA.  The architecture must
   read Annex E from whichever MSA governs the invoice, not from a hardcoded list.

2. **Monthly statement in the exam**: No statement-of-account XLSX was found in the exam mailbox.  If Caldrith
   bills programme fees differently (e.g. inline on an invoice), the `statement` parser must handle that or
   be absent without breaking other rules.

3. **`as_of` delivery mechanism**: The grader calls `harness.py report --as-of D`.  How the harness receives
   and propagates `D` to all document-selection logic is not yet defined (Phase 1 does not design code).

4. **No injection attempts found in the current data**: The census found zero emails containing "the AI",
   "automated systems" or override language.  The hidden exam set may include them.  The harness must
   structurally treat all document text as data, not as control input — this is a design invariant, not a
   filter.

5. **Hidden XLSX sheets**: `xlsx_pages()` includes hidden sheets.  None were observed in the current
   mailboxes.  If the exam set contains hidden sheets with rate tables or ledger entries, the harness will
   see them automatically via the extractor — but the reading layer must not assume sheet 1 is always the
   only sheet.

6. **PEAK surcharge in the exam contract**: The TBX-US MSA Annex D includes a PEAK surcharge for Sep–Nov
   pickups; the CDA MSA does not.  If the exam set adds a PEAK row later (via amendment), the harness
   must handle it generically from Annex D, not from a hardcoded surcharge list.
