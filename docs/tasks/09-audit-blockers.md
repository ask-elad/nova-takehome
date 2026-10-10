# Task 09 · Fix the audit's blockers (score caps, lost batches, feedback)

**Source:** an independent audit of the repo (findings B1–B4, M1, M2, M4, M11, minors). The human triage is
below; follow it. Real runs as in 05a. Commit after each item goes green.

## Regression gates: run after every item, all must hold
- `pytest` green;
- `make eval` all pass;
- `make grade` ≥ 99;
- `make sheet` answer sheet **unchanged** (total savings 8165.33).

If a fix changes one of these, stop and explain before going on.

## Items, in order
1. **B4 · feedback.**
   - `one_off_approval` + `waiver_scope` means the waiver covers the named months **on that key only**. That key
     becomes a `finding` (with `learned_at`), not `no_finding` (GLOSSARY; compare `reject`, which drops a key).
   - Match months by the typed `waiver_scope` value, not by searching quote text.
   - Fix `evals/cases/waiver_one_off_next_month.yaml`, which encodes the inverted reading.
   - `sender_authority`: resolve `subject.person` (a name) to the email addresses of held emails whose `From`
     display name matches, then grant the category on that contract from `valid_from`.
2. **B2 · waivers.**
   - A waiver that names no AWB, invoice or month is **no finding**.
   - Match `w.invoice` when it's given.
   - Evaluate the waiver's condition with the Judge, given the waiver text; if unknown, no finding.
   - Merge candidates per key.
3. **B1 · the five checks for acting alone, computed for real.** Each candidate carries: pickup-date source,
   the lowest authority level relied on, whether any feedback or quoted text was used, and whether an open
   conflict exists on the same contract and lane. `harness.py` passes these to `apply_policy`.
   - **Unknown means fail** (`human_review`). Keep the escalation rate under 60%: escalate only what really
     fails a check.
   - New evals: a $200 dispute whose pickup date comes only from the invoice must be `human_review` in
     autonomous mode; a clean tracked one must be `execute:dispute`.
4. **B3 · a bad fact drops one item, never the batch.**
   - One tolerant parser for dates (ISO, D/M/Y, month names, US M/D/Y when the day is over 12) and for amounts
     (commas, currency symbols and codes), used by every rule.
   - Values that fail verification are kept with low confidence, never blanked to `""`.
   - Wrap each rule module, and each item's assembly, in try/except: log to stderr and skip that item.
   - Test: a document with a malformed date still yields a valid report with the other items.
5. **M11 · schema validity.** Store feedback with its envelope (`after_batch`, `decided_at`). `learned_at.batch`
   is always a string, and the cited `feedback_item_id` is the item that actually caused the change. Validate
   every report against the schema in a test.
6. **M4 · grader robustness.**
   - Fall back on `PermissionDeniedError` (403) and model-unavailable 400s, not just 404.
   - Use `timeout=90` and low SDK retries.
   - A deadline of about 540 seconds per step: stop starting new calls and save what's done.
   - Each ingest re-attempts any document that has no saved facts.
7. **M2 · authority from the header.**
   - The sender is `DocRecord.sender_addr` (the parsed `From`), never the model-chosen line.
   - Empty `own_lines` means the whole body is treated as quoted.
   - Facts on lines flagged `addresses_automation` or `gives_orders` are dropped as level 5.
8. **M1 · confidence from real signals.** Pass the pickup source, re-read, authority level, Judge use and INR
   signals into `confidence.py`.
9. **Minors:**
   - INR: compute the finding in INR and convert the **difference** once.
   - An `.eml` without a `Date` header doesn't crash ingest.
   - Add `.claude/settings.local.json` to `.gitignore`.

## Done when
The regression gates hold, and the new tests and evals pass. Show:
- the four gate outputs;
- the escalation rate in both modes;
- a one-line note per item.