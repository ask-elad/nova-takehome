# Task 05b · End-to-end: ingest, report, first real score

**Phase:** 4 · **Follows:** `docs/tasks/05a-readers.md` (the key and cost rules there still apply)

## Build
1. **`ingest`:** for each new document, classify and read it (thread pool, at most 8 at once), verify, then save
   the facts next to the document record in the state dir. A document already read is never read again.
2. **`report`:**
   - load records received by `as_of`, with their facts;
   - build the `Case` (sheet rows from pages, the Claude `Judge`);
   - run all six rule modules, then `resolve`;
   - print schema-valid JSON: findings in `findings`; cashback, expiry and late-fee risk in `portfolio`.
3. **Placeholder actions,** until Phase 5:
   - findings: `draft:dispute` (`draft:claim_credit` for cashback);
   - expiry: `internal:alert`; late-fee risk: `internal:payment_reminder`;
   - conflict: `escalate`; cannot_determine: `draft:request_document`.

   **Never emit `execute:*`, in either mode.** Confidence is a fixed 0.9 for now.
4. Every step must finish well inside the grader's 600-second limit per step. Print the ledger totals to stderr
   at the end of `ingest`.

## Tests (offline)
- `report` output validates against the schema for a state dir built from fixtures.
- No `execute:` anywhere in the report, in either mode.
- An ingest that's run twice makes no new model calls (the ledger shows cached calls only).

## Done when
In the shell that has the key: `make grade` runs end to end. Show the score, the report card's `missed`, `false`
and `wrong_amounts` lists, the ledger summary, and the time taken by each step. Commit `report_card.*`.