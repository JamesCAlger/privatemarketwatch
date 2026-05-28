# Phase Completion History

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

## Phase 1 Complete: Universe Discovery

The pipeline identifies **581 entities** from multiple independent SEC data sources:

| Vehicle Type | Count | Discovery Method |
|---|---|---|
| BDCs | 423 | N-54A/N-54C elections, 814- file numbers, XBRL concept scan |
| Interval Funds | 123 | N-CEN classification, N-2 index scan, EFTS text search |
| Tender Offer Funds | 35 | N-CEN classification, N-2 index scan, EFTS text search |

Cross-validated against third-party lists (Interval Fund Tracker, Tender Offer Funds, Sure Dividend).

## Phase 2 Complete: Holdings Extraction

**BDC holdings (done):** 10-K/10-Q XBRL filings parsed for all 423 BDCs.

| Metric | Value |
|---|---|
| Filings indexed | 6,437 across 271 CIKs |
| XBRL files downloaded | 2,775 (3,662 older filings lack XBRL) |
| Filings with holdings | 1,739 |
| Total holding records | 1,040,369 |
| Unique CIKs with data | 191 |
| Unique investees | 267,981 |
| Date range | ~2022 onward (SEC phased in BDC XBRL requirements) |

**N-PORT holdings (done):** 835,234 holdings extracted from quarterly TSV data sets across 2019q4-2025q4.

## Phase 3 Complete: Unified Holdings & Validation

`data/output/private_markets_holdings.csv` unifies BDC + N-PORT into **718,089 rows** with 2-axis classification (`exposure_type`, `asset_class`) + `index_classification`, cross-source dedup, affiliation-axis dedup, pct_of_net_assets correction, NUSS name-gated government mapping, and L.P. co-keyword fund detection. Built via `python -m pipeline.main --unified` using DuckDB SQL CTEs (no pandas .apply).

| Index | Rows | % |
|---|---|---|
| DIRECT_LENDING | 561,450 | 78.2% |
| COMMON_EQUITY | 66,921 | 9.3% |
| UNCLASSIFIED | 26,772 | 3.7% |
| PREFERRED_EQUITY | 25,762 | 3.6% |
| STRUCTURED_CREDIT | 15,245 | 2.1% |
| PRIVATE_EQUITY_FUND | 15,211 | 2.1% |
| PRIVATE_CREDIT_FUND | 3,013 | 0.4% |
| REAL_ESTATE_FUND | 2,733 | 0.4% |
| CASH | 617 | 0.1% |
| HEDGE_FUND | 261 | 0.0% |
| DIRECT_REAL_ESTATE | 104 | 0.0% |

Quarters: 2019q4-2026q1.

## Phase 4 Complete: Position Matching & Index Construction

See `private_markets_index_spec.md` Phase 4 for full detail. Key findings from data analysis:

**Total return methodology** (matching public credit index conventions): price return (FV change) + income return (estimated coupon accrual) + principal return (paydown/repayment). All major public credit indices (Morningstar LSTA, ICE BofA HY, Bloomberg Agg) use total return as their flagship measure.

**BDC comparative period data:** 91% of BDC XBRL filings contain both current-period and prior-period schedule-of-investments facts under the same `investmentidentifieraxis` typed dimension. 196K position-pairs have FV in both periods. This is filer-matched position data requiring no external matching. Rows where `period < report_date` are prior-period comparatives, not duplicates.

**Position matching cascade:** Within-filing comparatives (BDC) > CUSIP (N-PORT, 47%) > exact issuer_name (N-PORT 98.5% carry, BDC 78%) > normalised name + composite key > LLM company extraction (for unstructured identifiers) > FV proximity. See spec for full method descriptions and coverage/accuracy metrics.

## Phase 5 Complete: Data Quality Audit

Full data quality and code-level transformation audit completed (`data/output/audit_data_quality.md`). All FAIL and WARN findings have been actioned and resolved.

## Phase 6 Complete: Compatibility Cleanup Refactor

Phase 6 removed compatibility wrappers and completed the classification/staging decomposition without changing current-cache outputs. Verification is documented in `docs/2026-05-16/phase6_current_cache_parity.md`.

Required evidence:
- Phase-6-only current-cache parity: `Diff clean: 418 checked`, `Semantic delta rows: 0`.
- Same-code reproducibility after determinism fixes: clean, `418 checked`, `0` semantic deltas.
- Full tests: `1868 passed, 13 skipped`.
- Active official baseline refreshed after archiving the stale baseline.

The old official baseline is historical-only:
- `data/snapshots/baseline_pre_phase6_stale_2026-05-16/`
- `docs/refactoring/baseline_manifest_pre_phase6_stale_2026-05-16.json`

The active baseline is deterministic post-Phase-6 output:
- `data/snapshots/baseline/`
- `docs/refactoring/baseline_manifest.json`
