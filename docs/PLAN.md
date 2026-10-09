# Plan

Read this at the start of every session. It says where the project stands and what you're working on now.
The humans keep it up to date. You may tick the items of the task you finish; the gates and everything else are
changed by the humans only.

## Where we are

**Phases 4–5 · Pipeline and policy.** Readers are done (05a): rules on reader facts reproduce all eight examples.
Current task: `docs/tasks/06-pipeline-and-policy.md` (it replaces 05b). It uses the real API: follow the key and
cost rules in `docs/tasks/05a-readers.md`.

## How work reaches you

- Each task is a file in `docs/tasks/`. It says what to do, what not to touch, and when it's done. Do that task and
  nothing beyond it.
- Design decisions live in `docs/decisions/`. Follow them. If a task can't be done without changing one, stop and
  explain why instead of working around it.
- A task is done when its "done when" check passes. End by showing the command you ran and its output.
- Tests come first: write the test from `GLOSSARY.md` or the worked example, watch it fail, then write the code.
- Tests never call the real API. Real model calls happen only in the runs a task asks for.

## Phases

Each phase ends with a gate. The next phase starts only after the gate has passed.
The rules engine is built before the readers: it's proven on hand-written facts first, and the readers then have
to produce the same facts.

| # | Phase | Gate |
|---|---|---|
| 0 | Workspace: repo, `CLAUDE.md`, this plan | done |
| 1 | Census, then the architecture decision | done: `docs/decisions/0001-architecture.md` |
| 2 | Foundation, then the typed schemas for what each reader returns | done |
| 3 | Rules engine on hand-written facts, one class at a time | done |
| 4 | Readers (the model fills the schemas) | done: rules on reader facts reproduce all eight examples |
| 5 | Verdicts, actions, modes, confidence | invariant tests for the five score-capping mistakes pass |
| 6 | New documents and feedback | one test per feedback kind, plus tests that feedback doesn't spread |
| 7 | Our own eval set, exam run | `make eval` green; answer sheet checked against the documents |
| 8 | Write-up and submission | `make validate` green |

## Phase 1 checklist
- [x] `docs/research/01-documents.md`, `02-extract.md`, `03-rules.md`, `00-summary.md`
- [x] `docs/research/04-review.md` (human review of the census)
- [x] `docs/decisions/0001-architecture.md` accepted

## Phase 2 checklist
- [x] Task 02 · foundation: text layer, mailbox, model client, runnable pipeline
- [x] Task 02b · fixes from review: real-SDK fallback and retries, system prompt, full cache key, truncation,
      no silently dropped documents
- [x] Task 03a · reader schemas (no prompts, no API calls)
- [x] Task 03a2 · fixes from review: whole-token number matching, typed fields for the rules engine

## Phase 3 checklist
- [x] Task 04 · money, case model, overcharge, resolve; overcharge golden test green
- [x] Task 04a2 · fixes from review: sheet parsing in production, terms in force, overcharge gaps, received_at
- [x] Task 04b · duplicate, waived_but_billed, late fees, expiry
- [x] Task 04c · cashback, conflict, cannot_determine; all eight golden tests green

## Phase 4 checklist
- [x] Task 05a · readers, verification, typed unranked pairs; rules on reader facts reproduce all eight examples
- [x] Task 06 · cost fixes, ingest and report end to end, policy layer (actions, modes, $5k, confidence); first real `make grade` score