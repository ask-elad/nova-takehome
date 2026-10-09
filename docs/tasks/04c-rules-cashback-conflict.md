# Task 04c · Rules: cashback, conflict, cannot_determine

**Phase:** 3 · **Follows:** `docs/tasks/04b-rules-invoice-classes.md` (ground rules from task 04 still apply)

## Do, in this order, committing after each one goes green
1. **cashback** (task 04, step 3): quarterly `rebate` and `promised_credit` per contract year (`CYn`), with the
   `cashback` golden test, including its decoy quarter.
   - Unit tests: whole vs marginal tiers; a quarter not yet closed gives nothing; an INR invoice converted per
     invoice month; a credit already issued for the period is subtracted; a credit issued early that covers what
     is owed gives no finding; `draft:claim_credit` vs `internal:track_credit` around the due date.
2. **conflict** in `resolve.py`, with the `conflict` golden test.
   - The decoy: a rate notice from a sender without `rates` authority means the amendment governs and it's a
     plain overcharge.
   - Unit test: `amount_range` lower bound never below 0.
3. **cannot_determine** in `resolve.py`: a held document names a document we don't hold, and the answer depends
   on it. `missing_doc` is the name exactly as cited, and the holder comes from Schedule 1 (rates person for a
   rates annex or rate notice, treasury person for Annex F, payment_terms person for payment terms).
   - Unit test: a missing document that couldn't change the answer is **not** `cannot_determine`.

## Done when
All eight golden tests and the full suite are green. Show `.venv/bin/python -m pytest harness/tests -q`.
Then tick Task 04 in `docs/PLAN.md`.