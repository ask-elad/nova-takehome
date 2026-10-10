# Task 08 · Hardening before submission

**Phase:** 7 (end) · One short session. Real runs as in 05a (with the cache, most calls are free).

1. **Regression: `evals/cases/sample_conflict.yaml` fails** (range `[0.00, 0.00]`, expected `[0.00, 20.87]`). It
   passed in Phase 3. Find which task-07 change broke it, fix the cause, and add a unit test that pins it.
   Note this in `evals/DELIBERATE_BREAK.md` as the second bug the eval set caught (a real one this time).
2. **Overfitting audit.** Run each command and paste its output:
   - `grep -rnE "TX-|TXI|CDU-|CDI-|CDC|CDA-|TBX-|CA[0-9]{8}|TX[0-9]{8}|Tarrowby|Caldrith|Quillmere|Ferrowyn" harness/nova/ harness/readers 2>/dev/null`
     must show only comments or docstrings.
   - **Replace "month windows parsed from free-text conditions" with the typed `months` field** the accessorial
     reader fills. Rule code must not regex free text.
   - **Explain "contract_for_invoice issuer fallback"** in two lines. Keep it only if it uses typed fields (contract
     reference, then a party match against the MSA parties); otherwise remove it.
3. **Check `evals/cases/autonomous_over_threshold.yaml`.** It must assert that an outbound finding summing to
   $5,000.00 or more on one invoice is `human_review` in autonomous mode. If it asserts something else, rename it
   for what it tests, and add a real over-threshold case.
4. **Re-run** `make eval`, `make grade`, `make sheet`. The answer sheet must be unchanged, the practice score should
   stay at about 99.6, and evals must be 14/14. Commit the outputs.

## Done when
Show the three run results, the grep output, and a one-line answer for each of steps 2–3.