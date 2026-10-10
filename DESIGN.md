# Design

The model reads; code decides. Claude turns documents into typed facts, and plain Python does arithmetic, dates,
precedence, verdicts and actions. Typed, checkable model answers combined by our own code is the pattern of
TypeSafe's Jev, built here on Claude. Full decision, and the options we rejected: `docs/decisions/0001-architecture.md`.

## Fact model

- **Text:** a verbatim copy of `grader/extract.py`, so our quotes are the grader's text. Scans go through Claude
  vision.
- **Readers:** one per document type (contract, billing document, email, sheet, shipment, scan), one document per
  call. Each fills a Pydantic schema through a forced tool call.
- **Provenance:** every value carries a `{page, line}` reference. The model never writes quotes; code copies them
  from the cited line.
- **Verification:** each value must appear on its line as a whole token (`5,235.09` matches `5235.09`; `12.84`
  never matches `2.84`). If one fails, that document is re-read one tier up.
- **Storage:** facts are keyed by document id, with the email's UTC received time. `report` rebuilds everything
  from documents received by `as_of`, so backdated documents and arrival order need no special handling.

## Conflicts

Contract terms come from `Case.terms_on(contract, date)`:
- the MSA, with signed amendments layered on per lane and band in effective-date order;
- rate notices returned as separate sources, gated by an exact `From`-address match against Schedule 1 `rates`.

Each rule returns one correct amount per source, with its authority level and precedence rank. Resolution:
- the stronger source wins;
- a source without authority drops out;
- two authorised sources in force that the MSA's typed `unranked_pairs` lists give a conflict, with
  `[max(0, billed − higher), billed − lower]`;
- a held document naming one we don't hold (for example "Annex A rev 2", on a lane and date it governs) gives
  `cannot_determine`, with the holder taken from Schedule 1.

## Confidence

The score starts at 0.95 and is reduced for each weaker signal:
- a pickup date not from tracking or a carrier pickup email;
- a re-read;
- a term below level 1;
- a Judge answer in the chain;
- an INR conversion.

Conflicts are fixed at 0.6, cannot_determine at 0.5; the weights are one table in `confidence.py`. Practice has no
wrong items, so AUROC is unmeasurable (Brier 0.019). Ranking on the hidden set is our least-tested claim.

## People in the loop

`policy.py` applies the glossary's action table.
- **Supervised:** outbound remedies are `draft:*`; there is no path to `execute:*`.
- **Autonomous:** `execute:*` only when all five checks pass:
  - pickup date from tracking or a carrier email;
  - no open conflict on the same contract, lane and period;
  - under $5,000 summed per invoice or cashback key;
  - the action can be undone;
  - every term at authority level 1–2.

  Unknown counts as failed, which gives `human_review`.
- **Escalation:** conflicts always `escalate`. Escalation is 4% on practice.
- **Injection:** text addressed to automated readers is stored as level-5 data, model calls have no tools that act,
  and senders come from the parsed `From` header, never the body.

## Feedback

Feedback items are stored with their envelope as scoped facts.
- **Before the rules run:** `rate_accepted`, `sender_authority` and `precedence` apply only where every
  `applies_to` filter matches, within `valid_from` to `valid_to`. A later signed document still wins.
- **After the rules run:** `reject`, `close`, `one_off_approval` (that key only, for the named months) and
  `override_amount`.
- **`learned_at`:** rules run with and without feedback; a key whose answer differs carries `learned_at`.
  "Must not spread" tests cover another month, lane and contract.

## New documents

Every printed report is kept in the state dir.
- A key whose verdict, amount or action changes gets `supersedes`.
- A key that exists only because of a backdated document gets `retro`.
- Expiry layers signed extensions, so an alert can disappear.
- New layouts are absorbed by the readers. Rules read only typed fields (band limits, basis kinds, `picked_up_values`
  for tracking exports), never layout text.

## Cost

Measured, not estimated:
- **Per document:** exam batch 1 (35 documents) took 69 calls and 150k tokens, about 4.3k tokens a document. Reads
  start on Haiku and escalate to Sonnet only when verification fails; contracts start on Sonnet.
- **Per run:** the first uncached practice grade (163 documents, both modes) cost $2.81 and about 5 minutes, about
  **$17 and 25 minutes per 1,000 documents** with 8 parallel calls.
- **Development:** the API total was about $9.
- **What saves the most:** a content-hash cache outside the state dir (set in a local file, since the grader strips
  environment variables), truncated inputs for classification and sheet mapping, and prompt caching of schemas.

## What I'd do next

An independent audit (`docs/research/05-independent-audit.md`) found 8 blockers; all are fixed. Still open:
- rate notices or letters attached as PDFs, and invoices attached as images;
- `cannot_determine` only on three paths, not every document a held document names;
- duplicates rebilled at a changed amount, and credits matched by exact strings;
- late-fee risk not subtracting amounts already disputed;
- margin step-down not computed;
- confidence weights tuned on a set with no wrong answers.

With another week: adversarial evals built from rewritten layouts, and calibrated confidence.