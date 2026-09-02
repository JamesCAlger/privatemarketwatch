# dbt Round-Trip Spike — Execution Log

Date: 2026-09-02 (evening) to 2026-09-03 (00:20)
Companion to: `dbt_spike_report.md` (the verdict) and `production_data_stack_plan.md` (the spec).
This file records HOW the spike was executed and the operator rulings made along the way —
the report records WHAT was concluded.

## Outcome

Verdict GO for phase 2; kill criteria 1/2/3 all PASS. See `dbt_spike_report.md` for
numbers and caveats. Spike commits `96ec694..a4927ce` on `ensemble-fp-experiment`
(10 spike commits, interleaved with two unrelated CI commits `70b4c8b`, `af52d8a`
from a concurrent session). NOT pushed or merged — owner's call.

## Execution model

Subagent-driven development from the plan
`docs/superpowers/plans/2026-09-02-dbt-roundtrip-spike.md`: fresh implementer per
task, independent reviewer per task, scoped re-reviews per fix round, final
whole-branch review on the most capable model. 6 tasks, 3 fix rounds total
(Tasks 2, 6, and one final-review fix), all converged in round 1.

## Concurrent Q1 2026 pass coexistence

The q1p3_20260831 quarter pass ran the entire session (pytest probe ->
--bdc-holdings rebuild -> --unified rebuild -> oracle stage). Countermeasures:

- Heavy extractor (Task 2) gated on rebuild-free windows via process watch;
  input `bdc_holdings.parquet` mtime verified stable before and unchanged after.
- `pip install dbt-duckdb` pre-checked with `--dry-run`: it would have upgraded
  protobuf 5.29.5 -> 6.33.6 in the shared conda env under the running pytest.
  Install redirected to a spike-local venv (`spikes/dbt_roundtrip/.venv`);
  shared env untouched.
- All spike writes confined to `spikes/dbt_roundtrip/` + two docs files
  (report, changelog); verified in five task reviews.

## Operator rulings (with cost-if-wrong)

1. No isolated git worktree — the spike needs the 121GB cache and data/output
   inputs that exist only in this checkout; write surface confined to a new dir.
   Cost: dirty-tree interference; mitigated by new-dir isolation.
2. Task 2 gated on rebuild-free windows (above). Cost: none realized.
3. Spike-local venv for dbt (above). Cost: later tasks must use the venv binary
   (`.venv/Scripts/dbt.exe`); documented in the spike README.
4. README `cd spikes/dbt_roundtrip` prefix stands (matches plan text).
   Cost: trivial path error if a future operator forgets the cd.
5. Parked to promotion-time: `con.description` reuse after fetchall in
   compare_and_verdict.py (fragile pattern, correct in current DuckDB) and
   cwd-dependent `dedup_hash()` (dbt VIEW bakes a relative parquet path).
   Cost: none until the spike code is promoted to a permanent fixture.
6. `scripts/diff_outputs.py --semantic` backstop SKIPPED — the concurrent pass
   rebuilt bdc_holdings + unified outputs the same evening, so baseline deltas
   were expected and unattributable to the spike; running it would have produced
   a false alarm, not evidence. Substitute evidence: reviewed write paths +
   input-mtime checks. DEFERRED ACTION: run `python scripts/diff_outputs.py
   --semantic` in a quiet window (no quarter pass, no rebuilds) as a
   belt-and-braces confirmation; expected result is deltas attributable to the
   Q1 pass only.
7. Final-review triage: one blocking fix applied (stale `boundary_model` line in
   NOTES.md — controller-caught factual error the task reviewer missed); all
   other parked/minor items left as disposable-spike caveats, including dbt
   anonymous telemetry not disabled in profiles.yml (disable if promoted).

## Findings that outlived the spike (carry into phase 2)

- The equality proof compares two transcriptions of the production SQL, not
  dbt vs live production output; output parity is enforced by phase 2's own
  per-increment gates (twin-build + semantic diff), not by this spike.
- Keeper-selection parity was not directly verified (which duplicate survives a
  group). Required check when this pattern becomes a phase 2 fixture: compare
  dbt's surviving source_row_id set against production rank-1 rows
  (one `md5(string_agg(...))` each side).
- Spec's "column X" localization granularity was delivered at model+row
  granularity; phase 2 proper should aim for the column pointer.
- SQLMesh comparison and correction-store seed-fit remain open (plan section 7).
- The write-guard replacement mandated by phase 2 is untouched by the spike and
  remains a precondition for any materialized production model.

## Rerun

`spikes/dbt_roundtrip/README.md` has the 4-step rerun order. Artifacts
(parquet slices, spike.duckdb, packet.json, verdict.json) are git-ignored and
reproducible from cached data; evidence that survives in git is
`spikes/dbt_roundtrip/NOTES.md` + the two reports.
