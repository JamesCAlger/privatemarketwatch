# Position & Borrower Tracking Program — Design

Date: 2026-09-03
Status: approved design (owner), pending implementation plan
Owner decisions captured: Approach 1 (measurement-first); both capabilities, cohort-first but universe-capable; agent-built gold set with human audit; borrower grain starts simple with business-group rollup deferred to Phase 2; cached external reference data (GLEIF) permitted; new `pipeline/borrower_resolution.py` module; ~600-packet gold set.

## Problem

Two tracking capabilities are needed on top of unified holdings:

1. **Within-fund position tracking** — follow the same instrument (loan tranche, equity stake) across quarters as held by one fund. Exists today (`position_matching.py` tier cascade A/B1/B1b/B2/C/D + `position_id` union-find) but quality is **unmeasured**: known suspects are name-drift chain breaks, ~19% singleton rate (partly structural), rank-based IDs that relabel on rebuild, and ~24K Tier-A pairs with NULL position_id.
2. **Cross-fund borrower tracking** — "show all loans to Acme Corp across funds / across multiple investments by the same fund." Barely exists: `entity_id` from `entity_resolution.py` covers ~10% of holdings because CUSIP/LEI are rare in private credit and fuzzy name clustering is deliberately conservative.

Both need a deterministic rules layer plus an agentic correction layer, mirroring the value-accuracy stack (source reconciliation → global rules → B2 per-CIK corrections → promotion gates).

100% accuracy is not expected on either capability. The goal is measured accuracy with an audited correction loop.

## Non-goals

- No changes to the v1 public headline-FV reconciliation contract. All new data is additive columns/artifacts.
- No index surfaces. This serves holdings analytics and future index work, not v1 index pages.
- No SEC EDGAR downloads. All adjudication runs against cached filings.
- Phase 1 does not attempt fuzzy cross-fund merges; those are Phase 2 agent territory with evidence requirements.

## Architecture

```
Phase 0: MEASURE        gold set + permanent match-quality metrics (independent gate)
Phase 1: DETERMINISTIC  stable position IDs + borrower_id layer + Tier E chain repair
Phase 2: AGENTIC        correction loop on residuals + borrower_group rollup
```

Each phase ships independently and gates the next. Scope: gold set and agent work run on the ~70-CIK wrapper cohort; all logic is universe-capable (cohort is a filter parameter, never hardcoded in rules).

## Phase 0 — Measurement

### Adjudication harness

Reuses the B2 worker-dispatch pattern and the shared cached-filing search primitive.

- **Packet types:**
  - *Chain packet*: all unified rows sharing a position_id chain, with accession pointers to every source filing involved. Question: is this one instrument through time?
  - *Entity-candidate packet*: a cluster of similar issuer names across funds (or within one fund). Question: are these the same borrower?
- **Sampling frame** (~600 packets: ~400 chain + ~200 entity): stratified by matching tier composition, chain length, CIK, and suspicious strata (interior singletons with non-trivial FV, within-chain FV/principal jumps, name-drift break candidates).
- **Verdicts**: `CONFIRMED` / `WRONG_MERGE` / `MISSED_LINK` (must name the counterpart row) / `INSUFFICIENT_EVIDENCE`. Every verdict carries evidence citations (accession, table/row locator, quoted text). Escalation without a verdict is a valid outcome and is not penalized.
- **Human audit**: owner reviews ~10% slice, stratified across verdict types and workers.

### Permanent metrics

New module `pipeline/match_quality.py` → `data/output/match_quality_metrics.csv`, computed on every rebuild (DuckDB, no row-level pandas):

- Chain continuity rate per CIK (adjacent-quarter presence vs chaining)
- Name-drift break-candidate count (same CIK, adjacent quarters, coherent FV/principal/rate, unchained)
- Within-chain anomaly rate (FV/principal jumps beyond guard ratios, instrument-type flips)
- Singleton decomposition (boundary / zero-FV / negative-FV structural vs interior suspicious)
- Entity layer stats (borrower coverage, cross-fund link counts, cluster purity flags)

These are deterministic signals, not truth; the gold set is truth. Both together form the Phase 2 promotion gate — agents cannot satisfy the gate by editing their own output.

### Deliverables

- `data/output/match_quality/gold_set.csv` + packet JSONs (versioned; later agent runs are never scored on packets they authored)
- Per-tier precision estimates and wrong-merge / missed-link rates
- Investigation write-up under `docs/investigations/` with dated heading

## Phase 1 — Deterministic fixes

Driven by Phase 0 measured failure modes; the three expected workstreams:

### 1. Position-ID registry to production

`pipeline/position_id_registry.py` (natural keys, mint/retire lifecycle, audit records) exists but is not live. Promote it: `position_id` becomes stable across rebuilds; `retirements.csv` records every merge/split with reason. Prerequisite for agents referencing chains by ID in Phase 2.

### 2. Borrower layer — new `pipeline/borrower_resolution.py`

Produces `borrower_lookup.csv` and two new unified-holdings columns: `borrower_id` (BOR-xxxxxxxx) and `borrower_id_method`.

Tier order (deterministic, conservative):

1. **CUSIP issuer prefix** (first 6 chars) — same issuer across funds where CUSIPs exist.
2. **LEI direct + GLEIF golden copy** — one-time download cached under `data/raw/gleif/`, DuckDB-filtered ingest (never pandas-loaded whole). Gives LEI→canonical legal name; the GLEIF relationship file additionally gives parent links, cached now to seed Phase 2 rollup.
3. **Strict exact-normalized-name match** across funds, using existing normalization rules. No fuzzy matching in this phase.

Coverage will be reported as measured, not assumed; LEI/CUSIP are boosters, not the backbone, in private credit.

### 3. Tier E chain repair

Within-CIK candidate pairs sharing `borrower_id` + instrument continuity + attribute coherence (rate/spread/maturity/principal guards) to relink name-drift chain breaks. Link-only (never merges existing chains destructively); every change is gated by re-running Phase 0 metrics against baseline and `diff_outputs.py --semantic`.

## Phase 2 — Agentic residual loop

- **Fix-classes** added to the existing correction-record schema (same JSON shape: cik, mechanism, scope, template, evidence_citations, confidence, rationale), stored under `data/output/agent_match/corrections/{CIK}/`:
  - `chain_link` — join two position_id chains (evidence: same instrument in both filings)
  - `chain_split` — split a wrong merge
  - `entity_merge` / `entity_split` — borrower cluster corrections
  - `borrower_group_assign` — assign business-group membership
- **Appliers**: pure functions in the `agent_b2_appliers.py` style — `apply_*(artifact_df, template) -> (df, audit)` — operating only on match/entity artifacts, never on holdings values. Fail-safe: bad template records an audit error and leaves the frame unchanged.
- **Worklists** generated from residuals: interior suspicious singletons, unresolved drift candidates, cross-fund near-miss clusters (fuzzy-score band below deterministic threshold).
- **Promotion gate**: independent verifier re-checks evidence citations against cached filings; gold-set metrics must not regress; blast-radius caps (max rows per correction, max corrections per CIK-quarter without escalation).
- **`borrower_group_id`** (business/economic rollup — HoldCo/Buyer/OpCo variants of one deal) lands here: seeded deterministically from GLEIF parent relationships where LEIs exist, extended by agent adjudication of holdco/sponsor evidence in filings. Two-level output: `borrower_id` (strict) rolls up to `borrower_group_id` (economic).

## Data contracts

New/changed unified-holdings columns (all additive):

| Column | Phase | Notes |
|---|---|---|
| `position_id` | 1 | becomes rebuild-stable (registry) |
| `borrower_id` | 1 | BOR-xxxxxxxx, cross-fund borrower key |
| `borrower_id_method` | 1 | cusip6 / lei / exact_name / agent |
| `borrower_group_id` | 2 | economic rollup, nullable |

New artifacts: `match_quality_metrics.csv`, `data/output/match_quality/` (gold set + packets), `borrower_lookup.csv`, `data/raw/gleif/` cache, `data/output/agent_match/` correction dirs, registry `retirements.csv`.

## Testing & verification

- Per-module pytest: metrics computation, each borrower tier (including false-positive tests per AGENTS.md — e.g., distinct companies sharing a name stem must NOT merge), appliers, registry promotion parity.
- Every data-touching change: rebuild from cache → compare `match_quality_metrics.csv` to baseline → `python scripts/diff_outputs.py --semantic`.
- Full suite before merge of each phase; proportional targeted tests as inner loop.

## Risks

- **Wrong merges corrupt per-unit return series** — the motivating risk. Mitigations: measurement before machinery, link-only deterministic repairs, split fix-classes, gold-set regression gate.
- **GLEIF scale** (multi-GB) — filtered DuckDB ingest only; cache the filtered subset.
- **Low LEI/CUSIP coverage** in private credit — expected; name tier and agents carry most coverage; report measured numbers.
- **Parallel-track collision** with Parquet PR-2 and quarter passes — Phase 0 is read-only against outputs; Phase 1 registry promotion and new columns coordinate with the Parquet companion schema when they land.
- **Adjudication-agent error** — 10% human audit slice, worker disagreement flags, escalation-is-valid framing to suppress fabricated verdicts.

## Phase acceptance

- **Phase 0 done**: 600 packets adjudicated, 10% audited, per-tier precision estimates published, `match_quality_metrics.csv` wired into rebuilds, investigation doc filed.
- **Phase 1 done**: stable position IDs live with parity check; `borrower_id` coverage measured and published; Tier E shipped with metric-gated evidence of net chain-continuity improvement and no gold-set regression.
- **Phase 2 done**: fix-classes + appliers + verifier live; first correction wave applied with audit trail; `borrower_group_id` on cohort with provenance.
