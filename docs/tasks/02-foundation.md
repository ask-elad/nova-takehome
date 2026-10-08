# Task 02 · Foundation: text layer, mailbox, model client, runnable pipeline

**Phase:** 2 (first half) · **Follows:** `docs/decisions/0001-architecture.md`

## Why
Everything later stands on four things: the same text the grader sees, the correct document ids and received
dates, one model client that is cached and logged, and a pipeline that runs end to end. No document reading
by the model yet. That's task 03.

## Build
1. **`harness/nova/textlayer.py`**: a verbatim copy of `grader/extract.py`, with a header comment saying where it
   came from and why it's copied. Don't change its logic.
2. **`harness/nova/mailbox.py`**: reads a batch folder into document records.
   - Doc ids follow the grader's convention: `batch_01/0003.eml` for the email, `batch_01/0003.eml#NAME.pdf` for
     an attachment.
   - Each record holds: `received` (the email's `Date` header in UTC; attachments inherit it), sender address and
     display name, subject, pages of text, `is_scan`, and the parent email id.
   - A helper renders pages with line labels (`[p1 L7] ...`) for prompts.
   - A helper resolves a `(page, line)` or a line range back to the exact text, for use as a quote.
3. **`harness/nova/llm.py`**: the only place that calls the Anthropic API.
   - Three tiers from env vars (`NOVA_MODEL_FAST`, `NOVA_MODEL_MAIN`, `NOVA_MODEL_STRONG`, defaults as in 0001),
     falling back to the next model if one isn't available.
   - Temperature 0. Output through a forced tool call with a JSON schema.
   - Retries on rate limits and overload, and a small thread-pool helper.
   - Disk cache keyed by (model, prompt version, content hash).
   - Every call, cached or not, appends a line to `<state>/ledger.jsonl`: time, purpose, model, input and output
     tokens, and whether it was cached.
   - A fake client (selected by `NOVA_LLM=fake`) returns canned responses, so tests never touch the network.
4. **`harness/nova/state.py`**: the state folder layout from 0001, with atomic JSON writes.
5. **Wire `harness/harness.py`** (keep the CLI exactly as it is):
   - `ingest` saves one record per document. Re-ingesting the same batch must not create duplicates.
   - `report` prints a schema-valid report with empty findings and portfolio.
   - `feedback` stores the file's items in `feedback.jsonl`.

## Tests (write them first) in `harness/tests/`
- `textlayer` output is identical to `grader/extract.py` for every document in `data/examples`,
  `data/scenarios` and `data/exam`.
- For every `expected_finding.json` in `data/examples/`: each evidence `doc` id exists in our mailbox records, and
  each quote is found by `textlayer.found()` on the cited page of our pages.
- Received dates: a document dated after `as_of` is excluded (a small handmade case is fine).
- The line resolver round-trips: the resolved text of any line is found on its page.
- `llm`: a second identical call is served from cache, both calls land in the ledger, and the fallback goes to
  the next model when the first raises "model not found". Use the fake client.
- `report` output validates against `grader/schema/report.schema.json`.

## Don't
- Don't call the real API in tests.
- Don't write any readers, rules or prompts for documents. That's task 03.
- Don't edit anything listed as off-limits in `CLAUDE.md`.

## Done when
- `.venv/bin/python -m pytest harness/tests -q` is green.
- `make grade` runs end to end without errors. The score will be near zero, and that's expected.
- Show both outputs. Then tick Phase 2 · task 02 in `docs/PLAN.md`.