# Task 03a2 · Fixes from the review of task 03a

**Phase:** 2 · **Follows:** `docs/tasks/03a-schemas.md`

## Why
The review accepted the fixture ref changes and the two fields made optional. It found one hole in the value
checker, and several places where the rules engine would have to parse free text. The rules engine must only
read typed fields: parsing "300+ kg" or "USD per chargeable kg" in rule code is layout parsing, and it breaks on
new carriers. Each fix starts with a failing test.

## Fixes

**1. Numbers and dates must match whole tokens.** (`verify.py`)
Today these all pass, and must fail:

| value | line contains |
|---|---|
| `2.84` | `12.84` |
| `44` | `144 kg` |
| `6.01` | `16.01` and `6.16` (but not `6.01`) |
| `340.1` | `340.12` |

A numeric value matches only when it isn't directly next to another digit or a decimal point followed by a digit.
Apply the same rule after stripping thousands separators (`5,235.09` still matches `5235.09`). Dates match only
as whole tokens.

**2. Dictionary values get checked too.** `SheetMap.columns` values are skipped today, because `_walk` returns
early on plain strings. Check them against the header line.

**3. Typed fields instead of text the rules would have to parse.** (`schemas.py`)
- **`RateRow`:** `band_min_kg` and `band_max_kg` (`band_max_kg` null for an open top band), `is_minimum_charge`,
  and `rates` as a list of `{period, rate}` instead of a list matched to periods by position. Keep `band` as
  the printed text.
- **`Accessorial`:** `basis_kind` is one of `per_kg`, `per_shipment`, `pct_of_freight`, `per_month`,
  `per_piece`, `other`. Keep `basis` as printed.
- **Rebate:**
  - `rebate_tier_rule` becomes `whole` | `marginal`, with its ref; keep the clause text as a separate `Val`.
  - add `rebate_period`: `quarter` | `contract_year`;
  - add `qs_includes` and `qs_excludes`: the charge kinds the contract's qualifying-spend definition counts and
    excludes, with a ref. The glossary says the contract's definition wins.
- **Margin step-down:** typed rows (threshold, from %, to %, period, ref) instead of `list[Val]`.
- **`refers_to`:** a list of `{name, ref}`. A `cannot_determine` item needs the missing document's name exactly
  as cited, and a quote.
- **`EmailFacts`:**
  - own and quoted text become line ranges (`Ref` with `line_end`), not copies of the text. The model shouldn't
    retype the email, because output tokens cost money and copies can drift;
  - `waivers` and `extensions` become lists;
  - add `payment_requests`: the invoice ids the email asks to be paid, with any "copy", "reminder" or
    "for your records" mark, and a ref. A duplicate needs to know whether the resend asks for payment, and that
    is often in the email, not the PDF.

**4. Update the eight fixtures** to the new fields. Check every changed value against the extracted text.

## Tests (write them first)
- The four cases in the table fail; `5,235.09` and `17/07/2030` still match.
- A wrong `SheetMap` column label fails.
- Fixtures load and verify cleanly with the new fields.
- `basis_kind`, `rebate_tier_rule` and `rebate_period` reject values outside their lists.

## Done when
The full suite (`.venv/bin/python -m pytest harness/tests -q`) is green. Show the output.