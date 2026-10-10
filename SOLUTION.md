# My solution

## How to run it

```
make setup
export ANTHROPIC_API_KEY=...        # the grader provides this; nothing else is needed
make grade                          # practice mailbox
make sheet                          # exam mailbox
make eval                           # our eval set
.venv/bin/python -m pytest harness/tests -q
```

`make setup` is enough: `harness/requirements.txt` is pinned. The harness reads only `ANTHROPIC_API_KEY` and
`ANTHROPIC_BASE_URL` from the environment.

**Models:** the default tiers are Haiku 5.5, Sonnet 5.5 and Opus 5.5. Each tier falls back to older versions if the
key doesn't serve a model (404, 403, or model-unavailable 400).

**Optional for development only:** a git-ignored `.nova-local.json` at the repo root can set:
- a shared call cache (`cache_dir`);
- a token cap (`max_paid_tokens`);
- model overrides.

The grader passes the harness no other environment variables, which is why these live in a file. Without the file
the harness behaves exactly as graded: the cache sits inside the state dir.

**Time limits:** each step stays inside the grader's 600-second limit, with an internal deadline of about 540 s.
A document left unread is retried on the next ingest.

## What works

**Practice (`report_card.txt`): 99.6 / 100, every hard gate clear.**
- Detection 25/25: 22 hits, 0 false, 0 missed.
- Amounts 20/20: $14,140.09 recovered, $0 wrongly disputed.
- Adaptation 15/15, learning 10/10, conflicts 10/10, clean controls 16/16.
- Gating 14.61/15: 24/24 actions right in both modes, escalation 4%.

The first end-to-end run scored 59.6. The changes between are listed in `ai_log/README.md`.

**Exam (`answer_sheet.json`):**
- total overpayment $3,847.70, cashback owed $4,307.34, late fees avoided $10.29, total savings **$8,165.33**;
- one conflict (CDU-3051302) and one cannot_determine (CDU-3051286, "Annex A rev 2", Joaquin Rathbone).

We checked it by hand against the documents before trusting it: every freight rate, the DG and dry-ice line, the
scanned INR invoice, the qualifying spend per quarter, and the annual credit. The first sheet was wrong in five
places. The harness was fixed generically until it matched the hand check.

**Evals (`evals/results.json`):** 14 of 14 pass, 12 of them ours. They cover:
- prompt injection, a spoofed display name, unauthorised waiver, extension and rate-notice senders;
- a quoted-only waiver, a reworded waiver, a one-off waiver followed by the next month's charge;
- house AWBs under one master, a renamed tracking column, feedback that must not spread, and autonomous execution.

**Unit tests:** rules are written from the glossary, and the eight worked examples are golden tests on hand-written
facts and on Claude-read facts.

## What doesn't

These come from an independent audit (`docs/research/05-independent-audit.md`). Its blockers are fixed; these
remain:
- **Unread documents:** rate notices and letters attached as PDFs are classified as "other" and not read. Image
  attachments other than scanned PDFs aren't read either.
- **cannot_determine:** comes from three paths only (an amendment pointing to an unheld annex, a missing Annex F
  month, a quoted-only waiver). It isn't raised for every document a held document names.
- **Duplicates:** need the same amount, so a rebill at a changed fuel rate is missed. Credit notes are matched by
  exact type and period strings.
- **Late-fee risk:** uses the invoice total and doesn't subtract amounts we're already disputing.
- **Margin step-down:** not computed.
- **Confidence:** the weights are hand-set. Practice has no wrong items, so ranking quality (AUROC) is untested.
- **Our own hand check:** the exam numbers match it, but it checked every freight rate and special case, not every
  security or delivery line.

## The eval case that caught a bug

`evals/cases/sample_conflict.yaml` started failing after task 07: range `[0.00, 0.00]` instead of
`[0.00, 20.87]`. The mailbox and the expected answer hadn't changed, so the bug was ours.

What was happening:
1. The amendment's first read, on the main tier, parsed correctly but failed verification on a few empty payment
   fields.
2. The re-read one tier up omitted those required fields, and Pydantic rejected it.
3. The reader kept only the last attempt, so it **threw away the good first read**.
4. The amendment never reached the rules, so the conflict collapsed into a single source.

The fix keeps the first valid read when a re-read fails to parse. It's pinned by
`test_reread_parse_failure_falls_back_to_first_read`. Details and the deliberate-break demo are in
`evals/DELIBERATE_BREAK.md`.