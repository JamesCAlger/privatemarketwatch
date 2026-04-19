# Private Market Watch — Next Steps Plan

**Created:** 2026-04-18
**Status:** Active

## Phase 1: Data Cleanup (1-2 days)

Priority data fixes before any frontend work.

### 1.1 Exclude Consumer Lending CIKs
- Remove CIKs 0001678130, 0001644771, 0002041175 from unified holdings
- 406K rows of noise, <$2.4B FV, opaque numeric IDs
- Add exclusion list to `unified_holdings.py`

### 1.2 Limit BDC Data to 2022+
- Pre-2022 BDC XBRL is unreliable (partial coverage, phased-in tagging)
- N-PORT starts 2019q4 and is structured from day one — keep all
- Net effect: cleaner dataset, accurate date range disclosure

### 1.3 Reclassify N-PORT UNCLASSIFIED
- $433B FV (26% of N-PORT) sitting in UNCLASSIFIED
- Audit `OTHER` ($198B), `EC` ($108B), `RE` ($87B) asset_cat codes
- Many are likely classifiable as DIRECT_EQUITY, PRIVATE_EQUITY_FUND, or a new REAL_ESTATE category

### 1.4 Fix N-PORT Entity Resolution
- entity_id coverage: 97.5% for BDC but only 46.4% for N-PORT
- N-PORT names are cleaner — should be higher, not lower
- Investigate entity_resolution.py thresholds for N-PORT name formats
- Target: 85%+ coverage

### 1.5 Rebuild All Outputs
- Single rebuild after all fixes: `python scripts/rebuild_outputs.py`
- Regenerate: unified holdings, position matches, index returns, frontend JSON

## Phase 2: Fund Financials (1-2 days, parallel with Phase 1)

### 2.1 Pull Fund-Level KPIs from SEC companyfacts API
- Endpoint: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json`
- ~330 API calls (168 BDCs + 160 interval/tender funds)
- Extract per-CIK quarterly time series:
  - NAV / NAV per share
  - Net investment income (NII)
  - Total investment income
  - Distributions per share
  - Total assets / total debt
  - Shares outstanding
  - Asset coverage ratio
- Output: `data/output/fund_financials.csv`
- New module: `pipeline/fund_financials.py`

### 2.2 Extract Unfunded Commitments from Cached XBRL
- Concepts already in XBRL but not extracted:
  - `InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount` (826 instances in Ares)
  - `InvestmentCompanyFundedCommitments`
  - `InvestmentCompanyNetAdjustedUnfundedCommitments`
- Position-level unfunded exposure is a key risk metric
- Can extract from cached XBRL files (no network needed)

## Phase 3: Fund Pages (3-5 days)

### 3.1 Export Fund-Level JSON
- New function in `export_frontend.py`
- `funds_index.json`: directory listing (name, CIK, type, FV, positions, NAV, yield)
- `fund_detail_{cik}.json`: per-fund KPIs, top 20 holdings, FV time series, composition

### 3.2 Build `/funds` Directory Page
- Searchable, sortable table of ~330 funds
- Filter by vehicle type (BDC / interval / tender offer)
- Sort by FV, NAV, yield, position count

### 3.3 Build `/funds/[cik]` Detail Page
- Fund KPIs (NAV, yield, leverage, fees)
- Holdings table (top 20 free, full behind paywall later)
- FV history chart
- Composition donut (asset class split, including non-private-markets for context)
- Vehicle type label (BDC vs Interval Fund)

## Phase 4: Investee / Cap Table Pages (3-5 days)

Depends on Phase 1.4 (entity_id fix).

### 4.1 Build `/companies` Directory
- 20,793 canonical entities
- Search by company name
- Sort by aggregate FV, fund count

### 4.2 Build `/companies/[entity_id]` Detail Page
- Canonical company name
- Total FV across all funds
- Per-fund breakdown (Fund A: $50M 1st lien at SOFR+550, Fund B: $30M 2nd lien)
- Valuation dispersion (do funds mark differently?)
- Time series of aggregate exposure
- Asset class breakdown per borrower

## Phase 5: Downloadable Data + API Foundation (1-2 days)

### 5.1 Data Downloads Page (`/data`)
- XBRL-era unified holdings CSV (free)
- Index returns CSV (free)
- Entity lookup table (free)
- Optional email gate for tracking

### 5.2 API Groundwork
- Defer full API until paying customers exist
- Start with static JSON endpoints served from Vercel

## Phase 6: Credit Quality Analytics (2-3 days)

### 6.1 Extract Additional XBRL Credit Concepts
From cached XBRL files (no network):
- Non-accrual status (460+ data points across BDCs, multiple concept names)
- Interest rate floors (`InvestmentInterestRateFloor`)
- Unfunded commitments (see Phase 2.2)
- Concentration risk percentages

### 6.2 Extract N-PORT Credit Flags into Unified Holdings
Already in raw TSV but not fully propagated:
- `IS_DEFAULT` (position-level default flag)
- `ARE_ANY_INTEREST_PAYMENT_IN_ARREARS` (arrears flag)
- `IS_ANY_PORTION_INTEREST_PAID_IN_KIND` (PIK flag)
- Consider: `MONTHLY_RETURN_CAT_INSTRUMENT` table (monthly realized/unrealized gains)

### 6.3 Build Credit Quality Dashboard
- Impairment trend (% of positions FV/cost < 0.90 by quarter)
- Spread compression chart (median basis_spread by quarter)
- PIK share of total coupon trend
- Vintage analysis (impairment curves by origination cohort)
- Default/arrears trend (N-PORT flags)
- Seniority breakdown with impairment rates

### 6.4 Credit Quality Video Data Package
Key charts for video (see data analysis in conversation 2026-04-18):
1. Impairment trend: 12.4% (2023q1) → 21.0% (2025q4)
2. Spread compression: 6.00% → 5.00% (100bps in 3 years)
3. PIK share: 21.7% → 29.1% of total coupon
4. Vintage curves: 2024-2025 cohorts at 20-22% initial impairment
5. Seniority hierarchy: 1st lien 8%, 2nd lien 18.6%, mezz 22.8%
6. Rate decomposition: 260bps all-in decline = 100bps spread + 170bps base

## Future Considerations

### Monetization Path
- Free tier: indices, fund directory, top 20 holdings, downloadable CSVs
- Paid tier ($5-20K/yr): full position detail, cross-fund search, API access
- Target customers: allocators, BDC managers, credit hedge funds, academics

### Data Quality Improvements
- HTML template engine amendments (30+ proposed, ~50 hrs for all)
- Would extend coverage to pre-XBRL era (~89% recall)
- Lower priority than product features above

### Additional Data Sources
- SEC companyfacts API for fund financials (Phase 2)
- N-PORT monthly return tables
- N-CEN fund characteristics (fee structures, redemption terms)
- 13F institutional ownership data (who owns the BDCs themselves?)
