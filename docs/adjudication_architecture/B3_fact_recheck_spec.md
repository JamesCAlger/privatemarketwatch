# B3 Fact Recheck — Design Spec (2026-08-22)

Owner-approved direction from the 2026-08-21/22 session: give the B3 gate a mechanical
check that corrected (and all other) holdings values match the filer's own XBRL facts,
with mismatches routed back to agents rather than auto-refused.

## Problem

The B3 gate today proves conservation and replay-equivalence but has no predicate for
"the leaf's effect matches the source." Two defects shipped past it in 2026-08-21
canaries: a semantic no-op leaf (gate PASS twice with zero substantive change) and an
inverted rate_rescale factor (0.1 vs 10) that only intake-schema checks saw. Both are
mechanically detectable by comparing row values against the filer's tagged facts.

## Design: three-way triangulation, triage not oracle

Three independent representations of each SOI row exist in cached data:

1. **Extracted holdings row** (unified frame) — what our pipeline produced.
2. **Tagged XBRL facts** (cached instance XML, already parsed by
   `pipeline.bdc_filings.CONCEPT_MAP` via
   `pipeline.source_reconciliation.extract_bdc_source_facts_from_xbrl`) — what the
   filer tagged, including `InvestmentInterestRatePaidInKind`, `...PaidInCash`,
   `InvestmentInterestRate`, `InvestmentBasisSpreadVariableRate`, floor, reference
   type, `pct_of_net_assets`.
3. **Rendered SOI text** (same cached HTML the SAV verifier parses).

CRITICAL CAVEAT (circularity): our BDC rows originate from the same tags, so a
tag-recheck is NOT an independent oracle for filer tag errors (the 0001588272 CCS row:
tag 0.016 is itself wrong; the truth is in rendered text + footnote). Therefore:

- **MISMATCH never auto-refuses a leaf.** It generates an agent handback packet citing
  the fact (concept, context, value) and the holdings row. Agents adjudicate
  tag-vs-text; SAV covers the tag-is-wrong direction.
- What the recheck DOES prove mechanically: our transforms did not mangle a
  correctly-tagged fact (column displacement, scale errors, dedup/dimension
  duplication, bad corrections, no-op corrections).

## Per-(row, field) outcomes

| Status | Meaning | Gate effect |
|---|---|---|
| `match` | holdings value == fact x field scale (rel tol) | green |
| `mismatch_scale` | matches fact x a DIFFERENT power of 10 | handback packet; gate predicate counts it |
| `mismatch_value` | no power-of-10 of the fact matches | handback packet; gate predicate counts it |
| `not_covered` | no fact tagged / ambiguous join / mixed tag semantics | recorded, never fails |

Coverage is reported honestly per CIK-quarter (n_match / n_mismatch / n_not_covered).

## Gate predicates (phase 2)

Added to `run_remediation gate` as a `fact_recheck` block (opt-in flag first; default
after calibration). Both computed on the TARGET quarter only:

- `fact_mismatch_non_increasing`: mismatch count (trial) <= mismatch count (baseline).
- `corrected_rows_fact_effect`: every row selected by the correction's row_selector
  that was `mismatch_*` in baseline and is fact-covered must be `match` in trial.
  This is the no-op killer: a leaf that changes nothing leaves its rows mismatching.
  Rows `not_covered` are excluded (recorded as `effect_not_assessable`).

MISMATCH rows in the trial append to
`data/output/agent_b2/fact_mismatch_worklist.csv` (append-only, like the
re-adjudication worklist) — the agent handback the owner specified.

## Semantics layer

- Field scales (holdings unit / fact unit): interest_rate 100, pik_rate 100,
  pct_of_net_assets 100, basis_spread 10000 (bps vs decimal) — CALIBRATED per Phase 1
  measurement task, not assumed; the comparator records which power-of-10 matched.
- Mixed tag semantics: CIKs whose `data/overrides/rate_convention/<cik>.json` marks
  mixed/unknown interest_rate semantics get `not_covered/mixed_semantics` for
  interest_rate (9 known CIKs + 24 unknowns). PIK and spread still compared.
- Join: source facts to holdings rows on (cik, report_date, normalized identifier)
  using `source_reconciliation._norm_identifier_sql`; ambiguous joins (n>1 either
  side) -> `not_covered/ambiguous_join`. Join coverage is a reported metric.

## Phase 3 (separate plan, after 1-2 calibrate)

`ix:nonFraction` DOM parser over cached HTML (name/scale/sign/context + rendered
table/row position) to densify the XBRL-HTML bridge, plus composed-rate verification
(all-in = base + spread; base from tagged benchmark, footnote parse, or
`data/raw/reference_rates`) wired to the per-CIK convention registry and identifier
grammars. Measured 2026-08-22: tag vocabularies vary sharply per filer (Blue Owl 887
spread facts; NexPoint zero), so per-filer capability detection is mandatory and
`not_covered` is a first-class outcome, not a failure.

## Non-goals

- Not a replacement for SAV (rendered-text anchoring) or the conservation gate.
- Never edits verdicts, never auto-refuses on mismatch, never touches production
  outputs (pure read + new artifact files).
- No SEC downloads: cached XML/HTML only.
