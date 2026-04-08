# Private Markets Index — SEC XBRL Pipeline

## Project Goal

Build private market indices from SEC regulatory filings. The pipeline discovers all SEC-registered vehicles investing in private markets (BDCs, interval funds, tender offer funds) and extracts investee-level portfolio holdings from their structured filings.

**IMPORTANT: The indices are at the POSITION level -- each constituent is an individual loan or equity investment (e.g., "Acme Corp Senior Secured First Lien Term Loan"), NOT aggregated at the company/borrower level.** A single company may appear multiple times in the index if a fund holds multiple positions in it (e.g., a first lien term loan, a second lien term loan, and an equity co-invest are three separate index constituents). This mirrors how public credit indices like the Morningstar LSTA Leveraged Loan Index work: each loan tranche is a separate constituent, not rolled up to the issuer.

See `private_markets_index_spec.md` for the full specification including the four target indices.

## Current State

### Phase 1 Complete: Universe Discovery

The pipeline identifies **581 entities** from multiple independent SEC data sources:

| Vehicle Type | Count | Discovery Method |
|---|---|---|
| BDCs | 423 | N-54A/N-54C elections, 814- file numbers, XBRL concept scan |
| Interval Funds | 123 | N-CEN classification, N-2 index scan, EFTS text search |
| Tender Offer Funds | 35 | N-CEN classification, N-2 index scan, EFTS text search |

Cross-validated against third-party lists (Interval Fund Tracker, Tender Offer Funds, Sure Dividend).

### Phase 2 Complete: Holdings Extraction

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

### Phase 3 Complete: Unified Holdings & Validation

`data/output/private_markets_holdings.csv` (326 MB) unifies BDC + N-PORT into **835,067 rows** with asset/issuer/index classification and cross-source dedup. Built via `python -m pipeline.main --unified` using DuckDB SQL CTEs (no pandas .apply).

| Index | Rows | % |
|---|---|---|
| DIRECT_LENDING | 753,334 | 90.2% |
| DIRECT_EQUITY | 57,746 | 6.9% |
| UNCLASSIFIED | 17,840 | 2.1% |
| PRIVATE_EQUITY_FUND | 4,803 | 0.6% |
| PRIVATE_CREDIT_FUND | 1,344 | 0.2% |

Sources: N-PORT 460,802 (55.2%) + BDC 374,265 (44.8%). 22,327 cross-source dupes removed. 237 CIKs with holdings / 583 universe entities. Quarters: 2019q4-2025q4.

**Validation status:** V1-V5 all implemented. See "Unified Holdings -- Validation" section below.

### Phase 5 Complete: Data Quality Audit

Full data quality and code-level transformation audit completed (`data/output/audit_data_quality.md`). All FAIL and WARN findings have been actioned and resolved.

### Phase 4 Complete: Position Matching & Index Construction

See `private_markets_index_spec.md` Phase 4 for full detail. Key findings from data analysis:

**Total return methodology** (matching public credit index conventions): price return (FV change) + income return (estimated coupon accrual) + principal return (paydown/repayment). All major public credit indices (Morningstar LSTA, ICE BofA HY, Bloomberg Agg) use total return as their flagship measure.

**BDC comparative period data:** 91% of BDC XBRL filings contain both current-period and prior-period schedule-of-investments facts under the same `investmentidentifieraxis` typed dimension. 196K position-pairs have FV in both periods. This is filer-matched position data requiring no external matching. Rows where `period < report_date` are prior-period comparatives, not duplicates.

**Position matching cascade:** Within-filing comparatives (BDC) > CUSIP (N-PORT, 47%) > exact issuer_name (N-PORT 98.5% carry, BDC 78%) > normalised name + composite key > LLM company extraction (for unstructured identifiers) > FV proximity. See spec for full method descriptions and coverage/accuracy metrics.

## Pipeline Architecture

```
python -m pipeline.main                  # Fast universe discovery (~5 min)
python -m pipeline.main --exhaustive     # All 6 discovery methods (~45-60 min)
python -m pipeline.main --holdings       # + BDC XBRL extraction (~1-3 hrs first run)
python -m pipeline.main --ciks 1418076   # Holdings for specific CIKs only
python -m pipeline.main --unified        # Build unified private markets holdings (~60s)
```

### Modules

| Module | Purpose |
|---|---|
| `pipeline/config.py` | Paths, URLs, constants |
| `pipeline/edgar_client.py` | Rate-limited SEC EDGAR HTTP client |
| `pipeline/bdc_universe.py` | BDC discovery (3 methods) |
| `pipeline/fund_universe.py` | Interval/tender fund discovery (6 methods) |
| `pipeline/third_party.py` | Cross-validation lists |
| `pipeline/merge.py` | Universe merge, dedup, validation |
| `pipeline/bdc_filings.py` | BDC 10-K/10-Q XBRL download and parse |
| `pipeline/nport_holdings.py` | N-PORT quarterly TSV extraction |
| `pipeline/unified_holdings.py` | Unified BDC + N-PORT holdings with classification, named co-invest reclassification, and cross-source dedup |
| `pipeline/validate_holdings.py` | Holdings validation: spot-check, classification summary, aggregate audit, cross-source overlap, coverage |
| `pipeline/main.py` | CLI orchestrator |

### Tests

`tests/test_bdc_filings.py` — 88 tests covering XBRL parsing, concept mapping, filing index building, download logic, and CLI integration.
`tests/test_nport_holdings.py` — 60 tests covering TSV reading, date normalisation, quarter processing, XML parsing, and CLI integration.
`tests/test_unified_holdings.py` — 155 tests covering identifier parsing, aggregate filtering, asset/issuer/index classification, coupon type inference, named co-invest/LP reclassification, BDC/N-PORT preparation, and full integration.
`tests/test_validate_holdings.py` — 32 tests covering spot-check sampling, per-CIK summary, aggregate leak audit, cross-source overlap with duplicate detection, coverage with total assets ratio, and orchestrator integration.
Run with `pytest tests/`.

## Data Layout

```
data/
  output/                              # Pipeline outputs
    combined_universe.csv              # 581 entities (master list)
    combined_universe.json
    bdc_universe.csv                   # 423 BDCs
    fund_universe.csv                  # 158 interval/tender funds
    bdc_filings_index.csv              # 6,437 filing metadata records
    bdc_holdings.csv                   # 1,040,369 investee-level positions (365 MB)
    nport_holdings.csv                 # 835,234 N-PORT holdings
    private_markets_holdings.csv       # 835,067 unified holdings (326 MB)
    bdc_parse_progress.csv             # Resumability checkpoint
    validation_report.csv              # Third-party cross-validation
    pipeline.log                       # Last run log
  raw/
    filings/bdc_xbrl/{cik}/*.xml       # Cached XBRL instance documents (~2,775 files)
    sec_datasets/                      # SEC bulk data ZIPs (BDC, N-CEN, N-PORT)
    n2_headers_cache/                  # Downloaded N-2 cover pages
    third_party/                       # Interval Fund Tracker, Sure Dividend CSVs
```

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

## Unified Holdings -- Validation

`data/output/private_markets_holdings.csv` (835,067 rows). V1-V5 are implemented. Run via `python -m pipeline.main --unified --validate`.

### V1. Reduce UNCLASSIFIED rate (currently 1.9%, 23K rows)

V1 heuristics are now **implemented**: BDC financial field fallback (interest_rate/basis_spread/principal -> LOAN, shares -> EQUITY), N-PORT LON/DBT+OTHER issuer defaulting to CORPORATE, named co-invest reclassification (~1K rows FUND->EQUITY), expanded credit/PE fund keyword lists. UNCLASSIFIED reduced from 16.3% to 1.9%.

**Implemented:** Named co-invest/LP interest reclassification -- ~1,056 FUND rows with identifiable operating companies (Inc., LLC, Corp., Holdings, etc.) are reclassified to EQUITY_COMMON/EQUITY_PREFERRED + CORPORATE, resulting in DIRECT_EQUITY index classification. Opaque fund positions remain as PRIVATE_CREDIT_FUND/PRIVATE_EQUITY_FUND.

**Target:** Reduce UNCLASSIFIED from 16.3% to < 5%.

### V2. Spot-check classification accuracy

For the top 10 BDCs by AUM (Ares Capital, Owl Rock, FS KKR, Blue Owl, Golub, Blackstone Secured Lending, etc.):

1. Pull one recent 10-K filing's schedule of investments (HTML or PDF)
2. Compare a sample of 20-30 holdings against `private_markets_holdings.csv` rows for that CIK/period
3. Verify: issuer_name matches, asset_class correct, fair_value matches, no duplicate/missing rows
4. Document error rate per filer and any systematic misclassifications

For the top 5 interval/tender offer funds by AUM:

1. Pull one recent N-PORT filing
2. Compare 20-30 holdings against the unified dataset
3. Verify issuer_type and asset_cat mapping to index classification

### V3. Aggregate/subtotal filtering

1. Sample 20 BDC filers and grep their `investment_identifier` values for subtotal patterns (e.g., "Total", "Sub-total", "Subtotal", category headers like "Senior Secured First Lien")
2. Identify any new subtotal patterns not caught by the current 6-pattern filter
3. Add new patterns and re-run; measure row count change

### V4. Cross-source deduplication -- IMPLEMENTED

**Detection (`validate_holdings.py`):** `check_cross_source_overlap()` now returns two DataFrames: overlap summary (CIKs with row counts per source) and duplicate holdings (pairs matched by CIK + report_date + jaro_winkler_similarity > 0.85 on issuer_name, with pct_diff on fair_value). Saved to `holdings_cross_source.csv`.

**Dedup (`unified_holdings.py`):** `build_unified_holdings()` includes a dedup CTE after UNION ALL. Within the same CIK + report_date + issuer_name + ROUND(fair_value, -2), only the BDC-source row is kept (BDC XBRL preferred over N-PORT TSV for BDCs that file both).

### V5. Coverage and completeness -- IMPLEMENTED

**Coverage (`validate_holdings.py`):** `check_coverage()` now includes total assets comparison:
- N-PORT: `reported_net_assets` from `nport_fund_info.csv` (max net_assets per CIK)
- BDC: estimated from `sum(fair_value) / (sum(pct_of_net_assets) / 100)` for the latest report_date
- `holdings_to_assets_ratio` column: expected 0.8-1.2x for healthy CIKs; outliers flagged at > 2.0 or < 0.3

All validation functions use DuckDB SQL (no pandas .iterrows/.apply). Output CSVs: `holdings_coverage.csv`, `holdings_total_assets.csv`.

## Known Limitations

- **BDC XBRL coverage starts ~2022-2023.** The SEC phased in investment-level XBRL tagging for BDCs. Pre-2022 filings are plain HTML with no structured data. Some 2022-2023 filings have only aggregate XBRL (category-level totals, not individual positions).
- **Industry/type/affiliation are mostly empty.** Most BDCs embed this metadata in the `investment_identifier` string (e.g., "Senior Secured Loans | First Lien | Acme Corp | Technology") rather than using separate XBRL dimensions. Parsing these out requires string splitting, which is filer-specific.
- **N-PORT holdings not yet extracted.** The SEC's quarterly N-PORT data set covers only one quarter per ZIP. Full historical coverage requires downloading multiple quarters.

## Resumability

All three phases of holdings extraction are resumable:
- **Filing index:** Cached to CSV, skipped if < 24h old
- **XBRL downloads:** Cached per-file in `data/raw/filings/bdc_xbrl/`, skipped if file exists and > 1KB
- **Parsing:** Progress tracked in `bdc_parse_progress.csv`, only unparsed filings are processed

## Key Technical Notes

- **Windows cp1252:** All log messages must use ASCII only — no Unicode box-drawing, arrows, em-dashes, or ellipsis characters.
- **CONCEPT_MAP ordering:** Longer XBRL concept substrings must appear before shorter ones (e.g., `investmentinterestratepaidinkind` before `investmentinterestrate`) because matching is first-match-wins.
- **lxml Comment nodes:** `root.iter()` yields Comment/PI nodes whose `.tag` is a callable, not a string. Always guard with `isinstance(tag, str)`.
- **SEC rate limit:** 10 req/sec max. Client uses 0.11s delay between requests.
- **DuckDB for large-dataset manipulation:** All data transformations on datasets >10K rows must use DuckDB SQL (CTEs, native string/numeric functions) rather than pandas .apply(), .iterrows(), or row-by-row lambdas. Python keyword constants remain the single source of truth; SQL is generated from them. Pandas is acceptable for final logging/summary only.
- **Tests overwrite output CSVs:** Several integration tests (e.g., `test_bdc_fund_income.py::test_single_filing_integration`, `test_index_returns.py`, `test_fee_uplift.py`) call pipeline functions that write to the real output files (`bdc_fund_income.csv`, `fee_uplift.csv`, `position_matches.csv`, `position_returns.csv`, `index_returns.csv`). Running `pytest` will overwrite production data with test fixtures. After running the test suite, run `python scripts/rebuild_outputs.py` to regenerate all output files from cached data.
- **Do NOT download data unless explicitly asked:** When rebuilding outputs, use `scripts/rebuild_outputs.py` or call pipeline functions directly (e.g., `build_unified_holdings()`, `compute_returns()`). Do NOT run `python -m pipeline.main` with download flags or call functions that trigger SEC EDGAR downloads unless the user explicitly requests it. All raw data is already cached on disk.

## Data Investigations

Ad-hoc data analyses (e.g., classification stability, outlier deep-dives, coverage checks) should be saved to `data/output/data_investigation_results.md`. Append each new investigation with a numbered heading, the question asked, and the results found.

## Frontend

Next.js 14 dashboard in `frontend/`. Reads static JSON from `frontend/public/data/`.

```
cd frontend
npm run dev -- -p 3004    # Dev server at http://localhost:3004
npm run build             # Static export to frontend/out/
```

## Scripts

| Script | Purpose | Usage |
|---|---|---|
| `scripts/rebuild_outputs.py` | Rebuild all output CSVs from cached data (no downloads). Use after running tests. | `python scripts/rebuild_outputs.py` (all), `--unified`, `--income`, `--returns` |
