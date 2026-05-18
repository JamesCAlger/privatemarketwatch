# Phase 6 Current-Cache Parity Verification

Date: 2026-05-16

## Question

Does Phase 6 change generated outputs when run against the same current cached
inputs?

## Method

The original pre-Phase-6 snapshot was not a valid gate after the determinism
cleanup because tied row selection had been stabilized. I rebuilt a new
pre-Phase-6 snapshot with the determinism fixes held constant, then reapplied
only `phase6_compat_cleanup.patch` and rebuilt the post-Phase-6 outputs.

Commands run:

```powershell
git apply --reverse phase6_compat_cleanup.patch
python scripts/rebuild_outputs.py
python scripts/current_cache_phase6_parity.py snapshot --clean --snapshot-dir data/snapshots/current_cache_pre_phase6_determinism_fixed
git apply phase6_compat_cleanup.patch
python scripts/rebuild_outputs.py
python scripts/current_cache_phase6_parity.py diff --semantic --snapshot-dir data/snapshots/current_cache_pre_phase6_determinism_fixed
```

## Result

The Phase 6-only current-cache comparison passed:

```text
Semantic report: data/output/current_cache_phase6_diff_report.json
Semantic delta rows: 0
Diff clean: 418 checked
```

This includes the upstream CSV artifacts, frontend JSON artifacts, and generated
classification SQL captured by the comparator.

## Additional Verification

Same-code reproducibility was also checked after the determinism fixes:

```text
Semantic delta rows: 0
Diff clean: 418 checked
```

The full test suite passed before the final Phase 6 gate:

```text
1868 passed, 13 skipped
```

After tests, production outputs were rebuilt from cached inputs.

## Official Baseline Status

The old official baseline was archived because it was built from stale current
cache state and nondeterministic output selection:

```text
data/snapshots/baseline_pre_phase6_stale_2026-05-16/
docs/refactoring/baseline_manifest_pre_phase6_stale_2026-05-16.json
```

Before retirement, running the existing baseline diff against current-cache
outputs failed:

```text
Diff failed: 170 divergent artifact(s), 3681 checked, 76 skipped
```

That result was expected because the official baseline was stale relative to the
current cache and determinism-cleaned output selection. It was handled as a
baseline refresh decision, not as Phase 6 drift.

The active official baseline was then refreshed from the deterministic
post-Phase-6 current-cache outputs:

```powershell
python scripts/snapshot_outputs.py --clean
python scripts/diff_outputs.py --semantic
```

Active baseline result:

```text
Snapshot complete: 3681 included, 78 excluded, 3759 total
Semantic diff report: data/output/semantic_diff_report.json
- holdings: 0 semantic delta row(s)
- matches: 0 semantic delta row(s)
- position_returns: 0 semantic delta row(s)
- index_returns: 0 semantic delta row(s)
- fund_financials: 0 semantic delta row(s)
Diff clean: 3685 checked, 78 explicitly skipped
```

## Conclusion

Phase 6 is zero-delta under the current cached inputs when compared against a
determinism-fixed pre-Phase-6 rebuild. No unexplained semantic Phase 6 output
delta remains. The active official baseline now points at deterministic
post-Phase-6 outputs; the old baseline is historical-only.
