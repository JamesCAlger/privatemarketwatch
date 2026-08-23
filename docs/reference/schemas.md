# Schemas & Validation Details

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

## BDC Holdings Schema (`bdc_holdings.csv`)

| Column | Type | Description |
|---|---|---|
| `cik` | str | SEC CIK |
| `entity_name` | str | BDC name |
| `accession_number` | str | SEC filing accession number |
| `form_type` | str | 10-K, 10-Q, etc. |
| `filing_date` | str | Date filed with SEC |
| `report_date` | str | Period of report |
| `period` | str | XBRL context instant date |
| `investment_identifier` | str | Typed dimension value (investee name + metadata) |
| `fair_value` | float | Fair value |
| `cost` | float | Cost basis |
| `principal_amount` | float | Principal/par amount |
| `interest_rate` | float | Stated interest rate |
| `basis_spread` | float | Spread over reference rate |
| `reference_rate_type` | str | SOFR, PRIME, etc. |
| `maturity_date` | str | Maturity date |
| `shares_held` | float | Number of shares |
| `pct_of_net_assets` | float | % of net assets |
| `unrealized_gain_loss` | float | Unrealized appreciation/depreciation |
| `pik_rate` | float | PIK interest rate |
| `industry` | str | Industry axis (rarely populated; usually in identifier) |
| `investment_type` | str | Investment type axis (rarely populated) |
| `affiliation` | str | Issuer affiliation (rarely populated) |
| `dimensions_raw` | str | Full XBRL dimension string for audit |
| `src_context_id` | str | XBRL contextRef of the winning dedup row (2026-08-22). With `accession_number`, locates the fact context in the cached filing. Primary-of-N when `dedupe_context_count` > 1; `''` for rows built before the anchor migration or merged from a legacy CSV. |

## Row Identity (`row_id` / `row_id_basis`, unified holdings)

`private_markets_holdings.csv` appends two columns AFTER `UNIFIED_COLUMNS`
(they are not in the constant by design; `_assign_row_ids` is the final build
step and re-runs after `assign_position_ids` re-saves):

- `row_id` = `ROW-` + first 16 hex chars of md5 over the row's source anchor:
  `source|accession_number|src_context_id` for BDC rows,
  `source|accession_number|nport_holding_id` for N-PORT rows.
  The anchor names the filing fact context, so the id survives rebuilds,
  staging reorders, promoted corrections, and parser fixes. It is an
  **as-filed claim**: an amendment (new accession) is a new id by design.
- `row_id_basis` = `src_anchor` when the anchor exists, else `natural_key` --
  the legacy fallback hash over `position_id_registry.compute_natural_keys`
  (content-sensitive: a corrected principal changes a fallback row's id).
- `row_id` is a within-build row name, not a cross-quarter identity --
  `position_id` owns that layer and is unchanged.
- Migration tooling: `scripts/restamp_row_selectors.py` maps legacy
  natural-key ids cited in correction-leaf `row_selector`s to anchor ids.
- Source-reconciliation published ids (2026-08-22): detail artifacts carry
  `source_row_id` = `src:{accession_number}:{context_id}` (stable grounding
  anchor; `#k` suffix on within-frame duplicate contexts, `src-ord:{n}`
  fallback when a part is missing) and `output_row_id` = the unified
  `row_id` when available. The positional ordinals remain internal to the
  reconciliation SQL only. Correction-leaf `positions[].source_row_id`
  citations copy the published anchor verbatim; the value gate re-verifies
  by string equality + fair_value tolerance against a grounding frame that
  is now independently re-derivable from the source-facts cache.

## Position-Level PIK Status

PIK outputs intentionally separate strict current-payment/accrual evidence from schedule-rate proxy metrics:

- `position_pik_status.csv` is one row per holding-quarter. `pik_current_status` is `paying`, `not_paying`, or `unknown` based on N-PORT paid-in-kind flags or BDC position-level PIK income/accrual/capitalization facts. BDC fund-level PIK income does not mark individual positions as paying.
- `pik_terms_flag` and `pik_terms_rate` come from disclosed schedule PIK terms (`pik_rate > 0`). These are useful for research comparability but are not proof of current-period PIK income.
- `pik_schedule_proxy_summary.csv` is the S&P-style public-filing proxy. The headline comparable denominator is BDC direct-lending fair value. Latest rebuild: 2025-12-31 BDC direct lending has 3,939 PIK-terms rows out of 50,200, with PIK-terms FV of $57.27B on $512.58B total FV (11.17%).
- `pik_schedule_proxy_transitions.csv` reports `pik_terms_started`, meaning the same `position_id` moved from no PIK terms to PIK terms. This is a "PIK terms started proxy," not confirmed bad PIK. Confirmed bad PIK needs amendment/origination evidence showing cash-pay terms changed due to borrower stress.

## Unified Holdings -- Validation

`data/output/private_markets_holdings.csv` (718,089 rows). Run via `python -m pipeline.main --unified --validate`.

**Status:** V1-V7 all implemented.
- **V1 (UNCLASSIFIED reduction):** Implemented. 2.5% UNCLASSIFIED (down from 16.3%). BDC financial field fallback, N-PORT issuer defaulting, named co-invest reclassification, expanded fund keyword lists.
- **V2 (Spot-check accuracy):** Manual validation against top BDCs and interval/tender funds HTML/PDF filings.
- **V3 (Aggregate filtering):** Manual pattern discovery and filter expansion.
- **V4 (Cross-source dedup):** Implemented. Jaro-Winkler name matching + FV proximity. BDC source preferred. Output: `holdings_cross_source.csv`.
- **V5 (Coverage):** Implemented. Total assets ratio validation (0.8-1.2x expected). Output: `holdings_coverage.csv`, `holdings_total_assets.csv`.
- **V6 (2-axis classification):** Implemented. Two new columns: `exposure_type` (DIRECT/FUND/LIQUID) and `asset_class` (PRIVATE_CREDIT/PRIVATE_EQUITY/REAL_ESTATE/STRUCTURED_CREDIT/HEDGE_FUND/CASH/OTHER). Expanded `index_classification` with 5 new values (REAL_ESTATE_FUND, DIRECT_REAL_ESTATE, STRUCTURED_CREDIT, HEDGE_FUND, CASH). Uses `nport_asset_cat` (EC/EP/RE/DBT/LON) to refine HEDGE_FUND catch-all. Cross-reference validation (10 rules, runs with `--validate`) + one-time LLM audit (GPT-4o-mini). Output: `classification_validation.csv`, `classification_llm_audit.csv`. NUSS issuer_type is now name-gated (only GOVERNMENT when name has govt keyword; eliminates A1/E1 disagreements). L.P. suffix requires fund co-keyword to trigger FUND reclassification (prevents SPV misclassification). Known residual: 231 E2 disagreements (issuer_category=FUND but exposure_type!=FUND) from three causes: (1) 86 money market fund positions (Goldman Sachs Financial Square, Vanguard Federal Money Market, etc.) that have issuer_category=FUND but exposure_type=LIQUID+asset_class=CASH -- correctly classified for index purposes; (2) 43 BDC aggregate headers ("Investments in Non-Controlled, Non-Affiliated Portfolio Companies") that leaked through aggregate filtering and carry issuer_category=FUND from the affiliation dimension; (3) 90 misc positions where issuer_category=FUND comes from N-PORT PF/RF tagging but the position is a direct lending/equity position in an operating company (e.g., "AffiniPay Intermediate Holdings, LLC" tagged PF by filer).
- **V7 (Affiliation-axis dedup + pct correction):** Implemented. Fixes FV inflation from affiliation-axis duplication (12 CIKs) via 3 mechanisms: affiliation prefix/suffix stripping from `_raw_id`, expanded `_BAD_ISSUER_NAMES_EXACT`, and ROW_NUMBER dedup over (cik, report_date, issuer_name, FV). Corrects `pct_of_net_assets` for multi-dimension-path BDCs (263 CIK-quarters, 116K rows) by recalculating with consolidated `net_assets` from `fund_financials.csv`. Dimension-path duplicates resolved by `no_dim_dupes` CTE (case/punctuation-normalized key excluding cost) + majority casing vote in `_prepare_bdc` + N-PORT cross-quarter dedup via `nport_deduped` CTE. Cost proxy made deterministic with per-tranche partition key (instrument_description + cusip) and fair_value tiebreaker. Tier A within-filing position matching case-folded to recover 2,386 cross-period pairs that previously fell to lower-confidence tiers.

All validation functions use DuckDB SQL (no pandas .iterrows/.apply).

## Provenance Passthrough Columns (step 1, 2026-08-23)

Six new columns appended to `UNIFIED_COLUMNS` after `src_context_id`.
Populated by a single `--unified` rebuild; no re-extraction required.
Upgrade path: these flat-tag columns fold into `src_facts` (per-field
JSON with instance-raw values) when the extractor migration ships.

### Dedup carry-throughs (from `bdc_holdings.csv`)

| Column | Type | Description |
|---|---|---|
| `src_context_count` | str | Number of XBRL contexts deduplicated into this row (`dedupe_context_count` passed through from bdc_holdings). Empty for N-PORT and for BDC rows built before the dedup audit. |
| `src_conflict_fields` | str | Comma-joined field names where deduplicated contexts disagreed on value (`dedupe_conflict_fields` pass-through). Empty when all contexts agreed or only one context existed. |

### Pipeline transform events (`src_transforms`)

Flat `;`-joined ordered list of `field:code` events recording which
pipeline heuristic fired on which field. One entry per branch that fired;
silent when the field passed through unchanged. Event/value CASE
conditions are colocated in `staging_bdc.py` Phase C and in the
`unified_pik_fixed`, `with_cost`, and `with_shares_fix` CTEs.

**Event vocabulary v1** (fires in this field order where applicable):

| Event code | Field | Condition | Effect |
|---|---|---|---|
| `interest_rate:neg_null` | `interest_rate` | raw < 0 | set to NULL |
| `interest_rate:rate_x100` | `interest_rate` | raw <= 0.50 | multiply by 100 |
| `interest_rate:rate_div100` | `interest_rate` | raw >= 50 | divide by 100 |
| `basis_spread:neg_null` | `basis_spread` | raw < 0 | set to NULL |
| `basis_spread:rate_x100` | `basis_spread` | raw <= 0.50 | multiply by 100 |
| `basis_spread:rate_div100` | `basis_spread` | raw >= 50 | divide by 100 |
| `pik_rate:neg_null` | `pik_rate` | raw < 0 | set to NULL |
| `pik_rate:rate_x100` | `pik_rate` | raw <= 0.50 | multiply by 100 |
| `pik_rate:rate_div100` | `pik_rate` | raw >= 50 | divide by 100 |
| `pct_of_net_assets:rate_x100` | `pct_of_net_assets` | raw <= 0.50 | multiply by 100 |
| `pct_of_net_assets:rate_div100` | `pct_of_net_assets` | raw > 50 (strict) | divide by 100 |
| `pik_rate:pik_boundary_div100` | `pik_rate` | pik >= 20 AND pik > interest_rate | divide by 100 (bps->pct fix, appended by `unified_pik_fixed` CTE) |
| `cost:cost_proxy_fv` | `cost` | cost NULL/zero but FV proxy available | cost filled from FV proxy (appended by `with_cost` CTE) |
| `shares_held:pow10_shares` | `shares_held` | shares >30x deviation from issuer median | pow-10 outlier corrected (appended by `with_shares_fix` CTE) |

Note: `pct_of_net_assets` uses a strict `> 50` threshold for the div/100
branch (not `>= 50`); all rate fields use `>= 50`. This asymmetry is
enforced by boundary tests in `tests/test_unified_holdings.py`.

### Class-C pathway enums

| Column | Type | Values | Description |
|---|---|---|---|
| `cost_source` | str | `''` or `'derived_proxy'` | `'derived_proxy'` when `with_cost` CTE filled a NULL/zero cost from the cross-quarter FV proxy. Extends the existing `*_source` enum pattern used by `interest_rate_source`, `basis_spread_source`, etc. |
| `shares_held_source` | str | `''` or `'derived_proxy'` | `'derived_proxy'` when `with_shares_fix` CTE applied a pow-10 correction to an outlier shares value. |

Rows where `cost_source='derived_proxy'` or `shares_held_source='derived_proxy'`
should be excluded from verified-FV numerators that require independently
confirmed position economics (per scoping doc accounting rule).

### Bridge overlay coordinate refs (`src_field_overrides`)

| Column | Type | Grammar | Description |
|---|---|---|---|
| `src_field_overrides` | str | `;`-joined `field=bridge:<sha8>:t<T>:r<R>` | Written by `apply_html_section_bridge_field_overlays` for each field overridden by the HTML-section bridge. `<sha8>` = first 8 chars of the HTML file's sha256; `<T>` = table index; `<R>` = row index within the bridge table. Empty when no bridge overlay applied to this row. |

Example: `maturity_date=bridge:a1b2c3d4:t2:r15` means `maturity_date`
was sourced from the HTML bridge file whose sha256 starts `a1b2c3d4`,
table 2, row 15.

### Coverage stats (2026-08-23 rebuild, 780,726 rows)

Measured from `private_markets_holdings.parquet` via `scratch/2026-08-23_prov_step1/coverage_stats.py`.

| Metric | Count |
|---|---|
| interest_rate:rate_x100 events | 357,833 |
| interest_rate:rate_div100 events | 0 |
| interest_rate:neg_null events | 8 |
| basis_spread:rate_x100 events | 395,670 |
| basis_spread:rate_div100 events | 1 |
| basis_spread:neg_null events | 75 |
| pik_rate:rate_x100 events | 45,940 |
| pik_rate:rate_div100 events | 0 |
| pik_rate:neg_null events | 24 |
| pct_of_net_assets:rate_x100 events | 299,629 |
| pct_of_net_assets:rate_div100 events | 0 |
| pik_rate:pik_boundary_div100 events | 14 |
| cost:cost_proxy_fv events | 252,559 |
| shares_held:pow10_shares events | 2,847 |
| Total rows with any src_transforms event | 730,363 (93.6%) |
| cost_source='derived_proxy' | 252,559 |
| shares_held_source='derived_proxy' | 2,847 (historical baseline ~1,902 pre-rebuild) |
| src_context_count > 1 | 103,365 |
| src_conflict_fields non-empty | 8 |
| src_field_overrides non-empty | 0 (bridge overlay had no matches in this cohort) |

### Known limitations

- **Values populated on rebuild only.** All six provenance columns are empty strings in cached
  `bdc_holdings.csv` rows generated before this migration. They are populated correctly on any
  full `--unified` rebuild from cached extraction data; partial rebuilds or legacy CSV imports
  may leave the columns empty.
- **Ordinal tie-break residual.** The 2026-08-23 rebuild produced four `src_anchor` row_id flips
  at CIK 0000081955 / 2025-12-31 (and cost/shares deltas at ~13 CIK-quarters across 7 CIKs:
  0001321741, 0001414932, 0001578348, 0000081955, 0001655050, 0001496099 et al.) due to DuckDB
  physical row-order perturbation hitting pre-existing order-sensitive tie-breaks in dedup/pick
  layers. All deltas are ACCEPTED as the same residual class as the 8 ordinal flips in the
  2026-08-22 anchor-row_id migration. Future hardening: deterministic ORDER BY in tie-break
  windows (not done in step 1).
