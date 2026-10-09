# Task 04a2 · Fixes from the review of task 04 (case model and overcharge)

**Phase:** 3 · **Follows:** `docs/tasks/04-rules-engine.md` (ground rules still apply)

## Why
The overcharge golden test passes, but the example is the simplest one: one MSA, no amendment, no rate notice,
USD only. The review found gaps that would break on the practice mailbox and the exam, and that tasks 04b and 04c
would build on. Each fix starts with a failing test.

## Fixes

**1. Spreadsheet rows are parsed in production, not in a test.** The tracking-row parser lives in
`tests/test_golden_overcharge.py`, so in the real harness `pickup_date()` would never see a `PICKED_UP` event.
- Move it to `nova/sheets.py`: `rows(pages, sheet_map) -> list[dict]`, driven by `SheetMap.columns` (header
  label to our field), for any sheet kind. Keep each row's page and line so it can be quoted.
- `Case` builds sheet rows itself from the document pages.
- Test it on a tracking export and a payment register from both mailboxes.

**2. One primitive for "terms in force", used by every rule.** Overcharge currently takes the first contract in
force that has the lane. That ignores the invoice's contract, never applies an amendment over the MSA, and looks
up fuel and accessorials only on whichever record it picked.

Add `Case.terms_on(contract_id, on_date)`:
- **The base is that contract's MSA.** Signed amendments to it with `effective_from ≤ on_date` are layered on in
  effective-date order. A later amendment replaces the rows it restates, per lane and band. Every other term
  falls through to the MSA.
- **Each value returned carries its source** (document and ref), authority level and precedence rank.
- **Rate notices come back as separate sources, never merged:**
  - in force on `on_date`;
  - the sender must be in Schedule 1 for `rates` on that contract, matched by exact address;
  - task 04c decides between sources.
- **Invoices choose their contract by `contract_ref`.** Never pick a contract just because it has the lane.

**3. Overcharge fixes:**
- Price **fuel after freight** for each AWB, whatever order the lines are printed in.
- Map **charge labels to codes through Annex E aliases**, then look accessorials up by code. Today "Screening
  fee" doesn't match "Security surcharge" and is waved through as correct.
- **Accessorial conditions:** apply `months`, and ask the `Judge` when the accessorial has a condition. For
  example, a DG fee billed on a shipment whose declaration says dry ice, refrigerant only: per the contract
  clause, the correct DG fee is 0 and the dry-ice fee applies. Add a unit test from practice variant OC-02's rule
  (`docs/research/03-rules.md`), on a small hand-made case.
- **INR invoices:** compute the finding in INR, then convert once, at the Annex F rate for the invoice month. A
  missing month is `cannot_determine`.

**4. Fixtures carry `received_at`** (the parent email's received date), so `as_of` filtering is really exercised.
Add a test: a document received after `as_of` changes nothing.

## Done when
The full suite is green, the overcharge golden test still passes, and the new tests cover each fix. Show the
pytest output.