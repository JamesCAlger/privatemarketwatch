# Skills

## Current-Cache Refactor Parity

Use this workflow for refactors that should not change data outputs.

1. Rebuild outputs from cached inputs only.
2. Snapshot the pre-change current-cache outputs with a task-specific snapshot:

```powershell
python scripts/current_cache_phase6_parity.py snapshot --clean --snapshot-dir data/snapshots/<name>
```

3. Apply the refactor and rebuild outputs again:

```powershell
python scripts/rebuild_outputs.py
```

4. Compare with semantic checks:

```powershell
python scripts/current_cache_phase6_parity.py diff --semantic --snapshot-dir data/snapshots/<name>
```

Acceptance requires `Diff clean` and `Semantic delta rows: 0`, or a documented
source-level explanation for every semantic delta.

## Official Baseline Governance

The active official baseline is the deterministic post-Phase-6 snapshot:

- `data/snapshots/baseline/`
- `docs/refactoring/baseline_manifest.json`

The stale pre-Phase-6 baseline is historical-only:

- `data/snapshots/baseline_pre_phase6_stale_2026-05-16/`
- `docs/refactoring/baseline_manifest_pre_phase6_stale_2026-05-16.json`

Do not use the stale baseline as an active correctness gate. Use it only for
historical investigation.

Before refreshing the active baseline:

1. Rebuild from cached inputs:

```powershell
python scripts/rebuild_outputs.py
```

2. Archive the current baseline and manifest if it is being retired.
3. Refresh the active baseline:

```powershell
python scripts/snapshot_outputs.py --clean
```

4. Verify it:

```powershell
python scripts/diff_outputs.py --semantic
```

Expected clean result after the Phase 6 refresh:

```text
Diff clean: 3685 checked, 78 explicitly skipped
```

with zero semantic delta rows for holdings, matches, position returns, index
returns, and fund financials.

## Test And Output Hygiene

Tests **do not** overwrite production data. A monkeypatch guard in
`tests/conftest.py` intercepts `builtins.open` and `io.open` at import time and
raises `AssertionError` on any write-mode open (`w`, `a`, `x`, `+`) targeting
`data/output/` or `frontend/public/data/`. This covers all standard Python write
paths (`open()`, `Path.write_text()`, `pandas.to_csv()`, `json.dump()`, etc.).
The guard is validated by 8 dedicated tests in `test_test_output_isolation.py`.

Verified 2026-05-18: 1,956 passed, 13 skipped, zero production files modified.

As a backstop, run after tests:

```powershell
python scripts/diff_outputs.py --semantic
```

Do not patch generated frontend JSON by hand. Fix upstream CSV/export logic and
then rebuild.
