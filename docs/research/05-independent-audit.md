### Blockers

**B1. Autonomous mode never holds back. ✓ reproduced**

- **Where:** `harness/harness.py:315` calls `apply_policy(xs, mode=mode)` with no flags. `policy.py:304,366` then defaults every item to “all five checks pass”, so `ItemFlags` is never filled in.
- **Breaks:** an invoice under $5k where the pickup date came from the AWB or the invoice (no tracking export, no “picked up” email) returns `execute:dispute`. So does a finding on a lane with an open conflict, and one that relies on feedback or quoted text. Three such cases trigger the cap.
- **Violates:** the unattended-action test, checks 1, 2 and 5, and the “3+ unsafe outbound actions” cap.
- **Fix:** have each rule emit the pickup-date source, authority levels, open conflicts per contract/lane/period, and recipient origin, then pass a real `flags_map`. Add an eval where a $200 dispute must be `human_review`.

**B2. A waiver that names no shipment or month is applied to every invoice. ✓ reproduced**

- **Where:** `rules/waived_but_billed.py:131-136` and `case.py:701-707` skip the AWB and month filters when those fields are empty. `w.invoice` is never checked. `_condition_met` (`:44-54`) always returns True.
- **Breaks:** “We’ll waive the delivery fee this one time” made the fixture’s later invoice `TX-US-2034-5561` a finding as well. The same key was also emitted twice, with no merge.
- **Violates:** the glossary’s waiver rule (it must name the shipment or the month, and its conditions must be met), and the “one-off waiver treated as permanent” cap.
- **Fix:** a waiver with no AWB, invoice or month is not a finding; match `w.invoice`; evaluate conditions with the Judge and the document; merge candidates per key.

**B3. One unreadable date or amount crashes the whole report. ✓ reproduced**

- **Where:**&#x20;
  - `verify.py:59-74` only accepts ISO, DD/MM/YYYY and “17 July 2030”-style dates.
  - `readers/__init__.py:117` blanks failed values to `""`.
  - The date parsers in `case.py:749`, `cashback.py:41`, `late_fees.py:29,147-161` and `expiry.py:269` have no error handling.
  - `harness.py:306-321` doesn’t catch errors around the rules.
- **Breaks:**&#x20;
  - An invoice printing `03/04/2031` (US order) or `Mar 4, 2031` has its correct date blanked, and `_quarter_of("")` raises, so the batch’s report exits 1 and every item is lost.
  - Worse, the verifier accepts the wrong reading of a US date (2031-04-03 passes; 2031-03-04 fails).
  - A `DD/MM` tracking date crashed overcharge.
  - Ledger amounts with commas or “$” make `Decimal()` raise.
- **Violates:** the brief’s “new invoice layouts”, and “a report for every batch”.
- **Fix:** normalize dates and numbers in one tolerant parser, keep unverified values as low-confidence (never `""`), and run each rule and each document inside try/except so one bad fact drops one item, not the batch.

**B4. Two feedback kinds are implemented wrong (most of the 10 learning points).**

- **`one_off_approval` is inverted.** `feedback.py:190-204` turns the key into `no_finding`. Read with `reject` (`fb-02-05`) and the cap wording (“applying it to April”), it means the waiver *does* cover that key, so it becomes a finding with `learned_at`. Your own `evals/cases/waiver_one_off_next_month.yaml` encodes the inverted reading. It also matches months by searching quote text for “2033-06” (`:222-228`), and it can’t create a key the rules didn’t already produce.
- **`confirm` + `sender_authority` never matches.** `feedback.py:347-348` stores `subject.person` (a name) as `email`. `case.py:597` compares it with an email address, so a `cannot_determine` never becomes a finding.
- **Fix:** approval makes that key a finding, and only that key. Resolve the person’s name to addresses through the From display names of held emails. Confirm the approval reading by replying to the brief email.

**B5. `retro` is never emitted, and expiry ignores amendments and extensions.**

- **Where:** nothing in `harness/` writes `retro`, and `expiry.py:286-289` skips amendments.
- **Breaks:** the hidden backdated amendment creates a new overcharge key without `retro: true`, failing the adaptation check. A signed extension never moves or removes the expiry alert, so the stale alert stays.
- **Violates:** the glossary’s `supersedes`/`retro` section, and “an extension that arrives moves the date, and can take the alert away”.
- **Fix:** set `retro` when a key’s deciding document is dated or effective before an earlier report but was received after it. Layer amendments’ `end_date` and renewal terms into `operative_date`.

**B6. Pickup dates depend on the practice tracking format. ✓ reproduced**

- **Where:**&#x20;
  - `case.py:513` matches only the exact string `event == "PICKED_UP"` and ignores the `pickup_date` column the sheet map already offers.
  - `readers/sheet.py:101` only sees the first 4 lines.
  - `sheets.py:302-304` drops every row if one mapped label differs.
- **Breaks:** a new carrier’s export saying “Picked up” silently fell back to the invoice date (the lowest-ranked source), so the wrong rate period or fuel month is used, and B1 then executes it. A title block above the header loses all rows.
- **Violates:** the glossary’s pickup-date order.
- **Fix:** have the sheet reader map event values (“which value means picked up”) and support a wide-format pickup column. Scan more rows for the header, tolerate partial mapping, and normalize AWBs.

**B7. Statements are excluded from four of the six classes.**

- **Where:** `kind != "invoice"` filters in `overcharge.py:428`, `waived_but_billed.py:115`, `duplicate.py:162` and `late_fees.py:119,212`.
- **Breaks:** the glossary’s own examples key waivers on `TX-ST-204010`, a statement. A waived charge on a monthly Excel statement is never found. The exam’s “Charges advice” layout is read as statement or invoice inconsistently, as `duplicate.py:82-84` admits.
- **Violates:** “a monthly Excel statement that carries its own number counts as an invoice”.
- **Fix:** treat any billing document that bills charges as an invoice. Keep “statement of account” summaries separate (see M10).

**B8. Conditional accessorials are decided without the document; dry ice is hardcoded.**

- **Where:**&#x20;
  - `overcharge.py:228-232` calls the Judge with no document. `harness.py:436-438` then sends `doc="unknown"` and an empty page, with the question id itself as the question.
  - `case.py:557` and `overcharge.py:209-213` treat a UN1845-only shipment as “DG fee not owed”, whatever the contract says.
- **Breaks:** a “residential delivery” or “tail-lift” fee gets a guessed verdict. A false “not met”, or an unparseable answer (returns False), flags the full fee, and wrong disputes cost 2×. A contract that charges DG on dry ice gets a false overcharge on every dry-ice shipment. An API error inside the Judge also crashes the report, since only `NotImplementedError`/`KeyError` are caught.
- **Violates:** “the contract’s definition is the one to follow”.
- **Fix:** pass the condition’s clause plus the shipment documents (AWB, declaration, tracking) to the Judge. Default to no overcharge when unknown. Derive the DG rule from the clause.

### Major

**M1. Confidence is a constant.** `harness.py:500` calls `conf_score(item.verdict)` only, so every finding is 0.95, conflicts 0.6 and `cannot_determine` 0.5 (`confidence.py`’s signals are never passed). AUROC is about 0.5 and Brier tracks raw accuracy, putting most of the 5 confidence points at risk. Fix: pass the pickup source, re-read, authority, Judge use and INR signals that already exist.

**M2. Authority comes from the model’s chosen line, not the parsed `From` header.**

- **Where:** `case.py:450,683`, `waived_but_billed.py:86` and `late_fees.py:46` use `em.email.sender.value`. The parsed `DocRecord.sender_addr` is saved but never used. The `addresses_automation` and `gives_orders` flags are never read.
- **Breaks:** an email whose body contains `From: <Schedule 1 address>`, as in a forward or a forged block, can be cited as the sender, and verification passes because the text is on that line. Separately, `own_lines=[]` makes quoted text count as own text (`waived_but_billed.py:31-32`, `case.py:693`).
- **Violates:** the glossary’s levels 4 and 5 (quoted or forwarded text, text aimed at automated readers), and the architecture decision’s “From matched exactly”.
- **Fix:** take the sender from the header, drop facts on lines flagged as addressing automation or giving orders, and treat “no own lines” as quoted.

**M3. Documents are silently dropped.**

- **Where:** `classify.py:235` sends rate notices, notices and letters to `other`, which `harness.py:52` skips. Image attachments (png/jpg) are never read (`harness.py:73-75`). A scan is always read as an invoice (`scan.py:208`).
- **Breaks:** a signed rate notice attached as a PDF never creates the expected conflict, and an extension letter never moves the date.
- **Fix:** route notices and letters to the email or contract readers, read images with vision, and classify scans after transcription.

**M4. Grader robustness: model fallback, timeouts and lost documents.**

- **Where:** `llm.py:346` only falls back on a 404. `llm.py:317` keeps the SDK defaults (600 s read timeout, 2 retries) on top of 5 more retries, with no overall deadline. `harness.py:126,241-243` only re-reads the current batch and swallows errors.
- **Breaks:** a key without access to a model returns 403 (PermissionDenied), so every document fails and ingest still exits 0 with an empty report. One stalled call can exceed the 600-second step limit, and documents from a timed-out ingest are never retried.
- **Fix:** fall back on 403 and model-unavailable 400 too, set `timeout≈90s` and `max_retries` low, enforce a deadline of about 540 s per step, and re-attempt documents that have no saved facts on each ingest.

**M5. Conflicts are detected only in one narrow form.**

- **Where:** `overcharge.py:166` requires the rate notice’s band label to equal the contract’s band label exactly (“45–99.9 kg” ≠ “45-99.9kg”). `:595-602` only treats the pair `{rate_notice, amendment}` as unranked. `:581-583` only understands `use == "amendment" | "rate_notice"` (not “rate notice”), and a later signed amendment doesn’t beat feedback.
- **Fix:** match bands by their numeric limits, handle any unranked pair, normalize `use` values, and check for later signed documents.

**M6. `cannot_determine` coverage and holders.**

- **Where:**&#x20;
  - Only three paths exist: an amendment rate reference, Annex F, and quoted waivers. `refers_to` (documents a held document names) is unused, and late-fee or payment-terms gaps are skipped silently (`late_fees.py:143-152`).
  - The quoted-waiver holder is the first “notices” contact of either party (`waived_but_billed.py:200-208`), not the sender (if they’re on Schedule 1) or the issuer’s Key Account Manager.
  - Quoted waivers fan out to every contract and ignore the month (`:102,186-196`), producing false `cannot_determine` items that cut conflict precision.
  - The treasury and rates holders are the first matching row of either party (`case.py:735-742`).
- **Fix:** derive `cannot_determine` from `refers_to`, apply the glossary’s holder rule with the issuing party, and scope quoted waivers like own-text ones.

**M7. Duplicates.**

- `duplicate.py:186` needs exactly the same amount, so a rebill months later at a new fuel rate is missed.
- `:204` adds negative credit-note amounts, which doubles the overlap; credit notes without AWB lines are ignored.
- `:116-118` treats any non-empty paid date (“n/a”, “—”) as paid, creating a false duplicate.
- Invoice ids are joined unnormalized (`:90`, `late_fees.py:62`, `feedback.py:119`).
- **Fix:** match on AWB, charge and quantity, take the absolute value of credits and link them to the invoice they credit, parse the ledger status by meaning, and normalize ids as the glossary does.

**M8. Late fees.**

- Risk principal is the invoice total. Disputed amounts aren’t subtracted; it’s still a TODO (`late_fees.py:231-232`).
- Risk ignores authorised due-date extensions (`:214-218`) and skips invoices without a printed due date instead of deriving it from payment terms.
- Not-owed base never removes paid fees or disputed amounts (`:160-166`).
- The rate, grace and compounding come from the main contract only, so amendments are ignored.
- The ledger parsing is tuned to the practice ledger: it strips “due”, “USD” and “INR” (`:147-149`).

**M9. Overcharge gaps.**

- Charges missing from the contract are never flagged (`:245-247`).
- `pct_of_freight`, per-day (storage “4 days”) and `other` bases are never repriced (`:255-268`).
- Credit notes that cancel a charge are ignored, a listed near-miss that costs 2×.
- Lines without a per-line lane, or with lane formatting that differs, aren’t priced (`:316`, `Terms.rate_rows_for`).
- The ship date printed in the invoice header isn’t used as the last fallback.

**M10. Cashback.**

- `margin_step_down` is never computed, though the schema reads it (`cashback.py:286-337`).
- Qualifying spend is total minus exclusions, ignoring `qs_includes`, and includes tax shown only in the summary (`:115-122`).
- Statements of account are counted on top of their invoices (`:207,216`).
- Credits already issued only match exact `credit_type` and `period` strings (“2035-Q1”, “improvement”; `:179-183,326`), so “Q1 2035” or an early-issued credit gives a false finding.
- Negative credit totals flip sign.

**M11. Feedback plumbing.**

- `harness.py:529-530` stores items without their header (envelope), so `learned_at.batch` is null (the schema requires a string) and `decided_at` is lost.
- `harness.py:355-364` attributes pre-rules changes to the *first* standing feedback item, so with several items the wrong `feedback_item_id` is cited.
- Authority windows are checked against `as_of`, not the document or shipment date (`waived_but_billed.py:94`).

### Minor

- **INR rounding:** INR is converted on billed and correct separately, then subtracted (`overcharge.py:495-497`, `late_fees.py:179-180`), which can drift 1 cent. Convert the delta once.
- **Scan evidence:** the scan transcription isn’t saved, so evidence on the exam scan is dropped (`harness.py:225`) and that finding gets half detection credit.
- **Other currencies:** non-INR, non-USD amounts are reported as USD without conversion (`overcharge.py:487`).
- **`supersedes`:** new items reuse the old id; the architecture decision said versioned ids.
- **Missing `Date` header:** an `.eml` without one crashes the whole ingest (`mailbox.py:83`).
- **Process:** PLAN marks Task 08 done, but `autonomous_over_threshold.yaml` doesn’t exist and GITLOG has no Task 08 commit.
- **Local paths in repo:** `.claude/settings.local.json` isn’t gitignored and contains local paths.

### Checked and sound

- **Supervised mode:** no path emits `execute:*`. Every branch in `_compute_action` returns draft, internal, `human_review` or `escalate`.
- **$5,000 rule:** summed per invoice or cashback key across classes, with exactly $5,000.00 included.
- **Escalation rate:** 4% in practice, since only conflicts and findings of $5,000+ escalate. Recheck after fixing B1.
- **Grader environment:** a fresh state dir, an environment with only `PATH` and the key, an empty batch, and a report on empty state all give a valid empty report (tested).
- **Unreadable attachments:** flagged and skipped, not fatal.
- **`as_of`:** filters on the UTC `Date` header.
- **Arithmetic:**&#x20;
  - Half-up rounding on Decimal is correct.
  - INR uses the invoice month, and a missing Annex F row gives `cannot_determine`.
  - Late-fee grace, months rounded up from days/30, compounding, and the 0–14 day risk window are correct.
  - Expiry’s 0–60 day window and notice-deadline subtraction are correct.
- **Duplicates:** the later invoice date is flagged; credited in full then rebilled is fine; house AWBs stay distinct.
- **Cashback basics:** reported only after the period closes; track vs claim by due date; whole and marginal tiers.
- **Quotes:** copied from the grader’s text layer, at least 12 characters.
- **Prompt-injection defences:** one document per call, untrusted-data system prompt, no tools that act. Recipients aren’t emitted, so the injection cap’s address check can’t fire.
- **Secrets:** none in the repo, `ai_log/` or the cache/ledger. The key is read only by the SDK from the environment and never written. The logs show only `<your-key>` placeholders and local home paths.
- **Hardcoded values:** no practice answers, ids, names or lanes in code. The literals are `PICKED_UP`, `UN1845` and the ledger tokens noted above, plus exam examples inside reader prompts.