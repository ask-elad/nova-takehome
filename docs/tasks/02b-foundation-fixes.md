# Task 02b · Fixes from the review of task 02

**Phase:** 2 · **Follows:** `docs/tasks/02-foundation.md`

## Why
Review of task 02 found that model fallback never fires against the real SDK, and that the model client is
missing things task 03 depends on. Each fix below starts with a test that fails today.

## Fixes

**1. Fallback by exception type, not by message text.** (`nova/llm.py`)
With `anthropic==1.8.0`, an unknown model raises `anthropic.NotFoundError` whose message reads
`Error code: 404 - {... 'not_found_error', 'message': 'model: <id>'}`. It contains neither "model not found" nor
"model_not_found", so today's fallback never triggers. The fake client hides this by raising a `ValueError` with
the matching words.
- Catch `anthropic.NotFoundError` for fallback.
- Each tier is an ordered list of model ids. The env vars take comma-separated lists. Try the rest of the tier
  first, then the next tier up.
- Defaults come from `docs/research/models.txt`, the model ids our key serves. For each tier, list the newest
  matching model first (Haiku for fast, Sonnet for main, Opus for strong), then the older ones as fallbacks. Use
  only ids that appear in that file. If the file is missing, stop and say so.

**2. Retries by exception type.** Retry `RateLimitError`, `OverloadedError`, `InternalServerError`,
`APIConnectionError` and `APITimeoutError` with exponential backoff. Re-raise everything else at once. Don't
match on message text.

**3. A `system` argument and a complete cache key.** `call()` takes `system` (the untrusted-data instructions in
0001 live there) and `max_tokens`. The cache key includes model, prompt version, system, messages, schema and
max_tokens. Changing any one of them must miss the cache.

**4. Truncated output is an error, never a result.** If `stop_reason == "max_tokens"`, raise `TruncatedOutput`.
Don't cache it.

**5. Safe under the thread pool.** Cache writes are atomic (temp file, then rename). Ledger appends hold a lock.

**6. Don't drop documents silently.** (`nova/mailbox.py`)
- Today an attachment that isn't `.pdf`/`.xlsx`, or that fails to parse, disappears.
- Instead, keep a record with `ext`, empty `pages` and `unreadable: true`, and print one line to stderr.
- Image attachments (`png`, `jpg`, `jpeg`, `tif`, `tiff`) get `is_scan: true` so the vision reader in task 03
  can pick them up.

**7. No key anywhere in the repo.** `make validate` scans every file in the repo folder, ignored files
included. The harness reads `ANTHROPIC_API_KEY` from the environment only. Don't add `.env` loading, and don't
write the key to any file, log or ledger.

## Tests (write them first)
- **The real SDK error path, with no network:** build `anthropic.Anthropic(api_key="x", max_retries=0,
  http_client=httpx2.Client(transport=httpx2.MockTransport(...)))`. Note that this SDK version uses `httpx2`. Make
  it return 404 `not_found_error` for the first model and a valid `tool_use` response for the second. Assert that
  fallback happens and that the ledger names the second model. The `LLMClient` needs a way to accept an injected
  SDK client for this.
- A 429 followed by success retries, then returns.
- A 400 is raised immediately, with no retry.
- A changed `system`, schema or `max_tokens` misses the cache.
- A `stop_reason` of `max_tokens` raises and writes no cache file.
- An unknown attachment type produces an `unreadable` record, not a missing one.
- Delete the `ValueError("model not found")` path from the fake client so no test depends on it.

## Done when
`.venv/bin/python -m pytest harness/tests -q` is green, and `make grade` still runs end to end. Show both outputs.