# 03 Pipeline design: writer order, stages, isolation and export

Consolidated 2026-09-12. Implements the [data contract](02_data_contract.md) under [decisions](01_decisions.md). Section 1 describes the pipeline as it runs today, with confirmed defects. Sections 2-7 describe the target. Nothing in sections 2-7 is deployed except the candidate runner in section 5.

## 1. Current writer order and confirmed defects

Execution scope follows the September 14 owner ruling in [decisions](01_decisions.md): build and verify the refactored architecture using isolated cached candidates. Agent dispatch and new enrichment to remediate the measured dataset run afterward. The existing proposal, verification, promotion and enrichment replay interfaces must work; operating campaigns is not required to prove those interfaces. Integration evaluations retain genuine data FAIL/UNASSESSABLE outcomes without claiming production readiness.

Order inside `build_unified_holdings` in `pipeline/unified_holdings.py`, with upstream staging and later CLI stages. Verified against code on 2026-09-12.

| Order | Writer | What it does | Defect |
|---|---|---|---|
| Upstream | `pipeline/bdc_filings.py` | One record per XBRL investment context; a row with no context does not exist downstream | By design; see D11 |
| S01-S04 | `staging_bdc._prepare_bdc` | Exclusions, latest-accession selection, wrapper parsing, scale and rate heuristics, `basis_spread * 100` to percentage points | |
| S05 | HTML-section bridge and iXBRL field-status overlays | Applies bridge rows keyed by CIK, accession, date, raw identifier | **Live:** loader filters on schema version only; the one file present is `0001838126.proposed.json` with 41 records applied to HPS |
| S06 | `identifier_spread_corrections.apply_spread_corrections` | Writes `new_value_decimal` into `basis_spread` after S04 scaled it | **Live:** 21 positions carry a 100x understated spread (4.75 bps for 475); the correct value sits in the leaf's `agentA_value_pct`; unit tests encode the wrong unit |
| U01-U06 | Roster, dedup, classification, `with_cost`, universe gate, lookups, `_correct_pct_of_net_assets` | `with_cost` treats zero as missing and can replace an explicit zero | Conflicts with D02 |
| U07-U08 | Row corrections, fund-strategy corrections | | |
| U09 | `agent_promoted.apply_promoted_stage2_corrections` | Sorts B2 leaves by `fix_class` **name** | **Latent:** verifier path `agent_b2_appliers.run_corrections` sorts by precedence **stage**; diverges on the first CIK with a stage-1 and a stage-2 leaf |
| U10 | `agent_promoted.apply_promoted_rules` | Layer C in sorted filename order | Parity with gate holds |
| U11 | `_enforce_schema` | Logs warnings only | **Confirmed:** runs before six mutating layers and never blocks a write |
| U12-U15 | GICS cache, lien cache, unclassified cache, wrapper position keys, RE fund GICS override | Rewrite classification and key columns after validation | |
| U16 | `_assign_row_ids`; CSV then Parquet companion | | Audit write condition omits the B2-only case |
| Later | `entity_resolution._enrich_holdings` | DuckDB `COPY` rewrites the holdings CSV | **Confirmed:** no companion rewrite |
| Later | `rebuild_returns` in `scripts/rebuild_outputs.py` | `assign_position_ids` result written to holdings and matches CSVs | **Confirmed:** no companion rewrite; `position_matches.parquet` lacks `position_id`; a later `--unified` run overwrote the ID-populated CSV, so all 780,425 rows have blank `position_id` |
| Later | `export_frontend.export_all` | Static JSON | **Confirmed:** sector donut uses a fund-level XBRL overlay rescaled twice; headline filters `fair_value > 0` and sums rounded buckets; instrument slices are browser-side remainders |

Consequence: after a default rebuild the holdings Parquet is stale by two stages, the matches Parquet is a different row set from its CSV, and the published artifact is never the validated frame.

## 2. Target ordering and the one finalizer

```
pinned sources + cohort + rules + registry inputs
  -> P02 select sources, obligations, accounting bases; independent fund totals
  -> P03 normalize and apply admitted corrections at their declared boundary
  -> P04 resolve entities, then match positions (reported cost only)
  -> P05 bind sector decisions and PIK/non-accrual status
  -> P06 identity-dependent derivations: cost proxy, calculated NAV percentage
  -> P07 FINALIZE: one writer for holdings CSV + Parquet + companions, validate after the last mutation
  -> P08 metrics and independent evaluation (read-only on the sealed data)
  -> P09 export from the sealed data
  -> P10 verify the exported bundle; mark ready or not ready
```

Rules:

- One writer for the canonical holdings CSV and its companion, after entity and position assignment. No stage rewrites the CSV after the companion exists.
- Correction order is semantic: source interpretation and exclusions; structural roster operations; typed field corrections with revalidation; classification features used by matching; identity; identity-bound enrichment. Alphabetical filename or `fix_class` sorting is not precedence. Verifier and production consume the same ordered plan. Two writers on one field need an explicit dependency, or the build stops with a conflict.
- Every admitted store records applied, no-op, rejected or failed, including B2-only and empty-frame runs. An admitted rule execution error prevents sealing.
- Admission is by manifest and status field, never by filename or directory placement. A `.proposed.json` file is not loadable.
- Schema and enum validation run after the last value-changing step; structural violations block the write.
- Matching reads `cost_reported`, never the proxy. Sector outputs do not feed the identity decision that justified them.
- No live model call inside a candidate build. GICS cache misses record a residual; they do not call a model.
- Independent fund financials needed by NAV ratios are built before the transforms that consume them, not read from a previous run.

## 3. Tool boundaries

| Component | Responsibility | Boundary |
|---|---|---|
| Python coordinator (`pipeline/programme/runner.py`) | Snapshot, stage invocation, checkpoints, process ownership, sealing | No financial logic in orchestration |
| Python extraction and staging | Cached document reading, wrapper and grammar application | Preserve raw facts; no new HTML parsing |
| DuckDB SQL inside Python modules | Large joins, dedup, classification, populations, metrics | Stays the transform layer until the writer graph is fixed; dbt is deferred (see [plan](05_plan.md)) |
| Python correction executor | Existing promoted-rule mechanisms with one ordered plan and audit | Never overwrites canonical CSV directly |
| Identity adapters | Resolver, contested matcher, registry allocation | Emit assignments; finalizer projects them |
| Existing validation stack | Source reconciliation, provenance replay, conservation, quarter acceptance, re-attestation | Reads sealed data; writes results elsewhere |
| Export and Next.js | Serialization from one sealed release | No private formulas, no overlays, no browser-side aggregation |

DuckDB uses one writer process per database file. Tests and trials redirect the output directory rather than relying on an OS sandbox.

## 4. Candidate isolation and checkpoints

Layout, all outside production roots:

```
data/programme/candidates/<candidate_id>/
  frozen/                    exact input universe plus runner code; size recorded in snapshot.json
  snapshot.json, snapshot_complete.json, runtime.json
  attempts/<stage>-NN/       workspace, bundle, temp, telemetry, process.json, result.json, complete.json
  restores/
data/programme/heavy.lock    one heavy job at a time (build, matching, full suite)
```

Protocol: verify pinned inputs and the parent's completion record; write outputs into an attempt-local bundle; close writers, reopen and verify types, keys, counts and CSV/Parquet equality including duplicate multiplicity; write the result manifest; write the completion marker last. A missing marker means incomplete, whatever files exist. Execution states are `pending`, `running`, `complete`, `failed`, `interrupted`; quality states are `not_evaluated`, `pass`, `fail`, `unassessable`. A completed FAIL is reusable evidence and never a release.

Identity of an attempt is `(stage, snapshot fingerprint, runtime fingerprint, artifact contract, parent result hash, controls)`. Changing any input creates a new candidate. The owner's later 2026-09-12 execution amendment removes fixed GB/time caps and routine retry-count stops; each diagnosed attempt remains separately recorded.

Requirements removed on 2026-09-12: the full runtime content hash (247,333 files, about five minutes per check) and the Windows low-integrity token are not required. Keep `runtime.json` as a package-list fingerprint. Native write protection comes from `config.OUTPUT_DIR` redirection into the attempt workspace plus the before-and-after inventory of protected roots.

Invalidation on changed input:

| Changed input | Minimum rebuild |
|---|---|
| Filing, amendment or selection policy | Affected fund's observation dates and history for matching and donors; dependent metrics |
| Grammar, classification, maturity or rate interpretation | Every applicable period and matching feature; downstream metrics |
| Entity merge, split or alias | Affected components across filers; if closure is uncertain, the whole identity stage |
| GICS decision only | Applicable fields and exposure outputs; identity reused |
| FV correction or FX quote | Affected fields, matching features that use them, donor chains, totals |
| Thresholds only | Evaluations and readiness; data unchanged |

## 5. What the runner implements today

`python -m pipeline.programme.runner {snapshot,canary,preflight,run,verify,restore} --candidate <id>` now has five adapters: unified holdings, durable identity, PIK evidence, returns and public export. The implementation includes the finalizer and financial migration; representative five-stage verification has passed. Full-data integration and acceptance on the repaired implementation remain incomplete; see the latest execution checkpoints in the [plan](05_plan.md).

New candidates use the amended package metadata fingerprint. Historical runtime records retain their original physical-content policy. Candidate output and baseline preservation is checked independently with before-and-after size/mtime inventories. Existing native write protection is retained, but is not a new programme requirement. The earlier `t1-runtime-20260910-v5` three-stage candidate remains historical evidence and is not the completed implementation of this specification.

## 6. Public export

One query over the sealed holdings for the public quarter and cohort, all signs, all classifications, retained subsidiary rows included:

```
headline          = SUM(fair_value)
instrument slices = same rows GROUP BY instrument partition, explicit unknown bucket
sector slices     = same rows GROUP BY gics_sector, explicit unknown bucket
```

Assert equality of the unrounded sums and of contributor row IDs before writing JSON. Compute slices server-side. Remove the `fair_value > 0` filter, the rounded-bucket sum, the fund-level sector overlay and its two rescalings, the lien-subtotal layering and the browser-side remainders. Conservation membership and reconciliation overlays stay diagnostic artifacts and never enter public totals. `metadata.totalAum` is unused by the frontend and should be removed or aligned.

Fund holdings pages expose the full history with `row_id`, `entity_id` and `position_id` so citations can resolve. Citations map `(release, row_id, field)` to an inline-XBRL fact ID or an existing bridge anchor; missing evidence returns an explicit unavailable state.

## 7. Test and trial protection

The pytest guard in `tests/conftest.py` patches Python `open` and diffs size and mtime of every protected file at session end. It cannot see DuckDB or Arrow writes until after they happen, and a byte-identical rewrite is invisible. Required controls:

- Redirect `config.OUTPUT_DIR` and `frontend/public/data` for the whole test session and for every trial build.
- Keep module-level cache roots isolated by fixture (the query-cache fixture added after the September 10 incident stays).
- Keep the size-and-mtime inventory as the detective backstop and run `python scripts/diff_outputs.py --semantic` after any suite.
- Full suite is serial and measured at 2 h 33 min; no parallel runner is installed. Budget it as such.

## 8. Entry-point migration

| Existing path | Treatment |
|---|---|
| `scripts/rebuild_outputs.py`, `pipeline/main.py` | Keep operator commands; route candidate work through stage adapters; block export when position IDs are blank (rule RI07) |
| `scripts/run_quarter_pass.py` | Keep preflight, rebuild, batteries, ledger, acceptance; add input and output fingerprints |
| `pipeline/unified_holdings.py` and staging | Becomes the finalizer; late identity and cache writers move before it |
| `pipeline/agent_promoted.py` | One ordered plan shared with the verifier; admission by manifest |
| `entity_resolution`, `position_matching`, `rebuild_returns` | Emit assignments; stop rewriting the CSV |
| `index_returns` and rate consumers | Atomic all-in migration with the storage flip |
| `export_frontend.export_all` | Section 6 |
| `quarter_acceptance`, `reattest_quarters` | Extended per [acceptance](04_acceptance.md); candidate path adapters |
