# Phase 1 — Parquet Migration Plan

Date: 2026-09-03
Status: IN PROGRESS (owner decision 2026-09-03: PR-1/PR-2 may proceed before
the phase-0 R2 gate — they are additive/reversible; ONLY PR-3 (CSV retirement
+ baseline refresh) waits for R2 `rclone check` + restore drill, because that
step actively relies on rebuild-from-raw as its safety net)
Parent: `production_data_stack_plan.md` section 6, Phase 1

## 1. Scope

Convert the core silver/gold chain to Parquet with explicit schemas. Everything
else stays CSV — the 2026-09-03 triage (`scratch/2026-09-03_csv_triage/`,
changelog entry same date) confirmed the remaining 131 top-level CSVs are small
summaries/diagnostics with real consumers; converting them buys nothing.

### Conversion list (11 artifacts, ~4.6 GB of the 4.9 GB total)

| Artifact | Size | Role |
|---|---|---|
| `source_reconciliation_detail.csv` | 1.48 GB | recon row detail |
| `private_markets_holdings.csv` | 683 MB | central unified holdings (KEEPS CSV compat forever — named contract in AGENTS.md) |
| `provenance_ledger.csv` | 643 MB | provenance re-verifier ledger (full rewrite per run — verified 2026-09-03, `provenance_reverify.build_ledger`) |
| `bdc_holdings.csv` | 577 MB | BDC extraction output |
| `bdc_ixbrl_field_status.csv` | 282 MB | extraction field status |
| `row_validation_issues.csv` | 209 MB | validation row flags |
| `nport_holdings.csv` | 193 MB | N-PORT extraction output |
| `position_pik_status.csv` | 178 MB | PIK status |
| `position_matches.csv` | 174 MB | position matching pairs |
| `position_returns.csv` | 154 MB | per-position returns |
| `position_id_edges.csv` | 124 MB | position-id union-find edges |

Layout: side-by-side `foo.parquet` next to `foo.csv` in `data/output/`. No
hive partitioning in phase 1 — at ~1M rows/artifact, single-file Parquet is
well within DuckDB's comfort zone; partitioning adds path complexity for zero
measured benefit at this scale. (Deviation from the parent plan's "partitioned
by report_date where large" — revisit only if an artifact exceeds ~10M rows.)

## 2. Schema contracts (the actual point of the phase)

New module `pipeline/output_schemas.py`: one ordered `{column: duckdb_type}`
dict per artifact. Non-negotiable typings:

- `cik`: VARCHAR, 10-digit zero-padded (kills the CIK-padding bug class)
- `report_date`, `period`, `maturity_date`, acquisition dates: DATE
- `fair_value`, `cost`, rates, `pct_of_net_assets`: DOUBLE with true NULLs
  (kills the all-NULL->INT32 inference class)
- identifiers/flags/text: VARCHAR; booleans: BOOLEAN, not 0/1 ints

Writers CAST to the contract on write (DuckDB `COPY (SELECT CAST...) TO
'x.parquet'`); a shared assert helper verifies emitted schema == contract.
Schema drift becomes a hard error at write time, not a silent downstream cast.

Writes use a deterministic `ORDER BY` (stable key per artifact) so twin-build
byte-identity is achievable; if DuckDB writer metadata still differs
byte-wise between twin builds, the determinism gate falls back to semantic
row-set equality (DuckDB `EXCEPT` both directions) — documented, not silent.

## 3. Write-guard gap — brought FORWARD from phase 2 (safety-critical)

The pytest production write-guard monkeypatches `builtins.open`/`io.open`.
DuckDB `COPY TO` and pyarrow write through native IO and **bypass it
entirely**. The parent plan mandates a replacement "with the first
materialized model" in phase 2 — but phase 1's Parquet writers open the same
hole earlier. Therefore the backstop ships in the FIRST phase-1 PR:

- post-suite filesystem check in `tests/conftest.py`: mtime+hash manifest of
  `data/output/` and `frontend/public/data/` captured at session start,
  re-verified at session end; any delta fails the run loudly.
- existing `open()` guard stays (still covers the pandas/json paths).

## 4. Increment sequence

Each increment is one PR on a branch, CI green, merged via the main ruleset.

### PR-1: contracts + dual-write + write-guard backstop
- `pipeline/output_schemas.py` with the 11 contracts.
- Each writer emits Parquet alongside its existing CSV (CSV still canonical;
  no reader changes). Writer modules confirmed during implementation audit.
- conftest filesystem backstop (section 3).
- `scripts/parquet_csv_parity.py`: reads both formats into DuckDB, compares
  row counts + per-column checksums + full anti-join; writes a parity report.
- GATE: full rebuild from cache, parity report clean for all 11, or every
  delta individually explained and classified as a type-fidelity correction
  (per the parent plan's gate wording: no bulk waivers; the diff is never
  weakened to pass).

### PR-2: reader flip + tooling
- Flip readers for the 11 artifacts to Parquet. Read-site audit scoped to
  these files only (not all ~280 CSV call sites): resolve via `config.py`
  constants where they exist, direct grep otherwise; tests included.
- `diff_outputs.py --semantic` + `snapshot_outputs.py` learn to read Parquet
  (byte-hash path already format-agnostic).
- GATE: full pytest suite green; `python -m pipeline.main --unified
  --validate` clean; semantic diff vs pre-flip build zero-delta.

### PR-3: retire legacy CSV writes + baseline refresh
- Stop writing CSV for 10 of the 11; `private_markets_holdings.csv` keeps its
  CSV export permanently (named contract).
- Refresh `data/snapshots/baseline/` per governance: rebuild from cached
  inputs, `diff_outputs.py --semantic`, document deltas, preserve the prior
  baseline (it is being retired: `baseline_pre_parquet_2026-09/`).
- GATE: twin-build determinism PASS on the Parquet path (parent plan's
  phase-1 gate, verbatim).

## 5. Scheduling constraints

- Full rebuilds for gates are hours-long and memory-heavy. Per AGENTS.md: check
  for running quarter-pass / pytest processes first; q1p3 work has been running
  overnight passes — gate rebuilds go in quiet windows only.
- R2 ordering (owner decision 2026-09-03, supersedes the parent plan's blanket
  phase gate): PR-1 (dual-write, purely additive) and PR-2 (reader flip,
  git-revertible with CSVs still on disk) proceed without waiting for R2.
  PR-3 waits for the phase-0 R2 gate (verified backup + restore drill) because
  retiring CSV writes + refreshing the baseline is the step whose recovery
  path is rebuild-from-raw.

## 6. Risks

- Long-tail readers of the 10 retired CSVs outside the audited scope (ad-hoc
  scripts, skills). Mitigation: PR-3 grep-audit across `pipeline/`, `scripts/`,
  `tests/`, `.claude/`, `docs/` for each retired filename; anything found gets
  flipped or the CSV stays another cycle.
- Type-fidelity deltas misclassified as harmless. Mitigation: each one gets a
  line in the PR description with the column, the old value, the new value,
  and why the new one is correct (e.g. "cik 1418076 -> 0001418076, matches
  N-PORT side").
- Parquet writer non-determinism breaking the twin-build gate. Mitigation:
  ORDER BY on write; semantic-equality fallback documented in section 2.
- pandas `read_parquet` vs DuckDB type disagreement at flipped read sites
  (e.g. DATE -> datetime64 vs object). Mitigation: parity script also
  round-trips through both readers for each artifact.

## 7. Effort

2–4 working days of implementation + one gated full rebuild per PR (wall-clock
dominated by rebuild scheduling, not code).
