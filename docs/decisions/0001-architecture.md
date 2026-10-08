# 0001 · Architecture: the model reads, code decides

**Status:** proposed · **Evidence:** `docs/research/00`–`04`

## The decision in one paragraph

Claude reads documents and answers small typed questions about them. Python does everything else: arithmetic,
dates, precedence, authority, verdicts, actions and confidence. Every fact the model returns points to the exact
line it came from, and code copies the quote from that line, so a quote can't be invented. The idea of a model
that returns typed, checkable answers which your own code combines comes from TypeSafe's Jev ("System One")
model. We use the same pattern on Claude, because the grading container can only reach the Anthropic API.

## Why

- Practice and exam invoices share nothing in layout: date formats, labels, column order and number formats all
  differ (`01-documents.md` §2). Rules tuned to the layout break, and the brief says a harness built that way
  scored 11/100 on the hidden set.
- `grader/extract.py` turns every text document into clean lines, one table row per line, for both carriers
  (`02-extract.md`). So the model reads plain text, never raw PDFs.
- The arithmetic and the rules are exact and fully written down in `GLOSSARY.md`. That's work for code, which is
  exact, testable and explainable in a live demo.
- Amounts score "money recovered minus twice anything wrongly disputed", and five mistakes cap the score at 40.
  Both reward deterministic, checkable decisions over fluent ones.

## How it works

```
ingest (per batch, per document)              report --as-of D (whole mailbox)
────────────────────────────────              ─────────────────────────────────
.eml → text pages (extract.py)                load documents received ≤ D
     → classify (fast model)                  build the case model (contracts, shipments,
     → typed reader per document type           invoice lines, payments, authority)
       (main model; vision for scans)         class rules → candidates with every source
     → verify: numbers are on cited lines     policy → verdict, action, mode, confidence
     → save document record (+ cache)         history → supersedes, retro, learned_at
                                              print report.json
feedback <file> → save scoped facts
```

**1. Text layer.** `harness/nova/textlayer.py` is a vendored copy of `grader/extract.py`. A test checks that the
two give identical output on every mailbox. Scans (no text layer) go page by page to Claude vision, which writes
the page out as text lines. From then on a scan is treated like any other document.

**2. Readers, one per document type.** A fast model first sorts each document into a type: contract, amendment,
invoice, credit note, statement, AWB, DG declaration, tracking export, payment register, email, or other. Then a
reader for that type fills a typed schema through tool use:

- *Contract / amendment:* parties, contract id, effective and end dates, renewal and notice terms, rate tables,
  fuel table, accessorials with their conditions, charge-code aliases, rebate tiers and tier rule, margin
  step-down, promised credits, payment terms, grace days, late-fee rate and whether it compounds, precedence and
  unranked instruments, Annex F, Schedule 1, and documents it refers to. Each term carries a line reference, and
  clauses marked "Not applicable" come back as switched off.
- *Invoice / credit note / statement:* header fields and one record per line (AWB, charge label, lane, quantity,
  unit, rate, amount, pickup or collected date), each with its line reference.
- *Email:* atomic questions, such as: Is it a waiver, extension, rate notice, pickup, delivery or customs event?
  Of what, on which AWB, invoice or month? Is a condition attached? Is this the sender's own text or quoted text?
  Does it address an automated reader?
- *Spreadsheet:* the model maps the column headers to our fields once per sheet, then code parses every row.

The model never sees the question "is there an overcharge?". It only reports what a document says.

**3. Verification after every read.** Every number and date the model returns must appear on the line it cites.
Invoice lines must satisfy rate × quantity = amount. If a check fails, the document is read again one model tier
up. If it still fails, the fact is marked low-confidence and any finding built on it goes to a person.

**4. Case model and rules (pure Python).** `report` is a pure function of (documents received by `as_of`,
feedback facts, mode). Nothing is carried over from earlier reports except history (item 7). So `as_of`
filtering, backdated amendments and documents arriving in any order all fall out of recomputation.

- **Rule modules:** one per class (`overcharge`, `duplicate`, `waived_but_billed`, `late_fee`, `cashback`,
  `expiry`). Each returns *candidates*: the key, the billed amount, a correct amount *per source* (with that
  source's authority level and whether it was in force on the pickup date), and the evidence.
- **Cross-document judgement calls:** some calls need a contract clause and another document side by side, such
  as "does the DG fee apply when the declaration says dry ice, refrigerant only?". These are asked at report time
  as atomic yes/no questions with a quote, and cached by their inputs.

**5. Policy (pure Python).** Turns candidates into items, following the glossary:
- precedence first; then conflict (both sources authorised, unranked, different amounts) or cannot_determine (a
  document that a held document names is missing, and it could change the answer), with the holder taken from
  Schedule 1;
- then actions per mode, the five checks for acting alone, and the $5,000 rule summed per invoice or cashback key.

Text addressed to automated readers is stored as level-5 data and can never set a term or an action. No model
call can take an action: the model only fills schemas.

**Prompt injection.** Following an instruction written in a document caps the score at 40, so the defence is
built into the structure rather than bolted on as a filter. Six layers:
1. *Nothing to hijack.* Model calls have no tools that act, only schemas to fill. The action vocabulary is a
   fixed list chosen by code, and paying, accepting terms or confirming a renewal are not in it.
2. *One document per call.* A reader sees a single document, wrapped in delimiters and labelled as untrusted
   data. An email can't steer how a contract or an invoice is read.
3. *Values must be on the page.* Every extracted value must appear on the line it cites (step 3). A document can't
   talk the model into inventing a rate or a date.
4. *Authority comes from structure, not wording.* The sender is the `From` address matched exactly against
   Schedule 1, never the display name or a claim in the body. Quoted or forwarded text is marked as such and is
   level 5 unless we hold the original. Recipients for outbound actions come from Schedule 1 only.
5. *Flagged, then ignored.* Readers answer "does this address an automated reader or try to give orders?" with a
   quote. Flagged text is stored as level 5. It can be cited as a fact, but it never sets a term, a verdict or an
   action.
6. *Tested.* Eval mailboxes with injection emails (a "system" note in an email, a fake Schedule 1 in a body, a
   display-name spoof, a demand to confirm a renewal) must leave the report unchanged.

**6. Confidence.** Computed from signals we already have: the authority level of the weakest term relied on, the
pickup-date source, whether verification passed, which model tier answered, agreement across sources (AWB vs
invoice weight, tracking vs invoice date), and whether the clause was in force on the pickup date. We start with
hand-set weights combined in a logistic function, then check Brier score and AUROC on our evals and the practice
set.

**7. History and learning.** State keeps every report it printed.
- **Supersedes:** if a key's verdict, amount or action differs from the previous report, the new item gets a
  versioned id (`overcharge:INV-1@2`) and `supersedes` points at the old one.
- **Retro:** a key that exists only because of a backdated document gets `retro: true`.
- **Feedback** is stored as scoped facts. Rules run twice, with and without the feedback facts. If the answer for a
  key differs, the item carries `learned_at`. One mechanism, easy to audit, and scope is enforced in one place.

## Models, cost, state

- **Tiers:** fast (`NOVA_MODEL_FAST`, default `claude-haiku-5-5`) for sorting documents and simple email
  questions; main (`NOVA_MODEL_MAIN`, default `claude-sonnet-5-5`) for contracts, invoices, waivers and scans;
  strong (`NOVA_MODEL_STRONG`, default `claude-opus-5-5`) only for re-reading after a failed check.
- **Fallback:** if the grading key doesn't serve a model, we fall back to the next one listed.
- **Every call:** temperature 0, tool-schema output, cached on disk by (model, prompt version, content hash), run
  in a small thread pool, and logged to `state/ledger.jsonl` with its tokens. The cost per 1,000 documents in
  DESIGN.md comes from that ledger.
- **State layout:** `documents/<doc>.json` (record and provenance), `cache/`, `feedback.jsonl`, `reports/`,
  `ledger.jsonl`.

## Code layout

```
harness/harness.py           CLI only (the three commands)
harness/nova/textlayer.py    vendored extract.py
harness/nova/llm.py          client, tiers, fallback, cache, ledger
harness/nova/readers/        classify, contract, invoice, email, sheet, scan, schemas
harness/nova/case.py         case model built from document records, as_of filter
harness/nova/rules/          one module per class
harness/nova/policy.py       verdicts, actions, modes
harness/nova/confidence.py
harness/nova/history.py      supersedes, retro, learned_at, feedback scope
harness/nova/report.py       assemble report.json
harness/tests/
```

## Options we rejected

- **One agent reads the mailbox and writes the report.** Rejected because:
  - quotes and arithmetic can't be checked;
  - results vary from run to run;
  - a mailbox overflows the context window;
  - every email gets a chance to give it orders.
- **Rules and regex, no model.** It doesn't generalise, which is the brief's own 11/100 example.
- **The model judges each candidate finding.** This puts arithmetic and precedence back in the model, where we
  can't test them. We keep the model to reading and to narrow yes/no judgements.
- **Local OCR for scans.** Its output breaks words and spacing into boxes and needs per-layout fixing. Vision is
  one call per scan, and the grader doesn't check quotes on scans.

## What we're least sure about

- **Contract reading** is the largest schema and the most costly mistake. If one read proves unreliable, we split
  it into a few section-level reads.
- **Contract conditions written in prose,** like the dry-ice clause, depend on the judgement calls catching them.
  The hidden set will have conditions we haven't seen.
- **Hand-set confidence weights** may rank items poorly until we have enough eval cases to tune them.