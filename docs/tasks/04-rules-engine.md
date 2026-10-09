# Task 04 · Rules engine on hand-written facts (all six classes)

**Phase:** 3 · **Follows:** `docs/decisions/0001-architecture.md` §4–5, `GLOSSARY.md`

## Why
Prove every rule in the glossary on our golden facts, with no model in the loop. In Phase 4 the readers will be
measured against these same facts, so a bug found here can't be blamed on the model.

Commit after each step that goes green. Several commits in this session is expected.

## Ground rules
- Rules read **typed fields only**. If a rule needs to parse free text (a band, a basis, a label), the schema is
  missing a field. Add it, fill it in the fixtures, and say so in your summary.
- Money is `Decimal`. The only rounding is `round_half_up(x, 2)`, applied where the glossary applies it.
- No model calls. Judgement calls that need reading go through a `Judge` interface (step 2). In tests it answers
  from fixtures; in Phase 4 it calls Claude.
- Never hardcode a name, lane, contract id or layout. Everything comes from the facts.

## Steps

**0. Two schema additions** (with fixture updates):
- `BillingLine.category`, one of: `freight`, `fuel`, `security`, `accessorial`, `minimum_charge`, `tax`, `duty`,
  `disbursement`, `late_fee`, `credit`, `programme_fee`, `other`. Also `BillingLine.refers_to_invoice` (a late
  fee names the invoice it's charged on).
- `qs_includes` and `qs_excludes` become lists of those categories. Keep the clause text as `qs_text: Val` for
  evidence.

**1. `nova/money.py`:** `round_half_up`, INR→USD once per finding (`amount_inr / fx`, rounded), with the fx for
the calendar month of the invoice date taken from the contract's FX rows. A missing month means
`cannot_determine`.

**2. `nova/case.py`: the case model.** Build it from (document records, facts per document, `as_of`). Only
documents received on or before `as_of` count.
- **Contracts:** MSA plus amendments. "Terms in force on date D" gives the rate row, fuel %, accessorials and FX,
  with the source and authority of each. A later signed amendment beats an earlier one for the same lane.
- **Rate notices:** from email senders who are in Schedule 1 for `rates` on that contract (exact address match).
  They're in force inside their effective dates.
- **Spreadsheets:** tracking events and payment-register rows, parsed from page text using each `SheetMap`.
- **Pickup date per AWB,** in this order: tracking `PICKED_UP`, then a carrier pickup email, then the AWB executed
  date, then the date printed on the invoice line. Keep which source it came from.
- **Authority lookup:** person + contract + category gives yes or no, from Schedule 1. Quoted or forwarded text
  never counts.
- **`Judge` interface:** `judge(question_id, context) -> (bool, ref)`, for things like "does this accessorial's
  condition apply to this shipment?" (dry ice vs DG fee) and "was the waiver's condition met?". The test judge
  reads answers from `fixtures/examples/<ex>/judgements.json`.

**3. `nova/rules/`, one module per class.** Each returns *candidates*: the key, the billed amount, one correct
amount *per source* (with authority level and whether it was in force), evidence refs, an optional missing
document, and an optional deadline. Order: overcharge, duplicate, waived_but_billed, late fees (not owed and
risk), cashback (rebate and promised credit), expiry.
- **overcharge:** reprice each line from the terms in force on its pickup date:
  - freight is rate × chargeable weight at the band that contains it, with the minimum charge;
  - fuel % for the pickup month is applied to the *correct* freight;
  - accessorials by `basis_kind`, months and the `Judge`.

  The finding is the sum of billed − correct over the wrong lines, one per invoice. Zero or less is no finding.
- **duplicate:** same invoice number resent while the register shows the first paid or scheduled and the resend
  asks for payment (the amount is the total). Or two invoice numbers billing the same AWB + charge code (Annex E
  aliases): flag the later invoice date, for the duplicated lines only. Credited in full is fine; credited in
  part is the overlap minus the credit.
- **waived_but_billed:** a waiver in the sender's own text, from a Schedule 1 `waivers` person for that contract,
  naming the AWB or month, with any condition met. The amount is the waived line. A non-authorised sender gives
  no finding. A waiver seen only in quoted text gives `cannot_determine`, held by the issuing party's Key Account
  Manager from Schedule 1.
- **late fees:**
  - *not owed* uses days_late = paid − due (the extended due date if an authorised `payment_terms` person
    extended it), then grace, then `ceil(days/30)` months, simple or compound, giving billed − correct;
  - *risk* means 0 < due − as_of ≤ 14 on an unpaid invoice: one month's fee on the open amount less anything we
    dispute on it, in the invoice currency, converted once.
- **cashback:**
  - *rebate:* for each closed quarter, QS is the sum of lines in `qs_includes` categories on invoices dated in the
    quarter, minus in-period credit notes (rebate and improvement credits excepted), with INR converted per
    invoice. Then the tier rule (whole or marginal), minus credits already issued for that contract, period and
    type.
  - *promised_credit* works the same way per contract year (`CYn`).
  - Action is `draft:claim_credit` once due, otherwise `internal:track_credit`.
- **expiry:** the operative date is the end date, or end date minus notice days when the contract auto-renews.
  Report when 0 ≤ deadline − as_of ≤ 60.

**4. `nova/resolve.py`: candidates to items.**
- **Precedence:** a signed amendment beats the MSA. A source without authority drops out.
- **Conflict:** two authorised sources in force, unranked by the precedence clause, giving different correct
  amounts. Report `conflict` with `amount_range = [max(0, billed − higher), billed − lower]` and both sources in
  evidence.
- **Cannot determine:** a held document names a document we don't hold, and the answer depends on it. The
  holder comes from Schedule 1.
- **Evidence quotes** come from `resolve_lines` on the refs. Every quote must be at least 12 non-space characters.
- Set `action` to a placeholder for now. Actions and modes are Phase 5.

## Tests (write each one before its code)
- **Unit tests from the glossary:** rounding ties; INR once per finding; late-fee windows at days 0, 14 and 15;
  expiry at 0, 60 and 61; compound vs simple; duplicate credited in part; marginal vs whole tiers; a
  non-authorised waiver; a quoted-only waiver; band edges (44 vs 44.5 vs 45).
- **Golden test, per worked example:** build the case from the example's documents + `facts.json` +
  `judgements.json` at the example's `as_of` (in `expected_finding.json`).
  - Every expected item matches on key, verdict, amount (±0.01), `amount_range`, deadline and `missing_doc`.
  - Every decoy is absent or `no_finding`.
  - Every quote we produce is found by `grader/extract.py`'s `found()` on its page.

## Done when
All eight golden tests and the full suite are green. Show `.venv/bin/python -m pytest harness/tests -q`, and list
any schema fields you added and why.