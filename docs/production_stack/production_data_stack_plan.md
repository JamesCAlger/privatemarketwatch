# Production Data Stack Plan

Date: 2026-09-02
Status: APPROVED DIRECTION (phase 0 in progress)
Owner: James Alger

## 1. Purpose and Scope

Move the repo from a research-grade pipeline on one laptop to a production-grade
data platform, without weakening the data-quality machinery that already exists.
This plan covers infrastructure shape only:

- storage, file formats, transformation framework, orchestration, CI/CD.

Explicitly OUT of scope here:

- the agentic validation/remediation loop (Agents A/B1/B2, quarter-pass
  operator, verify/promote gates). It is treated as a fixed subsystem that the
  new stack must accommodate unchanged — see section 5.
- v1 product scope changes (still: unlisted-BDC cohort holdings only).
- index construction (post-v1).

Guiding judgment (from AGENTS.md, reaffirmed): data-quality work outranks
refactoring. Every phase below is sequenced so that validation gates get
stronger or stay equal at each step; no phase trades measurability for
cleanliness.

## 2. Current State (2026-09-02 assessment)

Already production-grade in substance:

| Principle | Where it lives today |
|---|---|
| Immutable raw layer | `data/raw/` cached EDGAR data (121GB), no-network rebuilds |
| Deterministic rebuilds | `scripts/rebuild_outputs.py`, twin-build determinism gate |
| Environment diffing | `scripts/diff_outputs.py --semantic` + baseline snapshots |
| Corrections as versioned data | promoted overrides/anchors/rules/grammars in git, with evidence |
| Validation gates | V1-V7, shadow engines, 7/7 quarter-acceptance thresholds (v2) |
| Lineage/provenance | provenance columns + deterministic re-verifier (verified-FV 99.9%) |
| Serving | static JSON export -> Next.js site (zero query infra) |

Missing (the "shape" gaps), ranked by risk:

1. ~~Single-machine existence risk~~ — code pushed to GitHub 2026-09-02; raw
   cache backup to R2 pending owner's one-time Cloudflare setup
   (`docs/reference/cloud_backup_setup.md`).
2. No CI — in progress (`.github/workflows/ci.yml`, `needs_cache` split).
3. Transformations are SQL strings inside Python modules, not a declared DAG.
4. Orchestration is an operator skill + `run_quarter_pass.py`, with run history
   in markdown/memory rather than a run database.
5. CSV as the storage format (type-inference bug class, size, speed).
6. Repo hygiene: root littered with tmp dirs/scripts; `scripts/` mixes ~30
   production scripts with ~90 one-offs.

## 3. Target Architecture

```
  Python ingestion (edgar_client, N-PORT/N-CEN/BDC zips)   [unchanged]
      |
      v
  BRONZE  data/raw (local) mirrored to R2 object storage   [backup + future source of truth]
      |
      v
  Python extraction (XBRL parse, HTML templates, grammars) [unchanged]
      |
      v
  SILVER  typed Parquet: extracted holdings, facts, fund metadata
      |
      v
  dbt-duckdb (or SQLMesh) DAG:
      staging -> corrections-applied -> unified -> analytics
      - correction stores as SEEDS (promoted overrides/rules/anchors)
      - declared schema contracts per model
      - V1-V7 + conservation checks as dbt tests at layer boundaries
      |
      v
  GOLD  private_markets_holdings (Parquet + CSV compat) + analytics marts
      |
      v
  Python: position matching, index math (post-v1)          [unchanged]
      |
      v
  EXPORT  frontend JSON (pipeline.export_frontend)          [unchanged]

  SIDECAR (unchanged, out of scope): agent loop
      residual artifacts -> A (grammar) -> B1 (bundle) -> B2 (propose)
      -> deterministic verify/promote gate -> corrections seed layer
      Agents never write pipeline tables; only the gate writes seeds.

  CROSS-CUTTING:
      CI (GitHub Actions): cache-free tests + frontend build on push
      Orchestration (Dagster, phase 3): quarter-pass as partitioned job
      Semantic diff + twin-build gate: migration acceptance at every step
```

## 4. Tool Choices

| Layer | Choice | Rationale | Cost |
|---|---|---|---|
| Object storage | Cloudflare R2 | S3-compatible, zero egress, ~$1.85/mo for 121GB | ~$2/mo |
| Format | Parquet (partitioned by report_date where large) | typed schema kills the all-NULL->INT32 / CIK-padding bug class; 5-20x smaller; DuckDB-native | free |
| Engine | DuckDB (already in use) | right size for ~1M-row datasets; no warehouse needed | free |
| Transform | dbt-duckdb, evaluate SQLMesh before committing (sec. 7) | declared DAG, schema contracts, tests-as-config, docs/lineage | free (core) |
| Orchestration | Dagster OSS (phase 3) | asset-oriented matches artifact thinking; partitioned by quarter; wraps existing scripts unchanged | free (self-hosted) |
| CI | GitHub Actions | public repo = unlimited free minutes | free |
| Quality | dbt tests + KEEP `diff_outputs.py --semantic` + twin-build gate | dbt tests don't replace semantic diffing; both run | free |
| Serving | keep static JSON + Next.js | already production-grade | existing |

Explicitly REJECTED (right tools, wrong problems — revisit only if scale
changes by orders of magnitude): Snowflake/BigQuery/Redshift, Spark,
Airflow, Kafka, Iceberg/Delta table formats, data catalogs, self-hosted CI
runners on the public repo (fork-PR code execution risk).

## 5. Contract with the Agentic Subsystem

The stack migration must preserve these properties, verbatim from current
behavior:

1. Agents propose; only the deterministic verify/promote gate writes to the
   corrections layer. In dbt terms: agent output never touches models; promoted
   corrections land as seeds/config that models consume.
2. Residual/blocker artifacts remain first-class outputs of the validation
   layer (dbt test failures must still materialize as queryable rows that B1
   can bundle, not just CI red).
3. The quarter-acceptance thresholds (v2: reconcile>=90, flagged<=10,
   blocking<=1, verified_fv>=70) remain the promotion gate for gold,
   independent of any dbt test status.
4. Provenance columns and the re-verifier survive the migration; any model
   that transforms a value must carry its provenance forward.

## 6. Phased Sequence (with acceptance gates)

Ordering rule: risk reduction first, effort second. Each phase has a hard
acceptance gate; do not start the next phase while the previous gate is red.

### Phase 0 — Existence + enforcement (IN PROGRESS, days)
- [x] Push all branches to GitHub (done 2026-09-02).
- [x] Repo hardening: secret scanning + push protection + Dependabot (done).
- [ ] Raw cache backup to R2 (owner: one-time Cloudflare setup, then
      `scripts/backup_raw_to_r2.ps1`; re-run after each quarter ingest).
- [ ] CI live: `needs_cache` split + workflow green on GitHub.
- [ ] Branch ruleset on main requiring the two CI checks (after first green run).
- GATE: CI green on a fresh runner; raw cache verified in R2 via
  `rclone check` (checksum comparison — `rclone lsd` only proves folders
  exist, not that 121GB transferred intact) AND one restore drill:
  pull a subset to an empty dir and diff it against the local copy.

### Phase 1 — Parquet conversion (days-week)
- Convert silver/gold artifacts to Parquet with explicit schemas; keep
  `private_markets_holdings.csv` as a compatibility export (it is a named
  contract in AGENTS.md and consumed by scripts).
- Convert in one gated change: build both formats, then flip readers.
- GATE: twin-build determinism PASS on the Parquet path AND
  `diff_outputs.py --semantic` vs the CSV build shows zero deltas, OR only
  deltas individually explained and classified as type-fidelity corrections
  (the exact bug class Parquet exists to fix: all-NULL->INT32, CIK
  zero-padding, float round-trip). Each such delta gets a line in the
  migration notes; no bulk waivers, and the diff itself is never weakened
  to pass.

### Phase 2 — Transformation DAG migration (weeks, incremental)
- Decide dbt-duckdb vs SQLMesh (spike: port 2-3 CTEs to each, compare
  contract enforcement + column-level lineage + migration ergonomics).
- SPIKE SUCCESS CRITERION (the reason this phase exists): a model-boundary
  test failure must round-trip into the agent loop — failure materializes
  as queryable rows (`--store-failures` or equivalent) that convert into a
  B1-bundlable packet whose mechanism localization ("defect entered
  between staging and correction-application, column X") is strictly more
  precise than the current end-of-pipeline residual classifier. This only
  pays off for transform-layer defects (subtotal leakage, duplicate
  dimension paths, pct inflation, rate scale); extraction-side blockers
  (grammars, templates, parser mismatches) gain nothing from the DAG. If
  the spike yields only lineage docs and contracts restating V1-V7, the
  correct outcome is KEEP THE PYTHON SQL and close this phase — that is a
  valid conclusion, not a failure.
- Port `build_unified_holdings()` CTE-by-CTE: staging models first
  (`stg_bdc_holdings`, `stg_nport_holdings`), then correction application,
  then unified assembly. One CTE (or small cluster) per PR.
- Port correction stores to seeds; port V1-V7 + conservation + range checks
  to tests at the model boundary where each belongs.
- Shared logic (name normalization, CIK padding) becomes macros — single
  definition, both source paths.
- WRITE-GUARD REPLACEMENT (required, not optional): the pytest production
  write-guard (`tests/conftest.py`) monkeypatches `builtins.open`/`io.open`
  — DuckDB and dbt-duckdb write through native C++ IO and bypass it
  entirely. Once materializations are the main write path the guard is
  blind. Replace with: (a) test dbt profile targeting a scratch/tmp dir,
  never `data/output/`; (b) post-suite filesystem check (mtime + hash
  manifest of `data/output/` and `frontend/public/data/` before vs after)
  as the enforcement backstop. Ship this in the SAME increment that
  introduces the first materialized model, not later.
- GATE per increment: full pytest suite green + semantic diff zero-delta
  + twin-build determinism PASS. Twin-build is per-increment because
  splitting one DuckDB query into materialized models can change
  window-function / ROW_NUMBER tie resolution (`with_cost` FIRST_VALUE,
  match tiebreaks) in ways a single diff run passes but that drift across
  runs.
  GATE for phase completion: dbt/SQLMesh build reproduces current unified
  output exactly; provenance re-verifier reruns on the migrated output and
  reports verified-FV >= the pre-migration figure (99.9%) — section 5.4 is
  enforced here, not assumed; write-guard replacement live;
  `pipeline/unified_holdings.py` SQL retired; docs/lineage site generates.

### Phase 3 — Orchestration (1-2 weeks)
- Wrap the quarter pass in Dagster: partitioned-by-quarter job; existing
  scripts called as ops (no logic rewrite); agent dispatch stages as ops;
  acceptance thresholds as asset checks blocking gold materialization.
- Run history, stale-partition tracking, and pass/fail records move from
  markdown/operator memory into the Dagster run DB.
- GATE: one full quarter pass executed end-to-end under Dagster with
  identical artifacts to the script-driven path.

### Phase 4 — Hygiene + CI deepening (background, continuous)
- Root cleanup: tmp dirs/scripts into `scratch/` per existing convention.
- `scripts/` split: production entrypoints vs `scripts/oneoff/` (or delete).
- Curated R2 test slice for CI integration tests (deferred by owner
  decision 2026-09-02; revisit after phase 2).
- Nightly full-suite run stays local until the test slice exists.

## 7. Open Decisions

| Decision | Options | Default if undecided |
|---|---|---|
| dbt vs SQLMesh vs keep Python SQL | spike both in phase 2 against the round-trip criterion | dbt (ecosystem maturity) if the spike passes; keep Python SQL if it doesn't |
| License | MIT / Apache-2.0 / unlicensed | owner call; none = all rights reserved |
| `data/output` backup | R2 alongside raw vs rebuildable-so-skip | back up `data/snapshots/baseline` only |
| Backup cadence | post-ingest manual vs Task Scheduler | manual post-ingest |
| MotherDuck | adopt for hosted endpoint | no (no current need) |

## 8. Risks

- Migration preserving wrong behavior behind cleaner abstractions — mitigated
  by the per-increment semantic-diff gate; the diff, not the refactor, is the
  arbiter.
- Parquet flip breaking long-tail script consumers — mitigated by CSV compat
  export and grep-audit of `read_csv`/path references before the flip.
- Native-IO writes (DuckDB/dbt) bypass the Python-level pytest write-guard,
  silently reopening the production-corruption class it exists to block —
  mitigated by the write-guard replacement mandated in phase 2, shipped
  with the first materialized model.
- dbt seeds are awkward for large/nested correction stores — if a store does
  not fit seed semantics, keep it as a Parquet source with a schema contract
  instead; do not force it.
- Dagster adds a daemon/process to a machine already running fleets — keep
  phase 3 last; the script path remains the fallback.
- Solo-operator bus factor — phase 0 (git + R2 + CI) is the mitigation; docs
  in this folder are the runbook.
