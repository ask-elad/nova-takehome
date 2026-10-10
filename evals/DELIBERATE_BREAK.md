# Deliberate-break demonstration

The task asks us to break one rule on purpose, confirm an eval case catches
it, and restore the rule.

## What we broke

In `harness/nova/rules/duplicate.py`, the `_run_awb_code` comparison was
weakened to strip any `-H<n>` suffix before matching:

```python
# BROKEN
if (awb.split("-H")[0]) != (awb2.split("-H")[0]) or code != code2 or amt != amt2:
    continue
```

That treats two house AWBs under one master as the same shipment — glossary
decoy DU-05.

## Case that catches it

Running `make sheet` against the exam mailbox with the break in place
produces an extra duplicate finding on `CDU-3051313` for $52.70. That
invoice shares its master AWB (`CA96669138`) with `CDU-3051304` but the
house suffixes differ (`-H2` vs `-H1`), so the hand-checked answer sheet
has no duplicate on it. The regression surfaces as a mismatched row on the
duplicate line of the sheet-comparison table.

Within the eval set, `evals/cases/house_awbs_not_duplicate.yaml` is designed
to pin the house-suffix behaviour down on a tiny mailbox, but the
overcharge-example mailbox it uses doesn't contain the master-plus-two-house
pattern, so the broken comparison is dead code there. The real-world catch
is the exam re-run.

## Real-world case this task caught

Before this fix the practice exam hand-check flagged the extra
`CDU-3051313` duplicate as a false positive. Investigating that bug led to
the billing-reader prompt change ("keep the full waybill, don't collapse to
the master") and the regression test in
`harness/tests/test_duplicate_house_awb.py`.

## Second real-world case the eval set caught

In Phase 7 the eval case `evals/cases/sample_conflict.yaml` started failing
with `range ['0.00', '0.00']` instead of `['0.00', 20.87']` — same mailbox
and expected finding as the hand-written example, so the regression had to
be inside the harness. Tracing the pipeline showed the amendment was never
reaching the rules engine: `_read_record` returned `None` for
`batch_01/0003.eml#TBX-US-EXP-E90-AMD-1.pdf`, so overcharge priced the
invoice from the MSA alone and the two "correct" amounts collapsed to one.

The root cause was in `harness/nova/readers/__init__.py`. The first
(`main` tier) read of the amendment parsed cleanly but tripped
`verify_object` on a few empty-string payment fields; that triggered a
reread at `strong`, which omitted the required `payment_due_days`,
`payment_grace_days` and `late_fee_rate` fields entirely. Pydantic
rejected the strong-tier dict, and the reader threw away the perfectly
good main-tier parse because it only kept the latest attempt.

The fix: when the reread fails pydantic validation, fall back to the
first attempt's instance (and clear `parse_error`). The main-tier parse
is imperfect but usable — exactly the shape the amendment reader was
written to handle. The unit test
`test_reread_parse_failure_falls_back_to_first_read` in
`harness/tests/test_readers.py` pins the behaviour.

## Restoring the rule

Revert the comparison back to the exact `awb != awb2` check and confirm
`make sheet` matches the hand check again (overpayment `$3,847.70`).
