# Task 04b · Rules: duplicate, waived_but_billed, late fees, expiry

**Phase:** 3 · **Follows:** `docs/tasks/04-rules-engine.md` (read it for the ground rules; they still apply)

## Where things stand
Done in task 04: `nova/money.py`, `nova/case.py` (case model and `Judge`), `nova/rules/overcharge.py`,
`nova/resolve.py`, and the overcharge golden test. 102 tests pass. Build on these modules. Don't restructure
them. If one gets in your way, stop and explain why.

## Do, in this order, committing after each one goes green
1. **duplicate** (task 04, step 3), with the `duplicate` and `duplicate_rebilled_4_months` golden tests.
2. **waived_but_billed**, with its golden test. Add the unit tests for a non-authorised sender and a quoted-only
   waiver (`cannot_determine`, holder from Schedule 1).
3. **late fees:** `late_fee_not_owed` and `late_fee_risk`, with the `late_fees` golden test. Add unit tests for
   days_late at 0, 14 and 15, compound vs simple, and an INR risk item converted once.
4. **expiry,** with its golden test. Add unit tests at 0, 60 and 61 days, with and without auto-renewal.

Fixtures: if a golden test fails because the fixture lacks a fact the rule needs, add it from the extracted text,
verify it, and list it in your summary. Never change an expected value in `expected_finding.json`.

## Done when
The five new golden tests and the full suite are green. Show `.venv/bin/python -m pytest harness/tests -q`, and
list every fixture fact or schema field you added.