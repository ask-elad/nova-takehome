# Plan

Read this at the start of every session. It says where the project stands and what you're working on now.
The humans keep it up to date. You may tick the items of the task you finish; the gates and everything else are
changed by the humans only.

## Where we are

**Phase 2 · Reading layer.** The architecture is decided: `docs/decisions/0001-architecture.md`. Current task:
`docs/tasks/02-foundation.md`.

## How work reaches you

- Each task is a file in `docs/tasks/`. It says what to do, what not to touch, and when it's done. Do that task and
  nothing beyond it.
- Design decisions live in `docs/decisions/`. Follow them. If a task can't be done without changing one, stop and
  explain why instead of working around it.
- A task is done when its "done when" check passes. End by showing the command you ran and its output.
- Tests come first: write the test from `GLOSSARY.md` or the worked example, watch it fail, then write the code.

## Phases

Each phase ends with a gate. The next phase starts only after the gate has passed.

| # | Phase | Gate |
|---|---|---|
| 0 | Workspace: repo, `CLAUDE.md`, this plan | done |
| 1 | Census of the mailboxes, then the architecture decision | `docs/decisions/0001-architecture.md` signed off |
| 2 | Reading layer and fact store | every extracted quote is found by `grader/extract.py`; invoice lines reconcile |
| 3 | Rules engine, one class at a time | all eight worked examples pass as tests; first `make grade` score recorded |
| 4 | Verdicts, actions, modes, confidence | invariant tests for the five score-capping mistakes pass |
| 5 | New documents and feedback | one test per feedback kind, plus tests that feedback doesn't spread |
| 6 | Our own eval set, exam run | `make eval` green; answer sheet checked against the documents |
| 7 | Write-up and submission | `make validate` green |

## Phase 1 checklist
- [x] `docs/research/01-documents.md`
- [x] `docs/research/02-extract.md`
- [x] `docs/research/03-rules.md`
- [x] `docs/research/00-summary.md`
- [x] `docs/research/04-review.md` (human review of the census)
- [x] `docs/decisions/0001-architecture.md` signed off

## Phase 2 checklist
- [ ] Task 02 · foundation: text layer, mailbox, model client, runnable pipeline
- [ ] Task 03 · readers and verification