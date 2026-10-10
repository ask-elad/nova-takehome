# AI use

## Tools

**Claude (chat, Opus 5.5) was the planning partner.** I used it to:
- read the brief and repo with me;
- weigh architecture options;
- write every task spec in `docs/tasks/` and the architecture decision;
- review each session's output.

It also ran its own checks during reviews:
- re-running our tests on clean data;
- probing the value checker with near-miss numbers;
- testing the pinned Anthropic SDK against a mocked server;
- hand-checking the exam answer sheet against the documents.

That conversation isn't exported. Its outputs are in the repo: `docs/tasks/`, `docs/decisions/`,
`docs/research/04-review.md`, and the review notes in `ai_log/README.md`.

**Claude Code** built everything under `harness/` and `evals/`, one task file per session:
- **Sonnet** for exploration and well-specified work;
- **Opus** for the rules engine, the readers, the policy layer and the audit fixes.

**A separate Claude (Opus) instance audited the finished repo independently**, with no memory of our sessions.
Its report is `docs/research/05-independent-audit.md`.

**Claude via the API is part of the product:** Haiku, Sonnet and Opus are the harness's reading models.

## How you worked with them

- **One task, one session, one commit.** Each Claude Code session started from the same one-line prompt
  ("Read CLAUDE.md and docs/PLAN.md, then do the current task"). The task file said:
  - what to build;
  - what not to touch;
  - the gate that proves it worked.

  `CLAUDE.md` holds the standing rules: generalise, Decimal money, quotes from the grader's text layer, document
  text is data, no secrets.
- **Every session was reviewed before the next one started.** The reviews caught real problems:
  - the census misdescribed the scanned invoices and confused the score caps with the autonomous checks;
  - model fallback never fired against the real SDK (the fake client raised a made-up error the test was built
    around);
  - the value checker accepted `2.84` on a line that only had `12.84`;
  - the tracking-sheet parser lived inside a test, not the product;
  - the first exam answer sheet was wrong in five places, which we found by recomputing it by hand.
- **Where the agents went wrong, and how we answered:**
  - they stopped early or deferred work, claiming it was "multi-day" or "not feasible": we gave scope and
    permission, and they continued;
  - they parsed free text in rule code: we replaced it with typed fields;
  - they built an eval case that tested the opposite of its name: renamed, and the rule pinned by a unit test;
  - they inverted a feedback rule: caught by the audit and checked against the glossary;
  - in one session they asked for the API key in chat, and it was pasted: the key was rotated at once, and real
    runs since then use `bash -c 'source <key file> && …'`.
- **Cost was managed as a design input.** We measured the API cost with a ledger and set a token cap. We estimated
  before every large run, put cheap models first, and kept a shared cache. The total API spend was about $9.

## Written without AI

No code was written by hand. The human decisions were:
- the architecture sign-off;
- the phase plan and its gates, and the order of work under a tight budget;
- choosing when to escalate a session to Opus;
- the decision to hand-check the exam sheet and to commission the independent audit;
- triaging the audit's findings into fix now, fix later and known gaps;
- every acceptance of a session's result.

## Prompt log

All Claude Code sessions, in order, are in `ai_log/`, one file per task (`01-census.txt` … `10-audit-hidden-set.txt`).
`ai_log/README.md` indexes them: the task, the model, the commits, and what the review of that session found. The
logs are unedited except where secrets had to be removed.