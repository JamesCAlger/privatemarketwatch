You fix one confirmed shared cause in the pipeline's code, in your own git worktree, and prove
the fix changes only the funds the investigation predicted.

- Investigation (reviewed and confirmed): `{{investigation}}`.
- Worktree: `{{worktree}}`. Report: `{{report}}`.

Required:
1. The smallest change that fixes the cause, switched on for every fund it should apply to.
2. Tests in tests/: a focused test of the fix, a false-positive test, and a test that a real error
   still fails.
3. A cohort measurement: for each predicted fund, build a sandbox with
   `bash scripts/v05_evidence/build_fund.sh <label> <cik>` and compare with
   `python scripts/v05_evidence/holdings_field_diff.py <new> <old>`; list every changed column per
   fund in `"cohort_diff"`. If the change cannot be measured without the unified build, stop and
   say so in the report (`"needs_batch": true`).
4. Report JSON: {"shared_code": true, "files": [...], "tests": [...], "cohort_diff": {...},
   "predicted_ciks": [...], "moved_ciks": [...], "statement": "..."}.

Same rules as a fund agent: no inline Python, no git commit, no batch or unified build, no
downloads, ASCII only. End with two lines: what changed, which funds moved.
