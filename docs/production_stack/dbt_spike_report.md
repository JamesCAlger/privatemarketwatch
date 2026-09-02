# dbt Round-Trip Spike Report

Date: 2026-09-02
Spec: production_data_stack_plan.md, Phase 2 spike criterion.
Code: spikes/dbt_roundtrip/ (branch ensemble-fp-experiment, commits 96ec694..4d6ae20, range includes two unrelated CI commits, 70b4c8b and af52d8a, from a concurrent session)

## Verdict: GO for phase 2

| Kill criterion | Result | Evidence |
|---|---|---|
| 1. Stored failures carry provenance keys | PASS | 2,004 failure rows, all with populated src:{accession}:{contextRef} source_row_id (0 empty; artifacts/verdict.json + Task 3 dbt run output) |
| 2. Packet strictly better localized than incumbent | PASS | packet: boundary_model=stg_bdc_holdings + downstream_fix_model=bdc_dim_deduped + per-group source_row_ids (1,000 groups); incumbent for same CIKs: documented_duplicate_dimension_path label on 12 rows, no boundary model, no fix model, no per-group ids |
| 3. Port friction under ~1 day | PASS | NOTES.md log: ~3h15m wall time (20:35-23:50), 4 dbt-specific workarounds (see Ergonomics) |

## Replay facts

- Defect class: duplicate XBRL dimension paths (risk-register item).
- Spike CIKs: 0000017313, 0001959568, 0001959604. Dup groups: 1,000. Dropped rows: 1,004.
- groups_match: True; dropped_row_identity_match: True.
- Twin-build hash: equal (bf8de820f32778e3553bd9531edf773c).

## Ergonomics findings

- **Easy:** dbt store_failures materialize failing rows with full column context at zero boilerplate; the boundary test (duplicate_dimension_paths) required ~10 lines of SQL. The stored-failure table was queryable immediately for the packet converter.
- **Easy:** dbt run + dbt test integrate cleanly with an existing DuckDB parquet source via profiles.yml; no schema migration required.
- **Friction 1 -- protobuf conflict:** dbt-duckdb 1.11.0 requires protobuf 6.x; the conda env carries 5.29.5 (pinned by the pytest suite). Required an isolated .venv/ to avoid breaking the test suite. Resolution: spike-only venv; dbt-duckdb not added to requirements.txt.
- **Friction 2 -- view-default materialization:** dbt models default to VIEW, not TABLE. spike.duckdb contains views + stored-failure audit tables only (no materialized intermediate tables). Harmless for the spike but diverges from the production pattern; production models will need explicit `materialized='table'` config.
- **Friction 3 -- PowerShell 5.1 quoting:** `python -c` with nested double-quotes fails in PS5.1 due to quote mangling. Workaround: write a temp .py script, run it, delete it. A known PS5.1 trap; operators should use here-strings or named scripts.
- **Friction 4 -- cwd-dependent view path:** dbt VIEWs bake the relative parquet path at `dbt run` time. Running compare_and_verdict.py from repo root instead of spikes/dbt_roundtrip/ gives an IO error. Not a dbt bug -- a consequence of relative-path source config. Production models should use absolute profile paths.
- **Full port extrapolation:** This cluster (2 models + 1 boundary test + packet converter, covering a single dedup CTE) took ~3h15m wall time, of which ~36 min was the staging extractor running under environment contention (concurrent Q1 pass; the 2,146s runtime was I/O contention, not dbt overhead). Stripping contention, net dbt + tooling time was under 2 hours. build_unified_holdings has ~15 CTEs with cross-source joins, classification logic, and multiple output columns. A conservative extrapolation at 2 CTEs per ~1.5h of net dbt time gives roughly 10-12 hours of focused porting work, plus additional time for boundary tests on each CTE. This is achievable in a 2-3 day sprint but is not trivial. The friction items above are all solvable; none are architectural blockers.

## Caveats

- Single defect class, 3 CIKs, BDC-only slice; N-PORT branch and the cross-source dedup CTEs were not ported.
- source_row_id here lacks the incumbent's _{periodSuffix}; join on accession+context prefix when comparing to source_only_detail.csv.
- The same three CIKs carry 5,068 blocking rows of blocking_source_position_like_parser_mismatch -- a separate, extraction-side defect class the spike does not address; the 12-row incumbent comparison covers only the duplicate-dimension class.
- Framework choice (dbt vs SQLMesh) is NOT decided by this spike; if verdict is GO on criteria but ergonomics were poor, run the same replay on SQLMesh before committing (plan section 7). SQLMesh comparison remains open.
- The semantic-diff backstop (python scripts/diff_outputs.py --semantic) was skipped by controller ruling: a Q1 2026 quarter pass ran concurrently and rebuilt bdc_holdings + unified outputs on the same date, making baseline deltas unattributable -- the check would be a false alarm, not evidence. Substitute evidence: (a) all spike write paths land under spikes/dbt_roundtrip/ (verified across five task reviews); (b) the production input bdc_holdings.parquet mtime was verified unchanged after the extractor ran.
- compare_and_verdict.py reuses con.description after fetchall -- this is correct in current DuckDB but is fragile; if promoted, replace with an explicit schema capture before fetchall.
- dedup_hash() is cwd-dependent because the dbt VIEW bakes a relative parquet path -- harmless in the disposable spike, must be fixed to an absolute path if promoted to a permanent fixture.
- The write-guard replacement mandated by the stack plan phase 2 (scratch-dir dbt profile + post-suite filesystem manifest check) is untouched by this spike and remains a precondition for any materialized production model.

## Recommendation

GO -- proceed to phase 2 as planned. All three kill criteria pass: provenance is fully populated, the dbt packet is strictly more actionable than the incumbent residual label, and the total friction was well under one day. That said, phase 2 remains conditional on the stack plan's own gates: the spike proves the round-trip for one transform-layer defect class on a 3-CIK BDC-only slice, and SQLMesh comparison plus seed-fit for correction stores remain open per plan section 7. The write-guard replacement mandated by the stack plan must ship with the first materialized model before any production dbt output is trusted by tests.
