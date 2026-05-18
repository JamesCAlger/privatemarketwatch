# Private Markets Data Platform — SEC XBRL Pipeline

## Project Goal

Build a data platform for SEC-registered private markets vehicles (BDCs, interval funds, tender offer funds) with private markets indices derived from the data. The pipeline discovers all such vehicles, extracts investee-level portfolio holdings from their structured filings, and computes fund-level analytics, portfolio characteristics, and position-level indices.

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

**Validation status:** V1-V5 all implemented. See "Unified Holdings -- Validation" section below.

### Phase 5 Complete: Data Quality Audit

Full data quality and code-level transformation audit completed (`data/output/audit_data_quality.md`). All FAIL and WARN findings have been actioned and resolved.

### Phase 6 Complete: Compatibility Cleanup Refactor

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
| `pipeline/bdc_filings.py` | BDC 10-K/10-Q XBRL download and parse; HTML filing download |
| `pipeline/html_extract.py` | v3.0 HTML template extraction engine |
| `pipeline/validate_html_template.py` | HTML template validation: self-referential subtotal check, companyfacts aggregate check, carry rate, position count stability, FV fill, extraction coverage. Structured fail_reasons/warn_reasons. |
| `pipeline/nport_holdings.py` | N-PORT quarterly TSV extraction |
| `pipeline/unified_holdings.py` | Unified BDC + N-PORT holdings with classification, named co-invest reclassification, cross-source dedup, affiliation-axis dedup, and pct_of_net_assets correction |
| `pipeline/validate_holdings.py` | Holdings validation: spot-check, classification summary, aggregate audit, cross-source overlap, coverage, 2-axis classification cross-reference + LLM audit |
| `pipeline/position_matching.py` | 4-tier position matching cascade (within-filing, CUSIP, exact name, normalized/fuzzy) |
| `pipeline/index_returns.py` | Index return computation: per-unit price return, income return (3-tier rate imputation + PIK + fee uplift) |
| `pipeline/bdc_fund_income.py` | Fund-level income extraction from cached XBRL (no network) |
| `pipeline/bdc_sector_breakdown.py` | Per-industry aggregate data (FV, cost, % of net assets) from XBRL `EquitySecuritiesByIndustryAxis`. See [`docs/bdc_sector_breakdown.md`](./docs/bdc_sector_breakdown.md) |
| `pipeline/fee_uplift.py` | Per-CIK fee uplift: residual between fund income yield and coupon yield |
| `pipeline/ncsr_financials.py` | N-CSR/N-CSRS Financial Highlights parser: filing discovery, HTML download, FH table extraction (vertical/horizontal/split-table/broadened search), per-share NII, distributions, NAV, expense ratios, total return |
| `pipeline/fund_financials.py` | Fund financial data from companyfacts/N-PORT/N-CEN/N-CSR with YTD conversion, seed filtering, scale harmonization, schema enforcement |
| `pipeline/entity_resolution.py` | Entity resolution across data sources |
| `pipeline/identifier_extraction.py` | BDC investment identifier parsing (company name, type, industry extraction) |
| `pipeline/llm_review.py` | LLM-assisted review of unclassified/ambiguous holdings |
| `pipeline/export_frontend.py` | Export pipeline data to frontend JSON format |
| `pipeline/utils.py` | Shared utilities (UnionFind for position ID chaining) |
| `pipeline/db.py` | Database utilities |
| `pipeline/main.py` | CLI orchestrator |

### Tests

**1,956 passing tests** across 27 test files, with 13 skips in the latest full run (2026-05-18). Run with `pytest tests/`. Tests cannot overwrite production data -- a monkeypatch guard in `tests/conftest.py` intercepts `builtins.open` and `io.open` at import time and raises `AssertionError` on any write-mode open targeting `data/output/` or `frontend/public/data/`. The guard is validated by 8 dedicated tests in `test_test_output_isolation.py`.

| Test file | Tests | Coverage |
|---|---|---|
| `test_unified_holdings.py` | 583 | Identifier parsing, aggregate filtering, classification (2-axis + nport_asset_cat refinement + NUSS name-gating + L.P. co-keyword), dedup, shares normalization, cost proxy, affiliation prefix strip, affiliation dedup, pct_of_net_assets correction |
| `test_ncsr_financials.py` | 135 | N-CSR FH parsing: row labels, value parsing, period detection, layout detection, table finding, vertical/horizontal/split-table extraction, broadened search, dollar units, guard rails, dedup, filing index |
| `test_entity_resolution.py` | 119 | Entity resolution across sources |
| `test_fund_financials.py` | 111 | Fund financial data extraction, YTD conversion, seed filter, scale harmonization, schema enforcement |
| `test_bdc_filings.py` | 96 | XBRL parsing, concept mapping, filing index, download, CLI |
| `test_html_extract.py` | 88 | v3.0 extraction engine, table parsing, column mapping, dollar/rate parsing |
| `test_nport_holdings.py` | 75 | TSV reading, date normalization, quarter processing, XML parsing |
| `test_gics_classification.py` | 67 | GICS sector/industry classification |
| `test_validate_holdings.py` | 56 | Spot-check, aggregate audit, cross-source overlap, coverage |
| `test_validate_html_template.py` | 53 | Template validation gates, fail_reasons, summary persistence |
| `test_gics_mapping.py` | 50 | GICS code mapping and lookup |
| `test_position_matching.py` | 49 | 4-tier cascade, 1:1 enforcement, name multiplicity cap, position ID chaining |
| `test_index_returns.py` | 45 | Per-unit price return, income imputation, PIK, fee uplift |
| `test_bdc_sector_breakdown.py` | 35 | Context parsing, member name normalization, fact extraction, integration |
| `test_llm_review.py` | 33 | LLM review candidate selection and processing |
| `test_bdc_fund_income.py` | 27 | Fund income extraction from XBRL |
| `test_identifier_extraction.py` | 24 | BDC identifier parsing |
| `test_db.py` | 10 | Database utilities |
| `test_fee_uplift.py` | 9 | Fee uplift computation and guard rails |
| `test_gold_standard.py` | 6 | Gold standard validation |

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
    private_markets_holdings.csv       # 718,089 unified holdings (326 MB)
    position_matches.csv               # Position matching pairs (541K pairs)
    position_returns.csv               # Per-position total returns
    index_returns.csv                  # Quarterly index returns (4 indices, 25 quarters)
    bdc_fund_income.csv                # Fund-level income from XBRL
    fee_uplift.csv                     # Per-CIK fee uplift (128 CIKs)
    ncsr_filings_index.csv             # 2,376 N-CSR/N-CSRS filing metadata
    ncsr_financials.csv                # 1,974 Financial Highlights records (177 CIKs)
    fund_financials.csv                # Fund financial data from companyfacts/N-CSR
    bdc_sector_breakdown.csv           # Per-CIK per-industry aggregate FV/cost/% from XBRL
    xbrl_data_availability.md          # XBRL concept coverage matrix across all sources
    companyfacts_concept_catalog.md    # Full catalog of 1,262 XBRL concepts from companyfacts
    html_template_validation.csv       # Per-filing HTML extraction results
    html_template_validation_summary.csv  # Per-CIK validation summary (PASS/FAIL + reasons)
    template_claims.json               # CIK claim status for template work (done/claimed)
    html_template_extract_progress.csv # HTML extraction progress checkpoint
    entity_lookup.csv                  # Entity resolution lookup
    identifier_extraction_lookup.csv   # BDC identifier parsing results
    bdc_parse_progress.csv             # XBRL parse resumability checkpoint
    validation_report.csv              # Third-party cross-validation
    pipeline.log                       # Last run log
  raw/
    filings/bdc_xbrl/{cik}/*.xml       # Cached XBRL instance documents (~2,775 files)
    filings/bdc_html/{cik}/*.html      # Cached HTML filings for template extraction
    filings/bdc_html/{cik}/*.grids.json # Parsed table grids (cell text arrays)
    filings/ncsr_html/{cik}/*.html     # Cached N-CSR/N-CSRS HTML filings
    sec_datasets/                      # SEC bulk data ZIPs (BDC, N-CEN, N-PORT)
    n2_headers_cache/                  # Downloaded N-2 cover pages
    third_party/                       # Interval Fund Tracker, Sure Dividend CSVs
    filing_templates/<CIK>.json        # v3.0 HTML extraction templates (~201 CIKs)
    filing_templates/<CIK>.auto_detect.txt  # Context output for template validation
    filing_templates/v2_archived/      # Archived v2.0 templates
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

`data/output/private_markets_holdings.csv` (718,089 rows). Run via `python -m pipeline.main --unified --validate`.

**Status:** V1-V7 all implemented.
- **V1 (UNCLASSIFIED reduction):** Implemented. 2.5% UNCLASSIFIED (down from 16.3%). BDC financial field fallback, N-PORT issuer defaulting, named co-invest reclassification, expanded fund keyword lists.
- **V2 (Spot-check accuracy):** Manual validation against top BDCs and interval/tender funds HTML/PDF filings.
- **V3 (Aggregate filtering):** Manual pattern discovery and filter expansion.
- **V4 (Cross-source dedup):** Implemented. Jaro-Winkler name matching + FV proximity. BDC source preferred. Output: `holdings_cross_source.csv`.
- **V5 (Coverage):** Implemented. Total assets ratio validation (0.8-1.2x expected). Output: `holdings_coverage.csv`, `holdings_total_assets.csv`.
- **V6 (2-axis classification):** Implemented. Two new columns: `exposure_type` (DIRECT/FUND/LIQUID) and `asset_class` (PRIVATE_CREDIT/PRIVATE_EQUITY/REAL_ESTATE/STRUCTURED_CREDIT/HEDGE_FUND/CASH/OTHER). Expanded `index_classification` with 5 new values (REAL_ESTATE_FUND, DIRECT_REAL_ESTATE, STRUCTURED_CREDIT, HEDGE_FUND, CASH). Uses `nport_asset_cat` (EC/EP/RE/DBT/LON) to refine HEDGE_FUND catch-all. Cross-reference validation (10 rules, runs with `--validate`) + one-time LLM audit (GPT-4o-mini). Output: `classification_validation.csv`, `classification_llm_audit.csv`. NUSS issuer_type is now name-gated (only GOVERNMENT when name has govt keyword; eliminates A1/E1 disagreements). L.P. suffix requires fund co-keyword to trigger FUND reclassification (prevents SPV misclassification). Known residual: 231 E2 disagreements (issuer_category=FUND but exposure_type!=FUND) from three causes: (1) 86 money market fund positions (Goldman Sachs Financial Square, Vanguard Federal Money Market, etc.) that have issuer_category=FUND but exposure_type=LIQUID+asset_class=CASH -- correctly classified for index purposes; (2) 43 BDC aggregate headers ("Investments in Non-Controlled, Non-Affiliated Portfolio Companies") that leaked through aggregate filtering and carry issuer_category=FUND from the affiliation dimension; (3) 90 misc positions where issuer_category=FUND comes from N-PORT PF/RF tagging but the position is a direct lending/equity position in an operating company (e.g., "AffiniPay Intermediate Holdings, LLC" tagged PF by filer).
- **V7 (Affiliation-axis dedup + pct correction):** Implemented. Fixes FV inflation from affiliation-axis duplication (12 CIKs) via 3 mechanisms: affiliation prefix/suffix stripping from `_raw_id`, expanded `_BAD_ISSUER_NAMES_EXACT`, and ROW_NUMBER dedup over (cik, report_date, issuer_name, FV). Corrects `pct_of_net_assets` for multi-dimension-path BDCs (263 CIK-quarters, 116K rows) by recalculating with consolidated `net_assets` from `fund_financials.csv`. Dimension-path duplicates resolved by `no_dim_dupes` CTE (case/punctuation-normalized key excluding cost) + majority casing vote in `_prepare_bdc` + N-PORT cross-quarter dedup via `nport_deduped` CTE. Cost proxy made deterministic with per-tranche partition key (instrument_description + cusip) and fair_value tiebreaker. Tier A within-filing position matching case-folded to recover 2,386 cross-period pairs that previously fell to lower-confidence tiers.

All validation functions use DuckDB SQL (no pandas .iterrows/.apply). See MEMORY.md for detailed implementation notes.

## Known Limitations

- **BDC XBRL coverage starts ~2022-2023.** The SEC phased in investment-level XBRL tagging for BDCs. Pre-2022 filings are plain HTML with no structured data. Some 2022-2023 filings have only aggregate XBRL (category-level totals, not individual positions). HTML template extraction covers pre-XBRL filings back to 2013.
- **HTML template coverage is per-CIK.** Each BDC requires a v3.0 template mapping its specific table layout. ~3,662 pre-XBRL filings across ~190 CIKs need templates. Templates are created via `--auto-detect` + manual validation.
- **Industry/type/affiliation are mostly empty.** Most BDCs embed this metadata in the `investment_identifier` string (e.g., "Senior Secured Loans | First Lien | Acme Corp | Technology") rather than using separate XBRL dimensions. Parsing these out requires string splitting, which is filer-specific.
- **N-PORT consumer/marketplace lending positions.** Four N-PORT CIKs (0001658645 Stone Ridge Trust V, 0001678130 RiverNorth/DoubleLine, 0001644771 RiverNorth series, 0002041175 NB Asset-Based Credit) report individual consumer loans with opaque numeric IDs. These are excluded from unified holdings at the staging level via `NPORT_EXCLUDE_CIKS` in `config.py`. The data is preserved in `nport_holdings.csv` but filtered out during `--unified`. The frontend export additionally filters via `CONSUMER_LENDING_EXCLUDE_CIKS` in `pipeline/export/helpers.py`.
- **2 BDCs with holdings but missing from unified.** Two CIKs have `bdc_holdings.csv` rows but do not appear in `private_markets_holdings.csv`: (1) Terra Income Fund 6 (0001577134, 10 rows) -- all rows are prior-period comparatives with no current-period data; (2) Lord Abbett Private Credit Fund S (0002041841, 157 rows) -- aggregate-only XBRL where position-level rows have NULL across all financial fields. Both exclusions are correct. Lord Abbett is a candidate for HTML template extraction (~55 positions, $319M total). The original 20 missing CIKs (Investigation #5) were reduced to 2 by aggregate filter improvements.
- **Multi-dimension-path BDC duplicates (resolved).** BDCs that tag the same position under multiple XBRL dimension hierarchies are handled by the `no_dim_dupes` CTE in `unified_holdings.py` (case/punctuation-normalized partition key excluding cost) and the `_canonical_casing` CTE in `staging_bdc.py` (majority casing vote per CIK). These BDCs show `pct_of_net_assets` sums of 200-400% (corrected using consolidated `net_assets` from fund_financials). Residual: 48 rows with non-deterministic cost proxy from upstream dedup tie-breaking (0.007% of total).

## Resumability

All three phases of holdings extraction are resumable:
- **Filing index:** Cached to CSV, skipped if < 24h old
- **XBRL downloads:** Cached per-file in `data/raw/filings/bdc_xbrl/`, skipped if file exists and > 1KB
- **Parsing:** Progress tracked in `bdc_parse_progress.csv`, only unparsed filings are processed

## Contracts

These are harm-category restrictions. Violating them causes data loss, silent corruption, or external service abuse.

- **No unwanted network calls.** Do not trigger SEC EDGAR downloads unless the user explicitly asks. All raw data is cached on disk. Use `scripts/rebuild_outputs.py` or call pipeline functions directly to rebuild outputs.
- **No production data corruption.** Pytest installs a monkeypatch guard (`tests/conftest.py`) that replaces `builtins.open` and `io.open` with wrappers blocking any write-mode open (`w`, `a`, `x`, `+`) to `data/output/` or `frontend/public/data/`. This covers all standard Python write paths (`open()`, `Path.write_text()`, `pandas.to_csv()`, `json.dump()`, etc.). Verified 2026-05-18: 1,956 tests passed with zero production files modified. After running tests, run `python scripts/diff_outputs.py --semantic` as a backstop to confirm no artifact drift.
- **Baseline governance.** The active baseline is the deterministic post-Phase-6 snapshot. Do not compare new work against `baseline_pre_phase6_stale_2026-05-16` except for historical investigation. Refresh `data/snapshots/baseline/` only after rebuilding from cached inputs, running `python scripts/diff_outputs.py --semantic`, documenting semantic deltas, and preserving the prior baseline if it is being retired.
- **No SEC rate-limit violations.** The existing `edgar_client.py` enforces 10 req/sec. Do not bypass it or add parallel request paths.
- **No encoding crashes.** All log messages must use ASCII only — Windows cp1252 cannot render Unicode box-drawing, em-dashes, or ellipsis characters.
- **No slow transforms on large datasets.** Avoid pandas `.apply()`, `.iterrows()`, or row-level Python loops on datasets with >10K rows — the pipeline's 800K+ row datasets will hang for minutes. Use DuckDB SQL or vectorized operations. Pandas is fine for small summaries and logging.

## HTML Template Extraction (v3.0)

Per-CIK JSON templates in `data/raw/filing_templates/<CIK>.json` map HTML schedule-of-investments tables to standardized fields.

- **Engine:** `pipeline/html_extract.py` (~580 lines). Simple table reader: template specifies tables and columns.
- **Validation:** `pipeline/validate_html_template.py`. Multi-gate checks (self-referential FV, companyfacts, carry rate, position stability, FV fill, coverage).
- **Template format, creation workflow, and validation details:** See `prompts/html_extraction/learn_template_prompt.md`.
- **Fixing failing templates:** See `prompts/html_extraction/rework_template_prompt.md`.
- **Period tagging:** See `prompts/html_extraction/tag_periods_prompt.md`.
- **CLI:** `scripts/learn_template.py` (`--auto-detect`, `--validate`, `--next`, `--inspect`, `--accept`, `--revalidate-all`, `--add-periods`, `--list`).

## XBRL Data Source Discovery (Complete)

Full coverage matrix produced in `data/output/xbrl_data_availability.md` and `data/output/companyfacts_concept_catalog.md` (2026-05-03). Key findings:

- **BDC companyfacts**: Rich -- 80+ XBRL concepts covering balance sheet, income statement, distributions, fees, portfolio metrics. 191 CIKs with data. Already extracted by `fund_financials.py`.
- **Interval/tender fund companyfacts**: Empty -- these funds file N-PORT/N-CEN, not 10-K/10-Q, so companyfacts API returns no data.
- **N-CEN**: 103+ fields not yet extracted (expense ratios, flow data, leverage, board/adviser details). Covers interval/tender funds that companyfacts misses.
- **N-PORT**: Monthly NAV, total assets, borrowings already extracted. Additional fields available (credit ratings, liquidity classification, delta, DV01).
- **BDC bulk datasets**: Monthly TSVs with balance sheet, income statement, per-share data. Partially overlaps companyfacts but at different granularity.

## Oversubscription / Redemption Pressure

See **[`docs/oversubscription_data.md`](./docs/oversubscription_data.md)** for full analysis of data availability for fund-level oversubscription rates. Summary: N-PORT gives a binary cap signal for interval funds (already in `fund_financials.csv` as `redemption_pressure`); exact demand-side data requires parsing SC TO-I/A filings (non-traded BDCs, tender offer funds) and N-CSR/N-CSRS narratives (interval funds).

## Next Steps

See **[`NEXT_STEPS.md`](./NEXT_STEPS.md)** for the longer-term product roadmap (fund pages, investee pages, credit quality analytics, monetization).

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
| `scripts/snapshot_outputs.py` | Refresh the active deterministic official baseline after approval. Archive the prior baseline first if retiring it. | `python scripts/snapshot_outputs.py --clean` |
| `scripts/diff_outputs.py` | Compare current outputs with the active official baseline, including generated SQL and optional semantic summaries. | `python scripts/diff_outputs.py --semantic` |
| `scripts/current_cache_phase6_parity.py` | One-off current-cache pre/post comparator for Phase 6-style refactor parity. Use named snapshots under `data/snapshots/`, not the official baseline. | `snapshot --clean --snapshot-dir ...`, `diff --semantic --snapshot-dir ...` |
| `scripts/learn_template.py` | Manage per-CIK HTML extraction templates. Auto-detect, validate, inspect, accept, batch revalidate. | `--auto-detect <CIK>`, `--auto-detect-all`, `--validate <CIK>`, `--validate-only <CIK>`, `--next`, `--inspect <CIK>`, `--accept <CIK> --justification "..."`, `--revalidate-all`, `--add-periods <CIK\|ALL>`, `--list` |
