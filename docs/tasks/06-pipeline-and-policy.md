# Task 06 · End-to-end pipeline, policy layer, first real score

**Phases:** 4 (end) and 5 · Replaces `05b-pipeline.md` (merged into this task)
**Key and cost rules from `05a-readers.md` still apply.** Commit after each part goes green.

## Budget: about $1.20 of API credit is left, and there will be no top-up
The money goes to the **exam answer sheet first** (pass/fail), then the practice grade. Every real run below
follows these rules:
- `NOVA_MODEL_STRONG` is set to the main-tier list for our runs, so nothing escalates to Opus.
- **Estimate before you spend:** a `--estimate` flag on `ingest` counts each mailbox's documents by type and
  multiplies by the average paid tokens per document type from the 05a ledger. It prints projected input and
  output tokens and calls no model.
- **A hard stop:** `NOVA_MAX_PAID_TOKENS` (input + output, unset means no limit). The client raises before a call
  that would push the ledger's paid total past it. Our runs set it.
- Run order: estimate both mailboxes, then **show the estimate and stop for the human's go-ahead**. After that,
  `make sheet` (exam), then `make grade`. With the shared cache, the second mode costs nothing extra.
- Only the parts of this task marked "real run" may call the API. Everything else uses the fake client.

## Part A · Cost fixes first (before any big run)
1. **Shared cache.** `NOVA_CACHE_DIR` (an absolute path) overrides the cache location. Default: inside the state
   dir. The grader gives each mode a fresh state dir and its own `HOME`, so our runs must use
   `NOVA_CACHE_DIR=/home/askeladd/.nova-cache` (an absolute path, never `~`) to share calls between modes and
   re-runs.
2. **Contracts must pass on the first read.** Every contract in 05a failed verification on the main tier and was
   re-read on the strong tier. Use the `verify_failures` already stored from 05a to find which fields fail, and
   fix the prompt or the schema description. Don't re-run the eight examples to check this, because it costs
   money: test the fix offline against the stored responses and failures. The exam and practice runs will show
   whether it holds.

## Part B · Pipeline (from 05b)
3. **`ingest`:** classify, read and verify each new document (thread pool, at most 8 at once), and save its facts
   in the state dir. A document already read is never read again. Print the ledger totals to stderr.
4. **`report`:** load records received by `as_of`; build the `Case` (with the Claude `Judge`); run all rule
   modules, then `resolve`, then the policy layer (Part C); print schema-valid JSON (`findings` and `portfolio`).
5. Every step must stay well inside the grader's 600-second limit.

## Part C · Policy layer (`nova/policy.py`), straight from GLOSSARY.md
6. **Actions per verdict and class.**
   - Use the glossary's actions table.
   - Supervised mode: `draft:*`.
   - Autonomous mode: `execute:*` only when all five unattended-action checks pass, otherwise `human_review`.
   - A conflict is always `escalate`.
   - Check your mapping against `action.supervised` and `action.autonomous` in `data/scenarios/answers/*.yaml`.
     Read them to confirm the rule, never to copy answers.
7. **The $5,000 rule:** sum every outbound finding on the same invoice (or cashback key). At $5,000.00 or more,
   the action is `human_review`, in both modes.
8. **The five checks for acting alone:**
   - evidence complete, pickup date from tracking or a carrier pickup email;
   - no open conflict on the key, or on the same contract and lane;
   - under $5,000;
   - can be undone;
   - every term at authority level 1–2 and every fact at level 3 or better, with recipients from Schedule 1.
9. **Confidence** (`nova/confidence.py`):
   - start from 0.95;
   - lower it for each weaker signal: pickup date not from tracking, a value that needed a re-read, a term below
     authority level 1, a Judge answer in the chain, an INR conversion;
   - floor it at 0.5 for findings, and give conflicts and cannot_determine a fixed lower value.
   - Keep the weights in one table at the top of the file. We tune them in Phase 7.

## Tests (offline, written first)
- **The five score caps as invariants:**
  - no `execute:` in supervised mode, ever;
  - no action is triggered by text that addresses automation;
  - a one-off waiver never covers another month;
  - escalations stay under 60% of reported items on a mixed case;
  - autonomous `execute:` only when all five checks pass (a table of cases, one failing check each).
- **The $5,000 rule:** two findings on one invoice summing past the threshold both become `human_review`.
- `report` output is schema-valid in both modes.

## Done when
1. Offline tests green.
2. **The estimate for both mailboxes is shown, then STOP and wait for the human's go-ahead.**
3. Real runs, after the go-ahead. Use the token cap the human gives, all in one `bash -c 'source ~/.nova-key.env
   && …'`:

   ```
   NOVA_CACHE_DIR=/home/askeladd/.nova-cache NOVA_MODEL_STRONG=<main list> NOVA_MAX_PAID_TOKENS=<cap> make sheet
   NOVA_CACHE_DIR=/home/askeladd/.nova-cache NOVA_MODEL_STRONG=<main list> NOVA_MAX_PAID_TOKENS=<cap> make grade
   ```

   Commit `answer_sheet.json` and `out/exam_report.json` straight after `make sheet`.

`make grade` runs end to end in both modes. Show:
- the score and each component's points;
- the `missed`, `false` and `wrong_amounts` lists, and the actions marked wrong;
- the ledger summary;
- the time per step.

Commit `report_card.*`. Don't start fixing misses. List them, and stop.