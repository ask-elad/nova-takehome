# Task 03a · Reader schemas, the value checker, and hand-written facts for the examples

**Phase:** 2 (second half) · **Follows:** `docs/decisions/0001-architecture.md` §2–3

## Why
The rules engine (Phase 3) is built on hand-written facts before any reader exists. The readers (Phase 4) must
then produce the same facts. This task fixes the contract between the two halves: the typed shapes, the check
that every value is really on its cited line, and the hand-written facts for the eight worked examples.

No prompts, no API calls.

## Build

**1. `harness/nova/schemas.py`: Pydantic models.**
They serve as both the tool schema (`model_json_schema()`) and the Python types. Pydantic is already installed
with `anthropic`; pin its installed version in `harness/requirements.txt`.

- **`Ref`:** `page`, `line`, optional `line_end`. Every extracted value carries one.
- **Values:** money and rates as decimal strings normalised (`"5235.09"`), dates as ISO (`"2030-07-17"`), whatever
  the document printed.
- **`ContractTerms`** covers the MSA and the amendment:
  - id, kind, the contract it amends, parties, signed, dated, effective from, end date;
  - auto-renewal and notice terms; precedence order and unranked pairs; rate periods;
  - rate rows (lane, band min and max, minimum charge, rate per period);
  - fuel by month; accessorials (code, label, basis, rate, condition text, months applicable); charge-code aliases;
  - rebate (tiers, tier rule, qualifying-spend clause, due days); margin step-down; promised credits; payment
    terms (due days, grace days, late-fee rate, compounding, who may extend);
  - FX rows, Schedule 1 rows (name, title, party, categories, email);
  - documents it refers to, and key clauses (number, topic, ref).

  Any section can be `not_applicable` (with a ref). An amendment carries `effective_from` and only the rows it
  changes.
- **`BillingDoc`** covers the invoice, credit note and statement:
  - id as printed, kind, issuer, contract reference, currency, dates, totals;
  - marks such as "copy", "reminder" or "for your records", and whether it asks for payment;
  - for credit notes: credit type, period, and the invoices referenced;
  - lines (AWB, charge label, lane, quantity, unit, rate, amount, pickup or collected date).
- **`EmailFacts`:**
  - kind (waiver, due-date extension, rate notice, pickup, delivery, customs event, billing query, invoice
    transmittal, contract transmittal, other);
  - the sender's own-text lines vs quoted or forwarded lines (with the original sender, if shown);
  - waiver details (charge, AWB, invoice, month, condition), extension (invoice, new date), rate-notice rows with
    effective dates, pickup (AWB, date);
  - `addresses_automation` and `gives_orders`, each with a ref.
- **`SheetMap`:** the sheet kind (tracking export, payment register, other) and which column holds each of our
  fields.
- **`ShipmentDoc`** covers the AWB and DG declaration: AWB, master or house, executed date, origin, destination,
  pieces, actual and chargeable weight, goods, UN numbers, refrigerant-only.

**2. `harness/nova/verify.py`: does each value appear on its cited line?**
- **Money:** compare after normalising the line (drop thousands separators and currency codes).
- **Dates:** accept ISO, `DD/MM/YYYY` and month names on the line, converted to ISO.
- **Strings:** case-insensitive.
- **Output:** every failure, with field path and line text. No layout-specific rules: it must work for both
  carriers' formats as they stand in `docs/research/01-documents.md` §2.

**3. `harness/tests/fixtures/examples/<example>/facts.json`: hand-written facts.**
For each of the eight `data/examples/*`, write the schema objects for every document the example needs, by
reading the extracted text. These are our golden facts.

## Tests (write them first)
- Every fixture loads into its schema.
- `verify` passes on every fixture value against the real extracted text.
- `verify` fails on a deliberately wrong value, a wrong line, and a value from a neighbouring row.
- Both formats normalise: `5,235.09` on a line matches `"5235.09"`, and `17/07/2030` matches `"2030-07-17"`.
- Every schema exports a JSON schema the Messages API accepts as a tool `input_schema` (an object at the top
  level, no `$ref` the API can't resolve: inline the definitions if needed).

## Don't
Write prompts, call the API, or start on rules.

## Done when
Tests green. Then **stop**: the humans review `schemas.py` and one fixture before Phase 3 starts.