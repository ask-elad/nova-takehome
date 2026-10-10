# Task 10 · Audit fixes for named hidden-set features

**Source:** audit findings B5–B8, M5, plus scan evidence. Same regression gates as task 09. Commit per item.

1. **B5 · `retro` and expiry.**
   - Set `retro: true` on a key that exists only because of a document received after an earlier report but
     dated or effective before it (a backdated amendment).
   - Expiry layers the signed amendments' `end_date` and renewal terms: an extension moves the date and can
     remove the alert.
   - Eval: a backdated amendment changes an earlier invoice's verdict (`supersedes` or `retro`).
2. **B6 · pickup events without hardcoding.**
   - The sheet reader also maps which event value means "picked up", and a wide-format pickup-date column if
     there is one.
   - Search the first 15 rows for the header.
   - Partial mappings keep their rows.
   - Normalise AWBs (case, spaces).
   - Remove the `"PICKED_UP"` literal from rule code.
3. **B7 · statements.** Any billing document that bills charges with its own number is an invoice for every
   class. Summary-only statements of account stay out of QS double counting.
4. **B8 · Judge with context.**
   - Accessorial conditions go to the Judge with the condition's clause text **and** the shipment's documents
     (AWB, DG declaration, tracking).
   - Unknown or API error means **no overcharge** (a wrong dispute costs double).
   - Derive the dry-ice and DG rule from the contract clause through the Judge. Remove the `UN1845` literal from
     rule code.
5. **M5 · conflicts.**
   - Match rate-notice bands to contract bands by numeric limits.
   - Treat any listed unranked pair as unranked.
   - Normalise precedence `use` values.
   - A later signed amendment beats feedback.
6. **Scan evidence.** Save the scan transcription with the document's facts, so scan findings carry evidence.
7. **Finish B1 from task 09.**
   - The open-conflict check covers any open conflict on the **same contract and lane (and the same rate
     period)**, not just the same invoice (GLOSSARY, unattended-action test, check 2).
   - The pickup-source check (tracking or a carrier pickup email) applies to every class that relies on a pickup
     date, not only overcharge.
   - Add an eval: a clean dispute on a lane that has an open conflict on another invoice must be `human_review`
     in autonomous mode.

## Done when
Gates hold and the new evals pass. Show the outputs and one line per item.