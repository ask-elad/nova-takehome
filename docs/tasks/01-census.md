# Task 01 · Census of the mailboxes (read-only)

**Phase:** 1

## Why
Before we choose an architecture, we need to know what the harness will actually have to read. Your job is to
describe the data, not to design anything. Report facts, quote examples, and don't recommend an architecture.

## Rules
- Read-only. Write nothing under `harness/`.
- You may write one helper script, `scripts/dump_text.py`. It runs `grader/extract.py` over a mailbox and writes each
  document's pages as text to `out/text/<mailbox>/...`. Reuse the functions in `grader/extract.py`; don't
  reimplement them.
- Use subagents in parallel for the three reading jobs below. Each writes its own file.
- If you hit a design question, don't answer it: add it to the open questions in `00-summary.md`.

## Reading jobs
**A · Document census** → `docs/research/01-documents.md`
For `data/scenarios/` and `data/exam/`: every kind of document (MSA, amendment, rate notice, invoice, credit note,
statement, tracking export, AWB, payment ledger or AP register, email kinds such as waiver, pickup or extension), with
a count per mailbox and one short real excerpt of each. Then list:
- what differs in layout or wording between the practice carrier and the exam carrier;
- emails that address "the AI" or try to give instructions;
- documents with no text layer;
- INR invoices and the currencies used.

**B · Extractor behaviour** → `docs/research/02-extract.md`
What `grader/extract.py` returns for each kind of document: line order in invoice tables, how annex tables come out,
Excel rows, email headers. Note anything that would trip up quoting, such as wrapped lines, merged columns or
reordered cells. Check what happens with the scanned PDF.

**C · Rules in the worked examples** → `docs/research/03-rules.md`
For each folder in `data/examples/`: the deciding clause, the inputs the arithmetic needs, the steps, and the
look-alike that is *not* a finding and why. Then list every variant code in `data/scenarios/answers/` (OC-01,
OC-02, ...) with a one-line description of what that variant tests. Describe the rule each one tests, not the
answer.

## Done when
The three files exist, each under about 400 lines, with real excerpts and file paths.
Finish with `docs/research/00-summary.md`: one page covering the ten things most likely to make or break the
harness, and the open questions you couldn't answer from the data. Then tick the Phase 1 checklist in `docs/PLAN.md`.