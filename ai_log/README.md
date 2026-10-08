| # | Task | Model | Commit | Notes |
|---|------|-------|--------|-------|
| 01 | docs/tasks/01-census.md | Sonnet | <hash> | census; 3 errors found in review (docs/research/04-review.md) |
| 02 | docs/tasks/02-foundation.md | Sonnet | <hash> | 32 tests green, pipeline runs end to end. Review found: model fallback never fires on the real SDK (fake client raised a made-up error the test was built around); no system prompt; cache key missing the schema; truncated output accepted; unknown attachments dropped; model defaults changed from the decision without a note. All moved to task 02b. |
| 02b | docs/tasks/02b-foundation-fixes.md | Sonnet | <hash> | 40 tests green. Fallback now catches the SDK's NotFoundError, tested against the real SDK with a mocked server; system prompt, full cache key, truncation check, unreadable attachments kept. Model defaults from docs/research/models.txt. |
