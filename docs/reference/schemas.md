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
