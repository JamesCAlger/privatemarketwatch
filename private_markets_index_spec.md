# Private Markets Index: Implementation Specification

## Project Overview

Build a free, open-source set of private market indices derived entirely from structured SEC regulatory filings. The indices benchmark the performance of underlying investee companies held by SEC-registered vehicles (BDCs, interval funds, tender offer funds) that invest in private credit and private equity.

### Target Indices

**Index 1 — Direct Lending**: Tracks the performance of individual direct loan positions (first lien, second lien, unitranche, mezzanine) to operating companies. Sourced from BDC XBRL filings and interval/tender offer fund N-PORT filings. Fields: borrower name, instrument type, coupon, spread over reference rate, maturity, principal, cost basis, fair value. Returns computed as change in fair value plus accrued income (estimated from stated coupon) divided by beginning-period fair value.

**Index 2 — Direct Equity**: Tracks the performance of direct equity and preferred equity co-investments in operating companies. Same sources as Index 1. Returns computed from fair value changes.

**Index 3 — Private Credit Funds**: Tracks the NAV performance of private credit fund vehicles (e.g., Golub Capital Private Credit Fund, HPS Corporate Lending Fund) as marked by their holding vehicles. Sourced from N-PORT filings where `issuerCat` = `private fund` or `registered fund` and fund name is classified as a credit strategy.

**Index 4 — Private Equity Funds**: Same as Index 3 but for PE/buyout fund vehicles.

All four indices share a common data infrastructure, entity resolution layer, and index construction methodology.

### Data Sources

1. **BDC XBRL filings** (10-K, 10-Q): Schedule of Investments with investee-level detail. Filed on EDGAR. The SEC publishes a pre-extracted BDC Data Set at https://www.sec.gov/data-research/sec-markets-data/bdc-data-sets but the SOI table drops investee-level granularity for most filers. The raw XBRL instance documents contain full position-by-position data. The standard XBRL tags for values (InvestmentOwnedFairValue, InvestmentOwnedCost, etc.) are consistent across filers. Individual investee names are custom extension members on the typed dimension `Investment, Identifier [Axis]`.

2. **N-PORT filings** (Form N-PORT): Monthly portfolio holdings for all registered management investment companies (except money market funds and SBICs). Filed on EDGAR in XML format. The SEC publishes pre-extracted N-PORT Data Sets at https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets. Each holding has structured fields including `assetCat` (loan, equity-common, equity-preferred, debt, etc.) and `issuerCat` (corporate, private fund, registered fund, etc.) that enable clean classification. Holdings include issuer name, CUSIP/LEI where available, fair value, cost, and asset/issuer type.

3. **N-CEN filings** (Form N-CEN): Annual census of all registered investment companies. Contains fund classification, strategy, structure (interval fund, tender offer fund, etc.). Used for universe identification and cross-validation.

4. **EDGAR filing index**: Master index of all filings, used to discover the universe by observed filing behaviour rather than relying on pre-built lists.

### Key Design Principles

- **Universe defined by observed filing behaviour**, not by static lists. If an entity files relevant forms with relevant content, it's in the universe.
- **Entity resolution across vehicles**: The same borrower held by multiple BDCs and interval funds should be deduplicated using fuzzy matching and LLM-assisted classification.
- **Investee-level granularity**: The indices track individual company positions, not fund-level aggregates (except Indices 3 and 4 which deliberately track fund vehicles).
- **Separation of direct investments from fund investments**: Using N-PORT `assetCat` and `issuerCat` fields and BDC XBRL taxonomy axes.
- **Quarterly frequency** (moving to monthly as N-PORT monthly data becomes available).

---

## Phase 1: Universe Identification

### Objective

Identify the complete universe of SEC-registered vehicles that invest in private markets, using Q2 2025 data as the initial period, then extending to all historical data back to the earliest available filings (BDC data from August 2022 onward, N-PORT data from 2019 onward).

### Approach: Define Universe by Observed Filing Behaviour

Do NOT rely solely on any single pre-built SEC list (BDC Report, N-CEN dataset, etc.). Instead, discover the universe from multiple independent signals in the raw EDGAR data, then cross-validate.

### Step 1.1: Identify BDCs from EDGAR

#### Method A: EDGAR Full-Text Search for BDC Election Filings

Query the EDGAR full-text search API (https://efts.sec.gov/LATEST/search-index) for:
- Form type `N-54A` (notification of election to be a BDC) — gives all entities that have ever elected BDC status.
- Form type `N-54C` (notification of withdrawal of BDC election) — gives all entities that have withdrawn.
- Active BDCs = entities with N-54A but no subsequent N-54C.

For each entity, capture: CIK, entity name, date of election, filing number.

#### Method B: EDGAR Filing Index Scan for BDC Periodic Reports

Scan the EDGAR full filing index for Q2 2025 (and then all historical quarters) for:
- Form types: `10-K`, `10-K/A`, `10-Q`, `10-Q/A`
- Where the filing entity has a file number beginning with `814-`

The `814-` file number prefix is assigned by the SEC specifically to entities regulated under the Investment Company Act as BDCs. This is the same filter the SEC's BDC Data Set uses.

Capture: CIK, entity name, accession number, form type, filing date, period of report.

#### Method C: Cross-validate with SEC BDC Report

Download the SEC's BDC Report from https://www.sec.gov/about/opendatasetsshtmlbdc. Compare the CIK list against Methods A and B. Investigate any discrepancies:
- Entities in Methods A/B but not in the BDC Report may be newly elected BDCs or data lag.
- Entities in the BDC Report but not filing 10-K/10-Q may be shell BDCs, pre-operational BDCs, or recently deregistered.

#### Method D: Cross-validate with BDC Data Set SUB table

Download the SEC's BDC Data Set from https://www.sec.gov/data-research/sec-markets-data/bdc-data-sets. The SUB (submissions) table lists every BDC XBRL filing. Compare CIKs against Methods A-C.

#### Output

A consolidated BDC universe table:

```
bdc_universe:
  - cik: str (10-digit)
  - entity_name: str
  - file_number: str (814-XXXXX)
  - election_date: date (from N-54A)
  - withdrawal_date: date | null (from N-54C, if any)
  - status: enum (active, withdrawn, dormant)
  - first_periodic_filing: date
  - last_periodic_filing: date
  - discovery_methods: list[str] (which methods identified this entity)
  - filings: list of {accession_number, form_type, period, filed_date}
```

### Step 1.2: Identify Interval and Tender Offer Funds from EDGAR

#### Method A: N-PORT Filing Scan

Scan the EDGAR filing index for all `NPORT-P` form type filings for Q2 2025 (period ending June 2025). This captures every registered management investment company filing portfolio holdings.

For each filing, extract the series ID and registrant CIK. This is the broadest possible net — it includes mutual funds, ETFs, and other vehicles we don't want, alongside the interval and tender offer funds we do want.

#### Method B: Filter Using N-CEN Classification

Download the N-CEN Data Set from https://www.sec.gov/data-research/sec-markets-data/form-n-cen-data-sets. Filter for entities that identify as:
- Closed-end fund (not open-end, not ETF, not UIT)
- Interval fund (operates under Rule 23c-3)
- Conducts continuous offering under Rule 415(a)(1)(ix) (captures tender offer funds)

Cross-reference the N-CEN entity list with the N-PORT filers from Method A. Entities filing N-PORT that are classified as closed-end interval or tender offer funds in N-CEN are candidates.

#### Method C: N-2 Registration Statement Scan

Search EDGAR for `N-2` form type filings. Form N-2 is the registration form for closed-end funds and BDCs. The form includes checkboxes for:
- "Registered Closed-End Fund"
- "Business Development Company"
- "Interval Fund"

Parse N-2 filings to identify which entities have registered as interval funds. This catches funds that may have registered but not yet filed N-PORT (new launches).

#### Method D: Content-Based Filtering of N-PORT Holdings

For each N-PORT filing from a confirmed interval/tender offer fund, inspect the holdings to determine if the fund invests in private markets:
- Holdings with `assetCat` = `loan` and `issuerCat` = `corporate` → private credit (direct lending)
- Holdings with `assetCat` in (`equity-common`, `equity-preferred`) and `issuerCat` = `corporate` with no CUSIP or with unlisted status → private equity
- Holdings with `issuerCat` in (`private fund`, `registered fund`) → fund-of-fund exposure to private markets
- Holdings with liquidity classification = `illiquid` or `less liquid` → likely private market positions

A fund where a material portion of holdings (e.g., >25% of fair value) are classified as loans to corporates, equity in corporates without public identifiers, or interests in private funds should be included in the universe.

#### Method E: Cross-validate with SEC Investment Company Series and Class Data

Download from https://www.sec.gov/open/datasets-investment_company. This maps every registered investment company to its series and share classes. Use it to link N-CEN, N-PORT, and N-2 data via common identifiers (CIK, series ID, class ID).

#### Output

A consolidated interval/tender offer fund universe table:

```
fund_universe:
  - cik: str
  - series_id: str
  - entity_name: str
  - fund_name: str (series name)
  - fund_type: enum (interval, tender_offer, listed_cef, other)
  - invests_in_private_markets: bool
  - primary_strategy: enum (direct_lending, private_equity, fund_of_funds,
                            real_estate_credit, multi_strategy, other)
  - pct_private_holdings: float (% of portfolio in private market assets)
  - first_nport_filing: date
  - last_nport_filing: date
  - discovery_methods: list[str]
  - filings: list of {accession_number, form_type, period, filed_date}
```

### Step 1.3: Build Combined Universe

Merge the BDC universe and interval/tender offer fund universe into a single registry. Note that some entities may appear in both (a BDC that is also an interval fund files both 10-Q and N-PORT).

```
combined_universe:
  - entity_id: str (internal unique ID)
  - cik: str
  - entity_name: str
  - vehicle_type: enum (bdc, interval_fund, tender_offer_fund, listed_cef)
  - data_sources: list[enum] (xbrl_10k, xbrl_10q, nport)
  - status: enum (active, inactive, merged)
  - active_periods: list of date ranges
  - total_fair_value_latest: float (most recent total portfolio fair value)
```

### Step 1.4: Historical Extension

After establishing the Q2 2025 universe, extend backward:

1. For BDCs: The BDC Data Set covers reporting periods from August 2022 onward. The EDGAR filing index covers all historical filings. Scan backward quarter by quarter.

2. For interval/tender offer funds: N-PORT data is available from 2019 onward. Scan backward quarter by quarter.

3. Track entity lifecycle events: new launches (first filing), mergers (entity stops filing, another entity's portfolio grows), name changes (same CIK, different name), deregistrations (N-54C filing or last filing date).

### Implementation Notes

#### EDGAR API Endpoints

- Full-text search: `https://efts.sec.gov/LATEST/search-index?q=...&forms=...&dateRange=custom&startdt=...&enddt=...`
- Company search by CIK: `https://data.sec.gov/submissions/CIK{cik_padded}.json`
- Filing index (quarterly): `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/company.idx`
- XBRL companion files: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json`

#### Rate Limiting

EDGAR requests require a `User-Agent` header with contact information. Rate limit is 10 requests per second. Implement respectful throttling.

#### Data Storage

See the Data Architecture section below. Phase 1 outputs live in Layer 2 (the parsed data lake) as universe registry tables. Raw filings downloaded during universe discovery are stored in Layer 1 (the raw filing archive).

#### Validation Criteria

The universe identification is considered complete for a given quarter when:
1. Every entity in the SEC's BDC Report for that period appears in the BDC universe (or has been investigated and excluded with documented reason).
2. Every entity in the N-CEN dataset classified as an interval/tender offer fund appears in the fund universe (or has been investigated and excluded with documented reason).
3. No entity filing 10-K/10-Q with `814-` file numbers is missing from the BDC universe.
4. No entity filing N-PORT with material private market holdings (>25% illiquid/loan/private fund) is missing from the fund universe.
5. Discrepancies between discovery methods are documented and resolved.

---

## Data Architecture

The pipeline captures ALL parseable data from every filing by every vehicle in the universe, not just the fields needed for the four indices. This avoids re-parsing filings when new analyses are needed and enables future use cases (fund-level analytics, sector deep dives, academic research datasets) without pipeline changes.

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Index-Ready Datasets                          │
│  Filtered, classified, deduplicated subsets for the     │
│  four indices and the website. Opinionated.             │
│  Format: JSON files for website, Parquet for downloads  │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Parsed Data Lake                              │
│  Everything parseable from every filing, structured     │
│  into tables. Wide and permissive. Not opinionated.     │
│  Format: DuckDB database + Parquet files                │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Raw Filing Archive                            │
│  Every filing in its original format as downloaded      │
│  from EDGAR. Immutable source of truth.                 │
│  Format: Original files keyed by accession number       │
└─────────────────────────────────────────────────────────┘
```

### Layer 1: Raw Filing Archive

Store every downloaded filing in its original format. This is the immutable source of truth. If a parsing bug is discovered or a new field needs to be extracted, go back to Layer 1 rather than re-downloading from EDGAR.

```
data/raw/
  filings/
    {accession_number}/
      index.json              # Filing metadata (CIK, form type, period, filed date, URLs)
      instance.xml            # XBRL instance document (BDC 10-K/10-Q)
      nport.xml               # N-PORT XML filing
      ncen.xml                # N-CEN XML filing
      n2.htm                  # N-2 registration statement (HTML)
      filing_index.html       # EDGAR filing index page
  sec_datasets/
    bdc/
      2025q2_bdc.zip          # SEC's pre-built BDC Data Set (for cross-validation)
    nport/
      2025q2_nport.zip        # SEC's pre-built N-PORT Data Set (for cross-validation)
    ncen/
      ncen_latest.zip         # SEC's pre-built N-CEN Data Set
```

Storage estimate: ~500MB-1GB for all historical BDC and relevant N-PORT filings. Negligible.

### Layer 2: Parsed Data Lake

Extract everything parseable from every filing into structured tables. Use DuckDB as the primary store (single-file database, excellent Parquet support, fast analytical queries) with Parquet file exports for portability and downloads.

The principle: if a field is in the filing and can be parsed, it goes into Layer 2 regardless of whether the indices need it today.

#### Layer 2 Schema

**Table: universe**
Universe registry from Phase 1. One row per vehicle.
```
universe:
  - entity_id: str                    # Internal unique ID
  - cik: str
  - entity_name: str
  - file_number: str
  - vehicle_type: enum                # bdc, interval_fund, tender_offer_fund, listed_cef
  - status: enum                      # active, inactive, merged, withdrawn
  - election_date: date | null        # BDCs: from N-54A
  - withdrawal_date: date | null      # BDCs: from N-54C
  - first_filing_date: date
  - last_filing_date: date
  - discovery_methods: list[str]
  - data_sources: list[str]           # xbrl_10k, xbrl_10q, nport, ncen
```

**Table: filings**
One row per filing per vehicle.
```
filings:
  - accession_number: str             # Primary key
  - cik: str
  - entity_name: str
  - form_type: str                    # 10-K, 10-Q, NPORT-P, N-CEN, N-2
  - filing_date: date
  - period_of_report: date
  - fiscal_year_end: str
  - fiscal_period: str                # FY, Q1, Q2, Q3, Q4
  - inline_url: str
  - raw_file_path: str                # Path in Layer 1
  - parsed: bool                      # Whether Layer 2 extraction is complete
  - parse_timestamp: datetime
```

**Table: bdc_financials**
Fund-level financial data extracted from BDC 10-K/10-Q XBRL. One row per filing.
```
bdc_financials:
  - accession_number: str             # FK to filings
  - cik: str
  - period: date
  - total_investments_fair_value: float
  - total_investments_cost: float
  - total_assets: float
  - total_liabilities: float
  - total_net_assets: float
  - nav_per_share: float
  - shares_outstanding: float
  - net_investment_income: float
  - net_realized_gains_losses: float
  - net_unrealized_appreciation_depreciation: float
  - net_increase_decrease_from_operations: float
  - distributions_to_shareholders: float
  - total_investment_income: float
  - interest_income_non_controlled: float
  - interest_income_controlled: float
  - dividend_income: float
  - fee_income: float
  - base_management_fee: float
  - incentive_fee: float
  - interest_expense_on_debt: float
  - total_expenses: float
  - credit_facility_borrowings: float
  - notes_payable: float
  - asset_backed_debt: float
  - weighted_average_shares: float
  - net_investment_income_per_share: float
  - earnings_per_share: float
  - distributions_per_share: float
  - public_float: float | null
```

**Table: nport_fund_info**
Fund-level data extracted from N-PORT XML fundInfo section. One row per filing.
```
nport_fund_info:
  - accession_number: str             # FK to filings
  - cik: str
  - series_id: str
  - period: date
  - total_assets: float
  - total_liabilities: float
  - net_assets: float
  - monthly_total_return_1: float     # Month 1 of quarter
  - monthly_total_return_2: float     # Month 2 of quarter
  - monthly_total_return_3: float     # Month 3 of quarter
  - monthly_flow_sales_1: float
  - monthly_flow_reinvestments_1: float
  - monthly_flow_redemptions_1: float
  - monthly_flow_sales_2: float
  - monthly_flow_reinvestments_2: float
  - monthly_flow_redemptions_2: float
  - monthly_flow_sales_3: float
  - monthly_flow_reinvestments_3: float
  - monthly_flow_redemptions_3: float
  - credit_spread_risk_dv01_3m: float | null
  - credit_spread_risk_dv01_1y: float | null
  - credit_spread_risk_dv01_5y: float | null
  - credit_spread_risk_dv01_10y: float | null
  - credit_spread_risk_dv01_30y: float | null
  - is_non_cash_collateral: bool | null
  - borrowing_from_bank: float | null
  - borrowing_from_other: float | null
  - pct_illiquid: float | null
```

**Table: holdings_bdc**
Investee-level holdings from BDC XBRL filings. One row per position per filing. Extract ALL tagged facts on the Investment Identifier Axis, not just SOI fields.
```
holdings_bdc:
  - accession_number: str             # FK to filings
  - cik: str
  - period: date
  - investment_identifier: str        # Raw typed dimension value (full string)
  - issuer_name_parsed: str           # Extracted company name
  - instrument_description: str       # Extracted instrument description
  - industry_sector: str | null       # From Industry Sector Axis
  - investment_type: str | null       # From Investment Type Axis
  - issuer_affiliation: str | null    # From Issuer Affiliation Axis (controlled/non-controlled)
  - fair_value: float | null
  - cost: float | null
  - principal_amount: float | null
  - interest_rate: float | null
  - basis_spread_variable_rate: float | null
  - reference_rate: str | null        # SOFR, EURIBOR, SONIA, etc. (from extensible enumeration)
  - maturity_date: date | null
  - acquisition_date: date | null
  - interest_rate_floor: float | null
  - interest_paid_in_cash: float | null
  - interest_paid_in_kind: float | null
  - shares_held: float | null
  - face_amount: float | null
  - pct_of_net_assets: float | null
  - realized_gain_loss: float | null
  - unrealized_gain_loss: float | null
  - gross_additions: float | null     # For affiliates schedule
  - gross_reductions: float | null    # For affiliates schedule
  - fair_value_hierarchy_level: str | null  # Level 1, 2, or 3
  - is_custom_tag: bool               # Whether any custom tags were used for this position
  - raw_xbrl_segments: str            # Full dimension string for debugging
```

**Table: holdings_nport**
Investee-level holdings from N-PORT XML filings. One row per position per filing. Extract ALL fields from each invstOrSec element.
```
holdings_nport:
  - accession_number: str             # FK to filings
  - cik: str
  - series_id: str
  - period: date
  - issuer_name: str
  - issuer_title: str                 # Title of issue / instrument description
  - issuer_lei: str | null
  - cusip: str | null
  - isin: str | null
  - ticker: str | null
  - other_identifier: str | null
  - other_identifier_type: str | null
  - asset_cat: str                    # loan, equity-common, equity-preferred, debt, etc.
  - asset_cat_other: str | null       # Description if asset_cat = "other"
  - issuer_cat: str                   # corporate, private fund, registered fund, etc.
  - issuer_cat_other: str | null      # Description if issuer_cat = "other"
  - investment_country: str | null    # ISO country code
  - is_restricted: bool | null
  - fair_value: float
  - pct_of_nav: float | null
  - payoff_profile: str | null        # long, short, N/A
  - currency: str | null
  - exchange_rate: float | null
  - quantity: float | null
  - units: str | null                 # shares, principal amount, etc.
  - cost: float | null
  - liquidity_classification: str | null  # highly liquid, moderately liquid, less liquid, illiquid
  - fair_value_level: str | null      # Level 1, 2, 3
  # Debt-specific fields
  - annualized_rate: float | null     # Coupon rate
  - is_default: bool | null
  - are_interest_payments_in_arrears: bool | null
  - is_paid_in_kind: bool | null
  - maturity_date: date | null
  - coupon_type: str | null           # fixed, floating, variable, none
  - reference_rate_and_spread: str | null  # e.g., "SOFR + 475bps"
  # Convertible-specific fields
  - is_convertible: bool | null
  - conversion_ratio: float | null
  # Repo/reverse repo fields (if applicable)
  - repurchase_rate: float | null
  - repurchase_maturity: date | null
  # Derivative fields (if applicable)
  - derivative_category: str | null
  - notional_amount: float | null
  - underlying_name: str | null
  - underlying_cusip: str | null
  # Securities lending
  - is_on_loan: bool | null
  - loan_value: float | null
```

**Table: ncen_fund_data**
Fund census data from N-CEN filings. One row per fund per annual filing.
```
ncen_fund_data:
  - accession_number: str
  - cik: str
  - series_id: str | null
  - entity_name: str
  - fund_name: str | null
  - reporting_period_end: date
  - fund_type: str                    # open-end, closed-end, UIT
  - is_interval_fund: bool
  - is_exchange_traded: bool
  - is_section_3c7: bool | null
  - investment_adviser_cik: str | null
  - investment_adviser_name: str | null
  - administrator_name: str | null
  - auditor_name: str | null
  - custodian_name: str | null
  - transfer_agent_name: str | null
  - monthly_avg_net_assets: float | null
  - net_assets_end_of_period: float | null
  - has_credit_facility: bool | null
  - credit_facility_amount: float | null
  - total_borrowings: float | null
  - securities_issued: list[str] | null  # Types of securities issued
```

**Table: entity_resolution**
Output of entity deduplication. Maps raw investee names across vehicles to canonical entities.
```
entity_resolution:
  - canonical_entity_id: str          # Deduplicated entity ID
  - canonical_name: str               # Cleaned, standardised name
  - source_vehicle_cik: str
  - source_accession_number: str
  - source_raw_name: str              # As it appeared in the filing
  - source_type: str                  # bdc_xbrl or nport
  - match_method: str                 # exact, fuzzy, llm_assisted, manual
  - match_confidence: float           # 0-1
  - industry_sector: str | null       # Standardised industry
  - entity_type: str                  # operating_company, credit_fund, pe_fund, other_fund
```

### Layer 3: Index-Ready Datasets

Filtered, classified, and aggregated subsets of Layer 2 that feed the four indices and the website. This layer is opinionated — it makes choices about inclusion, exclusion, weighting, and classification.

Generated as static files consumed by the website at build time:

```
data/output/
  indices.json                        # Index-level time series for all four indices
  summary.json                        # Latest headline numbers for homepage
  constituents/
    direct-lending/
      2025-Q2.json                    # Constituent positions for Index 1, Q2 2025
      2025-Q1.json
      ...
    direct-equity/
      ...
    credit-funds/
      ...
    equity-funds/
      ...
  universe.json                       # Vehicle universe with metadata
  vehicles/
    {cik}.json                        # Per-vehicle data (for future vehicle pages)
  downloads/
    direct_lending_index.csv
    direct_lending_index.xlsx
    direct_lending_index.parquet
    direct_lending_constituents.csv
    direct_lending_constituents.parquet
    direct_equity_index.csv
    ...
    full_data_lake.parquet            # Layer 2 export for researchers
    universe.csv
    data_dictionary.csv
```

### Layer 3 Classification Logic

Holdings flow from Layer 2 into the four indices based on these rules:

**Index 1 — Direct Lending**
- From holdings_nport: `asset_cat` IN ('loan', 'debt') AND `issuer_cat` = 'corporate'
- From holdings_bdc: `investment_type` indicates debt instrument (first lien, second lien, unitranche, mezzanine, subordinated, unsecured) AND position is in an operating company (not a fund/vehicle investment)
- Excludes: CLO tranches, ABS, fund interests, government securities, derivatives, money market instruments

**Index 2 — Direct Equity**
- From holdings_nport: `asset_cat` IN ('equity-common', 'equity-preferred') AND `issuer_cat` = 'corporate'
- From holdings_bdc: `investment_type` indicates equity instrument (common stock, preferred equity, warrants) AND position is in an operating company
- Preferred equity classification: if the position has a stated coupon/spread AND a maturity date, treat as debt (Index 1). If no coupon/maturity or if the terms indicate equity-like participation, treat as equity (Index 2). Flag ambiguous cases.

**Index 3 — Private Credit Funds**
- From holdings_nport: `issuer_cat` IN ('private fund', 'registered fund') AND fund name classified as credit strategy by LLM/rules
- From holdings_bdc: positions tagged as fund/vehicle investments on Investment Type Axis where the fund name indicates a credit strategy
- Classification signals for credit: fund name contains "credit", "lending", "loan", "debt", "income", "CLO", "senior", "direct lending", or names of known credit fund managers

**Index 4 — Private Equity Funds**
- Same source logic as Index 3 but fund name classified as PE/buyout strategy
- Classification signals for PE: fund name contains "equity", "buyout", "growth", "capital partners", "venture", or names of known PE fund managers
- Ambiguous fund names (e.g., "multi-strategy", "opportunistic") flagged for manual review or excluded

---

## Phase 2: Full Data Extraction

### Objective

For every filing by every vehicle in the universe, extract all parseable data into Layer 2. This is a comprehensive extraction — not limited to what the indices need.

### Pipeline 1: BDC XBRL Extraction

For each BDC 10-K/10-Q filing:

1. Download the XBRL instance document and store in Layer 1.
2. Parse the full NUM table (every numeric fact). Populate `bdc_financials` with fund-level aggregates.
3. Parse all facts on the `Investment, Identifier [Axis]` typed dimension. For each unique identifier value, extract all associated standard tags (fair value, cost, rate, spread, maturity, etc.) and populate `holdings_bdc`.
4. Parse the `Investment, Issuer Affiliation [Axis]` to capture controlled/non-controlled status.
5. Parse the `Industry Sector [Axis]` and `Investment Type [Axis]` for industry and instrument subtotals — store these as separate rows in `holdings_bdc` with a flag indicating they are subtotals rather than individual positions.
6. Parse the TXT table for any text-tagged data relevant to positions (footnotes, descriptions).
7. Extract fair value hierarchy disclosures (Level 1/2/3 breakdowns) from the relevant XBRL tags.

### Pipeline 2: N-PORT XML Extraction

For each N-PORT filing by a vehicle in the universe:

1. Download the N-PORT XML and store in Layer 1.
2. Parse the `fundInfo` section and populate `nport_fund_info` with fund-level metrics (total assets, monthly returns, flows, risk metrics, borrowing data).
3. Parse every `invstOrSec` element and populate `holdings_nport` with all available fields. Extract ALL sub-elements, not just the fields listed in the schema — the schema above is a minimum; if a filing contains additional fields, store them in a catch-all JSON column.
4. For holdings where `issuer_cat` = 'private fund' or 'registered fund', flag for fund classification in Phase 3.

### Pipeline 3: N-CEN Extraction

For each N-CEN filing by a vehicle in the universe:

1. Download and store in Layer 1.
2. Parse fund census data and populate `ncen_fund_data`.
3. Use N-CEN data to enrich the universe table with adviser information, fund structure details, and strategy classification.

### Pipeline 4: SEC Pre-Built Dataset Cross-Validation

Download the SEC's BDC Data Set (SOI table, SUB table, NUM table) and N-PORT Data Set. Use these as cross-validation:
- Compare BDC SOI data against your own XBRL extraction. Discrepancies may indicate parsing bugs or XBRL tagging issues.
- Compare N-PORT dataset holdings against your own XML extraction.
- Log discrepancies but prefer your own extraction (which captures investee-level detail the SOI table often drops).

---

## Phase 3: Entity Resolution

### Objective

Deduplicate investee companies and fund vehicles across all holding vehicles, producing a canonical entity registry that maps every raw name variant to a single deduplicated entity.

### Approach

**Step 3.1: Exact and near-exact matching**
Normalise all investee names (lowercase, strip legal suffixes like LLC/Inc/Corp/LP, remove punctuation, normalise whitespace). Group exact matches. This handles the trivial cases where the same company is named identically or nearly identically across filers.

**Step 3.2: Fuzzy matching within attribute groups**
For remaining unmatched names, compute similarity scores (Levenshtein distance, Jaro-Winkler, token-set ratio) and group candidates with similarity above a threshold (e.g., 0.85). Use additional attributes to confirm or reject matches:
- Same industry sector across filers → higher confidence
- Same instrument type (both first lien) → higher confidence
- Similar maturity dates → higher confidence
- Similar principal amounts → moderate confidence signal
- Matching CUSIP or LEI (where available from N-PORT) → definitive match

**Step 3.3: LLM-assisted disambiguation**
For candidates where fuzzy matching is ambiguous (similarity between 0.7 and 0.85, or conflicting attribute signals), send pairs to an LLM with context and ask for a match/no-match classification with confidence score. Use the Anthropic batch API for cost efficiency.

**Step 3.4: Fund name classification**
For holdings identified as fund investments (`issuer_cat` = 'private fund' or 'registered fund'), classify each fund name as credit strategy, PE strategy, or other. Use rule-based matching first (keyword lists), then LLM for ambiguous names.

**Step 3.5: Industry standardisation**
Normalise the ~300+ industry sector variants observed in BDC XBRL (e.g., "Aerospace & Defense", "Aerospace And Defense Sector [Member]", "Aerospace and Defense [Member]") to a canonical set of ~50-75 GICS-aligned industry groups. Rule-based first, LLM for edge cases.

### Output

Populate the `entity_resolution` table in Layer 2. Every raw name in `holdings_bdc` and `holdings_nport` maps to a `canonical_entity_id`.

---

## Phase 4: Index Construction

### Objective

Compute quarterly total return series for each of the four indices using the deduplicated, classified data from Phases 2-3.

### Public Market Index Methodology Reference

All major public credit/fixed income indices use **total return** (price change + income) as their flagship measure. Interest/coupon income is the dominant return component for credit instruments; a price-only index would be fundamentally incomparable to public benchmarks.

| Index | Return Components | Rebalancing | New Issuance |
|---|---|---|---|
| Morningstar LSTA Leveraged Loan | Price + interest + principal repayment | Weekly (Friday) | At next weekly rebalance |
| ICE BofA US High Yield | Price + accrued interest (30/360) | Monthly (last calendar day) | Next month if eligible |
| Bloomberg US Aggregate | Price + coupon + paydown + FX | Monthly (dual-universe) | Projected Universe daily; Returns Universe at month-end |
| S&P 500 (Total Return) | Price + reinvested dividends | As-needed (committee) | Committee decision |

Key methodological choices relevant to our index:

1. **Returns computed on beginning-of-period constituents only.** New positions entering at rebalance do not retroactively affect the period's return. This cleanly separates mark-to-market performance from capital deployment.
2. **Income accrual, not receipt.** LSTA accrues interest daily using spread + reference rate. ICE BofA accrues on 30/360 basis. Neither waits for actual cash payment.
3. **No reinvestment assumption for coupon cash.** LSTA and ICE BofA treat received coupons as cash (no reinvestment return). Bloomberg assumes reinvestment in the index portfolio.
4. **Periodic rebalancing absorbs entries/exits.** Newly eligible securities enter at the next rebalance; exiting securities remain until rebalance. The universe naturally evolves with the market.

### Position Matching Across Quarters (Implemented)

Computing position-level total returns requires linking the same instrument across consecutive quarters. This is the critical data engineering challenge for the index. The implemented solution uses a 4-tier matching cascade followed by union-find graph analysis to assign stable `position_id` identifiers that track each instrument through its full lifecycle.

**Pipeline results (as of April 2025):** 548K matched pairs from 827K unified holdings. 341K unique position IDs: 181K chained (multi-quarter tracks) + 160K singletons. Max chain length 28 quarters.

#### BDC Identifier Formats

BDC investment identifiers (`investmentidentifieraxis` typed dimension) encode structured information about each position, but the format varies across filers and even across filing types (10-K vs 10-Q) for the same filer. Understanding these formats is critical for both rule-based parsing and position matching.

**Format 1 -- Pipe-delimited (6.7% of BDC rows, 67 CIKs)**

Contains 4-8 pipe-separated fields encoding investment type, company name, industry, spread, floor rate, all-in rate, acquisition date, and maturity:

```
Bank Debt/Senior Secured Loans | RQM+ Corp. | Life Sciences Tools & Services | S+675 | 1.00% | 11.34% | 8/20/2021 | 8/12/2029
Debt Investments | First Lien Senior Secured | Technology | MH Sub I, LLC | Term Loan | SOFR + 4.250% | 8.607% | 04/25/2028 - 1
Merama Inc. | Preferred Stock 3 | Equity Investments | Non-Affiliated Issuer
```

Field positions vary by filer. Some place the company name in position [0], others in [1] or [2]. The last segment may be an affiliation tag ("Non-Affiliated Issuer", "Affiliated Issuer") or a trailing tranche number. The current rule-based parser identifies the company by detecting affiliation tags and known category labels.

**Format 2 -- Structured comma-delimited (11.7% of BDC rows, 86+ CIKs)**

Contains 4-6 comma-separated fields, typically: company name, industry, instrument type, and optionally affiliation and tranche number:

```
Trident Maritime Systems, Inc, Senior Secured Loans, Two, due 2/26/2027
ProfitOptics, LLC, Technology, Senior Subordinated Term Loan
First Lien Debt, CPI Intermediate Holdings, Inc., Telecommunications
Bluesight, Inc., Senior Secured Loans 2, Non-Affiliated
```

Company name is usually the first field, but some filers place instrument type first ("First Lien Debt, Company, Industry"). The same company can appear with different field orderings across 10-K vs 10-Q filings by the same filer, breaking exact string matching.

**Format 3 -- Unstructured concatenated (21.3% of BDC rows, 132 CIKs)**

All metadata concatenated into a single string with no consistent delimiter. May include industry, company name, legal entity, instrument type, spread, floor, rate, acquisition date, maturity, and address:

```
High Tech Industries Superna Inc. First Lien Senior Secured Loan SOFR Spread 6.50% Interest Rate 10.24% Maturity Date 3/6/2028
Diversified Consumer Services Legacy.com Lotus Topco Inc. First Lien Secured Debt - Revolver S+475, 1.00% Floor Maturity Date 6/7/2030
First Brands Inc. 3255 West Hamlin Road Rochester Hills MI 48309 Transportation Equipment Manufacturing Security 2nd Lien Secured Loan Interest Rate 3M SOFR + 8.50% ...
```

The company name boundary is ambiguous -- "High Tech Industries" is an industry label, "Superna Inc." is the company, and "First Lien Senior Secured Loan" is the instrument. Addresses, rates, and dates may be interspersed. Rule-based parsing fails on many of these; they are the primary target for LLM extraction.

**Format 4 -- Short/clean (60.3% of BDC rows, 153 CIKs)**

Company name alone or with minimal metadata. Already clean enough for direct matching:

```
PetVet Care Centers, LLC | First Lien Term Loan
MNS Buyer, Inc. | First Lien Senior Secured Term Loan
Galaxy Universal LLC, Common Stock, Consumer Durables & Apparel
PPV Intermediate Holdings, LLC, First lien senior secured loan
```

**Cross-format matching problem:** The same filer may use pipe-delimited format in 10-K (annual) and comma-delimited or unstructured format in 10-Q (quarterly). This causes the same position to have completely different identifier strings across filings:

```
10-K (2023q4): "Bank Debt/Senior Secured Loans | Acme Corp. | Technology | S+475 | 1.00% | 10.24% | 3/15/2022 | 3/15/2029"
10-Q (2024q1): "Acme Corp., Technology, First lien senior secured loan"
```

Both refer to the same position, but exact string matching fails. The rule-based parser extracts "Acme Corp." from both, enabling matching. For unstructured identifiers where the parser fails, LLM extraction is the only reliable approach.

#### Implemented Matching Cascade

The cascade applies methods in priority order with cascade exclusion: positions matched by a higher-priority tier are excluded from lower tiers to prevent duplicates.

**Tier A: Within-filing comparatives (37.9% of pairs, ~208K)**

BDC 10-K/10-Q XBRL filings contain schedule-of-investments facts tagged at both the current period-end and the prior comparative period-end, using the same `investmentidentifieraxis` value. This provides filer-matched position pairs with no external matching needed.

- Accuracy: ~100% (the filer's own mapping)
- Spans: 3-month (10-Q), 6-month, 9-month, 12-month (10-K) depending on fiscal year-end
- Implementation: rows where `period < report_date` are prior-period comparatives; paired with `period = report_date` rows sharing the same `bdc_investment_identifier`
- 1:1 enforcement via double ROW_NUMBER with fair value proximity tiebreaking

**Tier B1: CUSIP match (1.6% of pairs, ~9K)**

N-PORT positions matched across consecutive quarters by CUSIP (instrument-level identifier). Coverage is 47% of N-PORT rows. Private holdings often lack CUSIPs, limiting this tier to broadly-syndicated loans that have been assigned identifiers.

**Tier B2: Exact issuer_name match (58.6% of pairs, ~321K)**

The workhorse tier. Matches positions across consecutive quarters within the same CIK by exact cleaned `issuer_name`. N-PORT carry rate: 98.5%. BDC carry rate after parsing: ~78% (higher after normalization).

- Excludes positions already claimed by Tier A (end-side only; see deferred exclusion below)
- 1:1 enforcement: double ROW_NUMBER partitioned by unified row ID, ordered by fair value proximity
- Fair value proximity tiebreaking: `ABS(LN(begin_fv / end_fv))` -- closer FV wins

**Tier C: Normalized name match (0.5% of pairs, ~2.7K)**

For BDC positions where `issuer_name` differs slightly between quarters due to punctuation, whitespace, or legal suffix changes. Normalization: lowercase, strip trailing punctuation, collapse whitespace, remove tranche numbers.

**Tier D: Jaro-Winkler fuzzy match (1.4% of pairs, ~7.7K)**

For positions that survive through Tiers A-C unmatched. Applies within the same CIK across consecutive quarters, with prefix-blocking (first 4 characters must match) and a minimum Jaro-Winkler similarity threshold of 0.88. A 5x fair value ratio guard prevents matching positions with wildly different sizes.

#### Deferred Cascade Exclusion

A critical design decision: Tier A end-side positions (current period, same filing) are reliably mapped to unified holdings via `bdc_investment_identifier` because they share the same filing. But Tier A begin-side positions (prior period comparative from a different filing) often cannot be mapped because the raw identifier format changed between filings.

**Solution:** Only exclude Tier A end-side positions from B2/C/D. Begin-side positions are released to lower tiers, allowing B2 to match them using cleaned `issuer_name`. This eliminates the "cascade exclusion gap" where Tier A claims a position, fails to map the begin-side, and blocks B2 from finding it.

#### Position ID Assignment (Union-Find)

After matching, a union-find (disjoint set) algorithm assigns stable `position_id` identifiers to track each instrument across its full lifecycle:

1. **Build graph:** Each matched pair (begin, end) is an edge. Only pairs with span <= 4 months are used (short-span filter prevents unreliable 12-month annual pairs from creating false connections).
2. **Map to unified holdings:** Each match-pair side is mapped to a unified holdings row via DuckDB join. Tier A uses `bdc_investment_identifier` (exact raw match within same filing). Tiers B/C/D use `issuer_name` (cleaned name). Double ROW_NUMBER enforces 1:1 on both the match side and the unified side.
3. **Connected components:** Union-find computes connected components. If Q1->Q2 and Q2->Q3 are paired, all three observations share one `position_id`.
4. **Supplementary B2:** A second-pass B2-style matching runs directly on unified holdings to catch positions that the main cascade missed (particularly those stranded by the cascade exclusion gap). Uses uniqueness filter (name appears exactly once per CIK/quarter), 5x FV ratio guard, and allows negative fair values (ABS-based ratio). Adds ~125K new connections.
5. **Singleton assignment:** Holdings not connected to any chain receive unique singleton `position_id` values.

**Output:** `position_id` column (format `POS-00000001`) propagated to `private_markets_holdings.csv`, `position_matches.csv`, and `position_returns.csv`.

#### Singleton Analysis

The overall singleton rate is 19.4% (160K of 827K holdings). By source:

| Source | Overall | Excl. last qtr + zero FV | Interior only |
|---|---|---|---|
| BDC | 27.3% | 13.8% | 11.1% |
| N-PORT | 15.6% | 13.9% | 8.4% |

The BDC-to-NPORT gap is almost entirely structural. BDC singleton budget (102K):

| Bucket | Count | % | Reducible? |
|---|---|---|---|
| Bad data (null/zero FV, empty name) | 39K | 38% | No |
| Last quarter (no forward match target) | 20K | 19% | Partially (backward match) |
| Negative FV | 14K | 14% | Done (ABS-based FV guard) |
| Island quarters (CIK appears once) | 5K | 5% | No |
| First quarter (no backward match target) | 5K | 5% | No |
| Interior: name changed between filings | 14K | 14% | LLM extraction |
| Interior: cascade/multi-tranche | 5K | 5% | Partially |

#### LLM-Assisted Company Name Extraction (Planned)

The largest reducible singleton bucket (~14K interior positions, ~75% of interior BDC singletons) consists of positions where the `issuer_name` genuinely changed between filings -- typically because the filer switched identifier formats between 10-K and 10-Q.

**The problem.** The same position appears with different raw identifiers across filings:

```
2023q4 (10-K): "Bank Debt/Senior Secured Loans | Acme Corp. | Technology | S+475 | 1.00% | 10.24%"
2024q1 (10-Q): "Acme Corp., Technology, First lien senior secured loan"
```

The rule-based parser in `unified_holdings.py` correctly extracts "Acme Corp." from both, so they match. But for unstructured identifiers the parser fails:

```
2023q4: "High Tech Industries Superna Inc. First Lien Senior Secured Loan SOFR Spread 6.50%"
2024q1: "Superna Inc, Technology, Senior Secured Loans"
```

The parser extracts the full string "High Tech Industries Superna Inc. First Lien Senior Secured Loan SOFR Spread 6.50%..." as the issuer name for the first, but correctly extracts "Superna Inc" for the second. They cannot be matched.

**The solution.** An LLM step extracts structured fields from each raw `bdc_investment_identifier` string into a canonical form. The LLM receives the full identifier and returns:

```json
{
  "company_name": "Superna Inc.",
  "instrument_type": "First Lien Senior Secured Loan",
  "industry": "Technology",
  "reference_rate": "SOFR",
  "spread_bps": 650,
  "all_in_rate_pct": null,
  "floor_pct": null,
  "maturity_date": "2028-03-06",
  "acquisition_date": null,
  "tranche_number": null,
  "affiliation": null
}
```

**What the LLM extracts (by format):**

*Pipe-delimited identifiers* -- the LLM identifies which pipe-segment is the company name (varies by filer), which is the industry, which is the spread, etc.:

| Raw identifier | company_name | instrument_type | industry | spread |
|---|---|---|---|---|
| `Bank Debt/Senior Secured Loans \| RQM+ Corp. \| Life Sciences \| S+675 \| 1.00% \| 11.34%` | RQM+ Corp. | Bank Debt/Senior Secured Loans | Life Sciences | S+675 |
| `Merama Inc. \| Preferred Stock 3 \| Equity Investments \| Non-Affiliated Issuer` | Merama Inc. | Preferred Stock | (none) | (none) |
| `Equipment Financing - 24.1% \| Up Trucking Services, LLC \| Road & Rail \| 11.30%` | Up Trucking Services, LLC | Equipment Financing | Road & Rail | (none) |

*Structured comma identifiers* -- the LLM disambiguates field order (company first vs instrument first):

| Raw identifier | company_name | instrument_type | industry |
|---|---|---|---|
| `First Lien Debt, CPI Intermediate Holdings, Inc., Telecommunications` | CPI Intermediate Holdings, Inc. | First Lien Debt | Telecommunications |
| `ProfitOptics, LLC, Technology, Senior Subordinated Term Loan` | ProfitOptics, LLC | Senior Subordinated Term Loan | Technology |

*Unstructured concatenated identifiers* -- the hardest case, where the LLM must find the company name boundary within a run-on string:

| Raw identifier | company_name | instrument_type | industry |
|---|---|---|---|
| `High Tech Industries Superna Inc. First Lien Senior Secured Loan SOFR Spread 6.50% Interest Rate 10.24% Maturity Date 3/6/2028` | Superna Inc. | First Lien Senior Secured Loan | High Tech Industries |
| `Diversified Consumer Services Legacy.com Lotus Topco Inc. First Lien Secured Debt - Revolver S+475, 1.00% Floor Maturity Date 6/7/2030` | Lotus Topco Inc. | First Lien Secured Debt - Revolver | Diversified Consumer Services |
| `First Brands Inc. 3255 West Hamlin Road Rochester Hills MI 48309 Transportation Equipment Manufacturing Security 2nd Lien Secured Loan...` | First Brands Inc. | 2nd Lien Secured Loan | Transportation Equipment Manufacturing |
| `Containers & packaging - FCA, LLC - M2S Group Intermediate Holdings, Inc. - First lien senior secured loan - SOFR(M)` | M2S Group Intermediate Holdings, Inc. | First lien senior secured loan | Containers & packaging |

**Implementation approach:**

1. **Deduplicate identifiers.** ~375K BDC holdings contain ~85K distinct `bdc_investment_identifier` values. Only distinct values need to be processed.
2. **Rule-based pre-filter.** The existing `_parse_bdc_identifier()` correctly handles ~70% of identifiers (pipe-with-affiliation, pipe-with-SLR-format, industry-prefix with dash separator). These don't need LLM processing. Only the ~25K distinct identifiers where the parser returns the full string or a clearly wrong result are sent to the LLM.
3. **Batch API.** Use the Anthropic batch API (Claude Haiku) with structured output. Each request contains 50-100 identifiers with a JSON schema for the response. Estimated cost: ~$2-4 for the full backfill, ~$0.25/quarter incremental.
4. **Persistent cache.** Results are stored in a lookup table keyed by SHA-256 hash of the identifier string. On subsequent runs, only new identifiers are sent to the LLM. The cache file (`data/output/identifier_cache.json`) is deterministic -- same input always produces same output.
5. **Integration.** The LLM-extracted `company_name` is used as a matching key in a new Tier E of the cascade, between Tier D (fuzzy) and singleton assignment. It enables matching across format changes: the 10-K identifier "High Tech Industries Superna Inc. First Lien..." and the 10-Q identifier "Superna Inc, Technology, Senior Secured Loans" both extract to company_name="Superna Inc." and can be matched.
6. **Validation.** A random sample of 200 LLM extractions is manually reviewed. Expected accuracy: 95-98% for company name, 90-95% for instrument type, 85-90% for industry.

**Additional extracted fields** beyond `company_name` improve downstream analytics:

- `instrument_type`: enables sub-index construction by lien position (first lien, second lien, mezzanine) directly from the identifier, supplementing the `asset_category` classification
- `industry`: enriches the ~70% of BDC holdings that have no structured industry tag, enabling industry sub-indices
- `spread_bps` and `floor_pct`: fills gaps in the XBRL-tagged `basis_spread` field (currently 33% coverage), improving income return estimation
- `maturity_date`: supplements the text-regex extraction already implemented (13% coverage), providing a more complete maturity profile

### Return Calculation (Implemented)

Returns are computed per matched position pair. Each pair has a begin-side and end-side observation with fair value, cost, principal, and rate data.

**Price return -- per-unit methodology.** Raw fair value change conflates mark-to-market with quantity changes (additional draws, partial paydowns, new purchases). The per-unit approach isolates true price performance:

- Direct Lending: `price = FV / principal_amount`. Return = `(end_price / begin_price) - 1`. Falls back to raw FV change if principal is missing.
- Direct Equity: `price = FV / shares_held`, then `FV / cost` if shares missing. Falls back to raw FV change.
- Impact vs raw FV: DL index rose from 89.8 to 126.6 (amortising loans were being penalised for returning principal). DE index fell from 181.7 to 121.6 (new share purchases were inflating returns).

**Income return -- 3-tier rate imputation.** Estimated quarterly coupon income accrual:

```
income_return = (effective_annual_rate / 4) * (begin_principal / begin_fair_value)
```

The effective annual rate is imputed via a 3-tier COALESCE cascade:

1. **Direct interest_rate** (83.8% of DL positions): The XBRL-tagged all-in coupon rate, harmonised to percentage scale.
2. **Basis spread + implied SOFR** (8.2%): For floating-rate positions with only `basis_spread` tagged. Implied SOFR is derived from peer filers in the same quarter: `median(interest_rate - basis_spread)` across all positions in the same CIK+quarter where both fields are populated. The implied SOFR tracks the Fed Funds rate precisely: 1.0% (2021q4) -> 5.4% (2023q3) -> 4.2% (2025q3).
3. **Same-filer median rate** (5.7%): For positions with no rate or spread data, uses the median interest_rate across all other positions from the same CIK in the same quarter. This assumes a filer's portfolio has relatively homogeneous pricing.
4. **Missing** (2.3%): No rate available. Income return set to zero.

**Outlier guards:**

- Total return capped at +200% / floored at -99% per position per quarter
- Positions exceeding these thresholds are excluded from the index (13.8K excluded, 10.7K floored)

**Index aggregation:**

- Fair-value-weighted: each position's weight = begin_fair_value / sum(begin_fair_value) across all constituents in that quarter
- Equal-weighted: each position weighted 1/N
- Chain-linked multiplicatively: `Index_t = Index_t-1 * (1 + R_t)`, base = 100 at 2019q4

**Index results (25 quarters, 2019q4-2025q4):**

| Index | FV-Weighted | EQ-Weighted | Avg Constituents | Annualised (FV) |
|---|---|---|---|---|
| DIRECT_LENDING | 140.9 | 140.9 | 8,902 | ~5.8% |
| DIRECT_EQUITY | 118.8 | 114.7 | 1,197 | ~3.0% |
| PRIVATE_CREDIT_FUND | 174.1 | 128.5 | 24 | ~16.5% |
| PRIVATE_EQUITY_FUND | 162.4 | 287.3 | 109 | ~8.5% |

### Weighting

Primary: fair-value weighting (each position's weight = its fair value / total index fair value at beginning of period). After entity resolution, aggregate fair values across vehicles for the same investee before computing weights.

Secondary (computed in parallel): equal-weighted by deduplicated entity. Each unique investee has equal weight regardless of how many vehicles hold it or the size of individual positions.

Tertiary: cost-weighted. Weight = cost basis / total index cost basis. Removes the circularity of weighting by the variable being measured.

### Chain-Linking

Quarterly index returns are chain-linked multiplicatively:
```
Index_t = Index_{t-1} x (1 + R_t)
```
Base index level = 100 at inception (2019q4, the earliest quarter with N-PORT data).

### Rebalancing

Quarterly, following the public index convention. At the start of each quarter:
1. Compute returns for the prior quarter using **beginning-of-quarter constituents only**.
2. Update the constituent list: add new positions that appeared during the quarter, remove positions that exited.
3. Re-weight all positions based on beginning-of-quarter fair values.
4. New entrants and exits do not affect the prior quarter's return.

### Sub-Indices

Computed using the same methodology, filtered by:
- Lien position: first lien, second lien, unsecured (Index 1 only)
- Instrument type: term loan, revolver, delayed draw, bond (Index 1 only)
- Industry sector: using standardised industry groups from Phase 3
- Reference rate: SOFR, EURIBOR, SONIA (proxy for geographic exposure)
- Affiliation: non-controlled vs controlled investments
- Vehicle type: BDC-sourced vs interval/tender-fund-sourced

---

## Phase 5: PME Comparators

### Objective

Build public market equivalent comparisons for each index against relevant public benchmarks.

### Benchmarks

- Index 1 (Direct Lending) vs Morningstar LSTA US Leveraged Loan Index
- Index 1 (Direct Lending) vs ICE BofA US High Yield Index
- Index 2 (Direct Equity) vs Russell 2000 Value Index
- Index 2 (Direct Equity) vs S&P 600 Small Cap Index
- Index 3 (Credit Funds) vs Index 1 (the fund-level credit return vs the asset-level credit return)
- Index 4 (Equity Funds) vs Index 2 (the fund-level equity return vs the asset-level equity return)

### Methodologies

**Kaplan-Schoar PME**: Ratio of discounted distributions to discounted contributions, using the public benchmark as the discount rate. PME > 1.0 means private outperformed.

**Direct Alpha**: Annualised excess return extracted from the PME ratio. More intuitive for most users.

**mPME (modified PME / Cambridge Associates method)**: Produces a time-weighted return series for the private index that can be plotted alongside the public benchmark on the same chart. Most visually compelling for presentations.

### Cash Flow Construction

For PME purposes, approximate cash flows from the position-level data:
- Contributions: cost basis of new positions appearing in a quarter
- Distributions: cost basis reductions (repayments/returns of capital) + income (estimated from coupons)
- Residual value: ending fair value of all active positions

Quarterly cash flow timing assumption: all flows occur at quarter-end (standard in the industry for quarterly PME calculations).

---

## Automation and Operations

### GitHub Actions Workflows

**Weekly incremental update** (runs every Sunday)
1. Query EDGAR filing index for new BDC 10-K/10-Q and N-PORT filings since last run.
2. Download new filings to Layer 1.
3. Parse new filings into Layer 2.
4. Run entity resolution on new investee names (incremental — only process names not already in the resolution table).
5. Recompute Layer 3 (index values, constituent files, website JSON).
6. Commit updated data files to repo.
7. Vercel auto-rebuilds the website.

**Quarterly full rebuild** (runs on 15th of March, June, September, December)
1. Re-scan the full universe using all discovery methods.
2. Re-download any filings that may have been amended.
3. Re-parse all filings into Layer 2 (full rebuild, not incremental).
4. Re-run entity resolution across the full dataset.
5. Recompute all historical index values.
6. Regenerate all download files.
7. Commit and deploy.

**Error handling**
- If EDGAR is unreachable or rate-limited, retry with exponential backoff up to 3 attempts, then fail the workflow and send email notification.
- If a filing fails to parse, log the error, skip it, and continue. Unparseable filings are flagged for manual investigation.
- If entity resolution LLM calls fail, fall back to fuzzy matching only for that run.

### EDGAR Rate Limiting

- Maximum 10 requests per second.
- User-Agent header: `PrivateMarketsIndex/1.0 (contact@yourdomain.com)`
- Implement a request queue with configurable delay (default 100ms between requests).
- Cache all downloaded files in Layer 1; never re-download a filing that's already cached.

### Monitoring

- GitHub Actions workflow status (email on failure).
- Data freshness check: the weekly workflow logs the number of new filings found. If zero new filings are found for two consecutive runs during a typical filing season (Feb-Mar, May, Aug, Nov), flag for investigation.
- Universe change log: log every entity added to or removed from the universe, with reason.
