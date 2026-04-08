# Private Markets Index: v1 Implementation Guide for Claude Code

## What This Document Is

This is the complete implementation guide for building v1 of the Private Markets Index — a free, open-source transparency tool for the wealth channel semi-liquid private markets universe. It is written for Claude Code to execute end-to-end.

Three companion documents exist for reference:
- `private_markets_index_spec.md` — full data architecture, schema definitions, and future-phase specifications
- `frontend_spec.md` — website design, page specifications, and content tone
- `additional_analytics_spec.md` — analytical modules beyond the core indices

This document specifies what to build for v1, in what order, with what tools, and what "done" looks like at each step.

---

## v1 Scope

v1 delivers a working end-to-end system: data pipeline → index computation → static website. It covers:

1. Universe identification for BDCs and interval/tender offer funds
2. Full data extraction into a three-layer architecture
3. Rule-based entity resolution (no LLM in v1 — fuzzy matching only)
4. Four position-level indices + one vehicle-level index
5. A static Next.js website deployed on Vercel with core pages
6. GitHub Actions automation for weekly updates

v1 uses **Q2 2025** as the initial target period, then extends to all available historical data.

v1 does **not** include: LLM-assisted entity resolution, PME comparators, the quarterly research report, individual vehicle pages, or the full analytics suite. These are documented in the companion specs for future phases.

---

## Project Structure

```
private-markets-index/
├── pipeline/                          # Python data pipeline
│   ├── pyproject.toml                 # Dependencies: duckdb, requests, lxml, pandas,
│   │                                  #   rapidfuzz, pyarrow, openpyxl
│   ├── config.py                      # EDGAR settings, paths, constants
│   ├── edgar/                         # EDGAR interaction layer
│   │   ├── client.py                  # HTTP client with rate limiting and User-Agent
│   │   ├── filing_index.py            # Quarterly filing index parsing
│   │   ├── xbrl_parser.py             # BDC XBRL instance document parser
│   │   ├── nport_parser.py            # N-PORT XML parser
│   │   ├── ncen_parser.py             # N-CEN XML parser
│   │   └── downloader.py              # Filing download and Layer 1 storage
│   ├── universe/                      # Phase 1: Universe identification
│   │   ├── bdc_discovery.py           # Multi-method BDC identification
│   │   ├── fund_discovery.py          # Interval/tender fund identification
│   │   ├── universe_builder.py        # Merge, validate, output combined universe
│   │   └── validators.py              # Cross-validation against SEC datasets
│   ├── extraction/                    # Phase 2: Data extraction
│   │   ├── bdc_extractor.py           # BDC XBRL → Layer 2 tables
│   │   ├── nport_extractor.py         # N-PORT XML → Layer 2 tables
│   │   ├── ncen_extractor.py          # N-CEN XML → Layer 2 tables
│   │   └── sec_dataset_loader.py      # Load SEC pre-built datasets for validation
│   ├── resolution/                    # Phase 3: Entity resolution
│   │   ├── normaliser.py              # Name cleaning and normalisation
│   │   ├── fuzzy_matcher.py           # Fuzzy matching with rapidfuzz
│   │   ├── attribute_matcher.py       # Matching on spread, maturity, CUSIP, industry
│   │   ├── fund_classifier.py         # Rule-based fund name → strategy classification
│   │   ├── industry_standardiser.py   # ~300 raw industry labels → ~60 canonical labels
│   │   └── resolver.py                # Orchestrates resolution pipeline
│   ├── indices/                       # Phase 4: Index construction
│   │   ├── returns.py                 # Position-level return computation
│   │   ├── weighting.py               # Fair-value, equal, cost weighting
│   │   ├── index_builder.py           # Chain-linking, rebalancing, sub-indices
│   │   ├── vehicle_index.py           # Vehicle-level NAV return index
│   │   └── classifications.py         # Position → index classification logic
│   ├── output/                        # Phase 5: Generate website data
│   │   ├── json_generator.py          # Layer 3 JSON files for website
│   │   ├── download_generator.py      # CSV, XLSX, Parquet download files
│   │   └── summary_generator.py       # Homepage summary statistics
│   ├── db/                            # Database
│   │   ├── schema.py                  # DuckDB schema creation
│   │   └── queries.py                 # Common analytical queries
│   ├── run_full.py                    # Full pipeline execution (all phases)
│   ├── run_incremental.py             # Incremental update (new filings only)
│   └── tests/                         # Tests
│       ├── test_xbrl_parser.py
│       ├── test_nport_parser.py
│       ├── test_entity_resolution.py
│       ├── test_returns.py
│       └── fixtures/                  # Sample filings for testing
├── website/                           # Next.js static site
│   ├── package.json
│   ├── next.config.js                 # Static export configuration
│   ├── tailwind.config.js
│   ├── public/
│   │   └── data/                      # ← Pipeline output JSON lands here
│   │       ├── indices.json
│   │       ├── summary.json
│   │       ├── universe.json
│   │       └── constituents/
│   │       └── downloads/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx             # Root layout with nav
│   │   │   ├── page.tsx               # Homepage
│   │   │   ├── indices/
│   │   │   │   └── [slug]/
│   │   │   │       └── page.tsx       # Index detail page
│   │   │   ├── methodology/
│   │   │   │   └── page.tsx
│   │   │   ├── data/
│   │   │   │   └── page.tsx           # Downloads page
│   │   │   └── about/
│   │   │       └── page.tsx
│   │   ├── components/
│   │   │   ├── IndexCard.tsx           # Homepage index summary card
│   │   │   ├── PerformanceChart.tsx    # Recharts time series
│   │   │   ├── ReturnBarChart.tsx      # Quarterly return bars
│   │   │   ├── DataTable.tsx           # Sortable data table
│   │   │   ├── StatPanel.tsx           # Key statistics display
│   │   │   ├── SectorBreakdown.tsx     # Horizontal bar chart
│   │   │   ├── Nav.tsx                 # Navigation header
│   │   │   └── Footer.tsx
│   │   ├── lib/
│   │   │   ├── data.ts                # JSON data loading utilities
│   │   │   └── formatting.ts          # Number/date formatting
│   │   └── styles/
│   │       └── globals.css
│   └── tsconfig.json
├── data/                              # Data directory (gitignored except output)
│   ├── raw/                           # Layer 1: raw filings (gitignored)
│   │   ├── filings/
│   │   └── sec_datasets/
│   ├── db/                            # Layer 2: DuckDB database (gitignored)
│   │   └── private_markets.duckdb
│   └── output/                        # Layer 3: website JSON + downloads (committed)
│       ├── indices.json
│       ├── summary.json
│       ├── universe.json
│       ├── constituents/
│       ├── vehicles/
│       └── downloads/
├── .github/
│   └── workflows/
│       ├── weekly_update.yml          # Weekly incremental update
│       └── quarterly_rebuild.yml      # Quarterly full rebuild
├── README.md
└── .gitignore
```

---

## Implementation Order

Build in this exact sequence. Each step produces testable output before the next begins.

### Step 1: Project Scaffolding and Configuration

Set up the repo structure, dependencies, and configuration.

**pipeline/pyproject.toml**
```toml
[project]
name = "private-markets-index"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "duckdb>=1.0",
    "requests>=2.31",
    "lxml>=5.0",
    "pandas>=2.1",
    "pyarrow>=15.0",
    "rapidfuzz>=3.6",
    "openpyxl>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]
```

**pipeline/config.py**
```python
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FILINGS_DIR = RAW_DIR / "filings"
SEC_DATASETS_DIR = RAW_DIR / "sec_datasets"
DB_PATH = DATA_DIR / "db" / "private_markets.duckdb"
OUTPUT_DIR = DATA_DIR / "output"
WEBSITE_DATA_DIR = PROJECT_ROOT / "website" / "public" / "data"

# EDGAR settings
EDGAR_USER_AGENT = "PrivateMarketsIndex/1.0 (your-email@example.com)"  # CHANGE THIS
EDGAR_RATE_LIMIT_SECONDS = 0.11  # ~9 requests/sec, under the 10/sec limit
EDGAR_BASE_URL = "https://www.sec.gov"
EDGAR_DATA_URL = "https://data.sec.gov"
EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST"

# Filing index base URL
EDGAR_FULL_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index"

# SEC dataset URLs
BDC_DATASET_BASE = "https://www.sec.gov/files/structureddata/data/business-development-company-bdc-data-sets"
NPORT_DATASET_BASE = "https://www.sec.gov/files/dera/data/form-n-port-data-sets"
NCEN_DATASET_URL = "https://www.sec.gov/data-research/sec-markets-data/form-n-cen-data-sets"

# Universe identification
BDC_FILE_NUMBER_PREFIX = "814-"
PRIVATE_MARKET_HOLDINGS_THRESHOLD = 0.25  # 25% of portfolio to qualify as private market fund

# Index construction
INDEX_BASE_VALUE = 100.0
INDEX_START_LABEL = "Q4 2022"  # Earliest BDC dataset period

# Classification
DIRECT_LENDING_ASSET_CATS = {"loan", "debt"}
DIRECT_EQUITY_ASSET_CATS = {"equity-common", "equity-preferred"}
FUND_ISSUER_CATS = {"private fund", "registered fund"}
CORPORATE_ISSUER_CAT = "corporate"
```

**Done when**: `pip install -e .` succeeds, all directories created, config imports cleanly.

### Step 2: EDGAR Client

Build the HTTP layer that respects rate limits and caches responses.

**pipeline/edgar/client.py**

Implement a class `EdgarClient` with:
- `__init__` sets User-Agent header, creates a `requests.Session`
- `get(url) -> requests.Response` with rate limiting (sleep `EDGAR_RATE_LIMIT_SECONDS` between requests) and retry logic (3 attempts with exponential backoff for 5xx errors and rate limit 429 responses)
- `get_json(url) -> dict` — GET and parse JSON
- `get_text(url) -> str` — GET and return text
- `download_file(url, dest_path) -> Path` — download and save to disk, skip if file exists (Layer 1 caching)

All requests must include the User-Agent header from config.

**Done when**: Can successfully fetch `https://data.sec.gov/submissions/CIK0001422183.json` (FS KKR Capital Corp) and parse the JSON response. Rate limiting is observable via logging.

### Step 3: DuckDB Schema

Create all Layer 2 tables.

**pipeline/db/schema.py**

Implement `create_schema(db_path)` that connects to DuckDB and creates all tables defined in the implementation spec:
- `universe`
- `filings`
- `bdc_financials`
- `nport_fund_info`
- `holdings_bdc`
- `holdings_nport`
- `ncen_fund_data`
- `entity_resolution`
- `index_values` (new table for computed index time series)
- `index_constituents` (new table for per-position per-quarter index membership and returns)

Additional tables for index output:
```sql
CREATE TABLE IF NOT EXISTS index_values (
    index_id VARCHAR NOT NULL,         -- 'direct_lending', 'direct_equity', 'credit_funds', 'equity_funds', 'vehicle_nav'
    period DATE NOT NULL,
    index_level DOUBLE,                -- Chain-linked from base 100
    quarterly_return DOUBLE,
    ytd_return DOUBLE,
    trailing_12m_return DOUBLE,
    annualised_return DOUBLE,
    annualised_volatility DOUBLE,
    max_drawdown DOUBLE,
    num_constituents INTEGER,
    total_fair_value DOUBLE,
    total_cost DOUBLE,
    weighted_avg_spread DOUBLE,        -- Direct lending only
    weighted_avg_coupon DOUBLE,        -- Direct lending only
    weighted_avg_maturity_years DOUBLE, -- Direct lending only
    pct_first_lien DOUBLE,            -- Direct lending only
    weighting_method VARCHAR NOT NULL, -- 'fair_value', 'equal', 'cost'
    PRIMARY KEY (index_id, period, weighting_method)
);

CREATE TABLE IF NOT EXISTS index_constituents (
    index_id VARCHAR NOT NULL,
    period DATE NOT NULL,
    canonical_entity_id VARCHAR,       -- From entity resolution (null if unresolved)
    source_vehicle_cik VARCHAR NOT NULL,
    source_accession_number VARCHAR NOT NULL,
    issuer_name VARCHAR NOT NULL,
    instrument_type VARCHAR,
    industry_sector VARCHAR,
    fair_value DOUBLE,
    cost DOUBLE,
    principal_amount DOUBLE,
    coupon_rate DOUBLE,
    spread_bps DOUBLE,
    reference_rate VARCHAR,
    maturity_date DATE,
    quarterly_return DOUBLE,
    capital_return DOUBLE,
    income_return DOUBLE,
    weight_fair_value DOUBLE,
    weight_equal DOUBLE,
    weight_cost DOUBLE,
    classification VARCHAR NOT NULL,   -- 'direct_lending', 'direct_equity', 'credit_fund', 'equity_fund'
    is_new_position BOOLEAN,
    is_exited_position BOOLEAN
);
```

Use DuckDB's native types. Use `VARCHAR` for strings, `DOUBLE` for numbers, `DATE` for dates, `BOOLEAN` for flags. Do not use SQLite-style type affinity.

**Done when**: `create_schema()` runs without error, all tables exist, can insert and query a test row.

### Step 4: Universe Identification — BDCs

Implement the multi-method BDC discovery from the spec.

**pipeline/universe/bdc_discovery.py**

Implement `discover_bdcs(client: EdgarClient, db_path: Path, target_quarter: str) -> int`:

**Method A — Company search API**:
Query `https://efts.sec.gov/LATEST/search-index?q=%22N-54A%22&forms=N-54A&dateRange=custom&startdt=2000-01-01&enddt=2026-12-31` to find all BDC election filings. For each, extract CIK and entity name. Then query for N-54C filings to find withdrawals. Active BDCs = those with N-54A and no subsequent N-54C.

**Method B — Filing index scan**:
For the target quarter (and surrounding quarters to catch filings), download the EDGAR quarterly company index from `{EDGAR_FULL_INDEX_URL}/{year}/QTR{q}/company.idx`. Parse the pipe-delimited file. Filter for form types `10-K`, `10-K/A`, `10-Q`, `10-Q/A`. For each, check if the filing has an 814- file number by fetching the entity's submission history from `https://data.sec.gov/submissions/CIK{cik_padded}.json` and checking the `fileNumber` field.

**Method C — SEC BDC Dataset**:
Download the SEC's BDC dataset ZIP for the target quarter from `{BDC_DATASET_BASE}/{year}q{q}_bdc.zip` (or monthly file). Extract the SUB table (sub.tsv). Every unique CIK in the SUB table is a BDC.

**Cross-validation**:
Merge all three lists. Flag any CIK appearing in only one method for investigation. Log discrepancies. Insert all validated entities into the `universe` table with `vehicle_type = 'bdc'` and `discovery_methods` listing which methods found them.

Also insert all discovered filings into the `filings` table.

**Done when**: Running against Q2 2025 produces a universe of ~100-130 BDC entities stored in DuckDB. Console output shows how many entities each method found and any discrepancies.

### Step 5: Universe Identification — Interval/Tender Offer Funds

**pipeline/universe/fund_discovery.py**

Implement `discover_funds(client: EdgarClient, db_path: Path, target_quarter: str) -> int`:

**Method A — N-CEN dataset**:
Download the N-CEN dataset. Parse for closed-end funds that identify as interval funds or conduct continuous offerings. Extract CIK, series ID, fund name, fund type.

**Method B — EDGAR filing index for N-PORT**:
Scan the quarterly filing index for NPORT-P form types. Extract all CIKs filing N-PORT. Cross-reference against Method A's closed-end fund list to filter out mutual funds and ETFs.

**Method C — Content-based filtering**:
For candidate funds from Methods A and B, download one N-PORT filing per fund and parse the holdings. Compute the percentage of fair value in private market assets:
- `asset_cat` in ('loan', 'debt') AND `issuer_cat` = 'corporate' → private credit
- `asset_cat` in ('equity-common', 'equity-preferred') AND `issuer_cat` = 'corporate' AND no CUSIP → private equity (no CUSIP suggests unlisted)
- `issuer_cat` in ('private fund', 'registered fund') → fund-of-fund private market exposure
- `liquidity_classification` in ('less liquid', 'illiquid') → likely private

Include funds where private market holdings exceed `PRIVATE_MARKET_HOLDINGS_THRESHOLD` (25%).

Classify each fund's primary strategy based on which category dominates: `direct_lending`, `private_equity`, `fund_of_funds`, `multi_strategy`, `other`.

Insert into `universe` and `filings` tables.

**Done when**: Running against Q2 2025 produces ~50-150 fund entities. Each has a primary strategy classification.

### Step 6: Data Extraction — BDC XBRL

**pipeline/edgar/xbrl_parser.py**

Implement `parse_bdc_xbrl(filing_path: Path) -> dict` that parses a BDC XBRL instance document and returns structured data.

The XBRL instance document is XML. Key structures to parse:

1. **Context elements** — define the reporting periods and dimensional breakdowns. Each `<context>` has an ID, a period (instant or duration), and optional dimensional qualifiers (axis/member pairs).

2. **Fact elements** — numeric and text values tagged with US GAAP taxonomy concepts. Each fact references a context ID, has a unit, and a decimal precision.

3. **The Investment Identifier Axis** — a typed dimension. Facts dimensioned by this axis are individual investment positions. The dimension member value is a free-text string describing the investment (company name, instrument type, etc.).

Parsing approach:
- Parse the XML with lxml
- Build a context lookup: context_id → {period, dimensions}
- For each numeric fact, extract: concept name, context_id (→ period + dimensions), value, unit
- Group facts by their `InvestmentIdentifierAxis` dimension value — each unique value is one position
- For each position, extract all associated concept values: `InvestmentOwnedFairValue`, `InvestmentOwnedCost`, `InvestmentInterestRate`, `InvestmentBasisSpreadVariableRate`, `InvestmentMaturityDate`, `InvestmentOwnedBalancePrincipalAmount`, `InvestmentOwnedNetAssetsPercentage`, etc.
- Also extract facts dimensioned by `IndustrySectorAxis` and `InvestmentTypeAxis` (industry and type subtotals)
- Also extract undimensioned facts for fund-level financials (total assets, NAV, income, expenses, etc.)

Note: The XBRL taxonomy uses CamelCase concept names without spaces. The SOI TSV column headers use display labels with spaces. Map between them.

Note: Some filers use inline XBRL (iXBRL) where the facts are embedded in HTML. The extraction approach is the same — lxml can parse the ix: namespace elements. However, for v1 it may be simpler to work with the SEC's pre-extracted BDC dataset NUM and TXT tables rather than parsing raw XBRL. Decide based on data quality assessment.

**Pragmatic v1 approach**: Start by loading the SEC's BDC dataset (SUB, NUM, TAG, SOI tables as TSV files). These give you structured data without needing to write a full XBRL parser. Use the NUM table for fund-level financials and industry/type subtotals. For investee-level detail that the SOI misses, fall back to downloading and parsing the raw XBRL instance document for specific filings.

**pipeline/extraction/bdc_extractor.py**

Implement `extract_bdc_data(db_path: Path, accession_number: str)`:
- Load the filing's XBRL data (from SEC dataset or raw parsing)
- Insert fund-level data into `bdc_financials`
- Insert position-level data into `holdings_bdc`
- Mark the filing as `parsed = true` in `filings` table

**Done when**: Can extract data from the PFLT filing (accession 0001504619) and the BCSF filing (accession 0001655050). Fund financials and position-level holdings appear in DuckDB.

### Step 7: Data Extraction — N-PORT

**pipeline/edgar/nport_parser.py**

Implement `parse_nport(filing_path: Path) -> dict` that parses an N-PORT XML filing.

N-PORT XML structure:
```xml
<edgarSubmission>
  <headerData>...</headerData>
  <formData>
    <genInfo>...</genInfo>          <!-- General fund info -->
    <fundInfo>                      <!-- Fund-level metrics -->
      <totAssets>...</totAssets>
      <totLiabs>...</totLiabs>
      <netAssets>...</netAssets>
      <monthlyTotReturns>
        <monthlyTotReturn1>...</monthlyTotReturn1>
        <monthlyTotReturn2>...</monthlyTotReturn2>
        <monthlyTotReturn3>...</monthlyTotReturn3>
      </monthlyTotReturns>
      <monthlyFlows>...</monthlyFlows>
      <borrowers>...</borrowers>
      ...
    </fundInfo>
    <invstOrSecs>                   <!-- Individual holdings -->
      <invstOrSec>
        <name>...</name>            <!-- Issuer name -->
        <lei>...</lei>
        <title>...</title>          <!-- Title of issue -->
        <cusip>...</cusip>
        <identifiers>...</identifiers>
        <balance>...</balance>       <!-- Quantity/principal -->
        <units>...</units>           <!-- shares, principal amount, etc -->
        <curCd>...</curCd>           <!-- Currency -->
        <valUSD>...</valUSD>         <!-- Fair value in USD -->
        <pctVal>...</pctVal>         <!-- % of NAV -->
        <payoffProfile>...</payoffProfile>
        <assetCat>...</assetCat>     <!-- loan, equity-common, etc -->
        <issuerCat>...</issuerCat>   <!-- corporate, private fund, etc -->
        <invCountry>...</invCountry>
        <isRestrictedSec>...</isRestrictedSec>
        <fairValLevel>...</fairValLevel>  <!-- 1, 2, or 3 -->
        <debtSec>                    <!-- Debt-specific fields -->
          <maturityDt>...</maturityDt>
          <couponKind>...</couponKind>
          <annualizedRt>...</annualizedRt>
          <isDefault>...</isDefault>
          <areIntrstPmntsInArworDeworSchworOthrwise>...</areIntrstPmntsInArworDeworSchworOthrwise>
          <isPaidKind>...</isPaidKind>
        </debtSec>
        <securityLending>...</securityLending>
        <liquidityClassification>...</liquidityClassification>
      </invstOrSec>
      ...
    </invstOrSecs>
  </formData>
</edgarSubmission>
```

Parse with lxml. Iterate over all `invstOrSec` elements. For each, extract every available sub-element into a flat dict. Handle missing elements gracefully (many fields are optional).

**pipeline/extraction/nport_extractor.py**

Implement `extract_nport_data(db_path: Path, accession_number: str)`:
- Parse the N-PORT XML
- Insert fund-level data into `nport_fund_info`
- Insert all holdings into `holdings_nport`
- Mark the filing as parsed

**Done when**: Can extract data from the iDirect Private Credit Fund N-PORT filing (accession 0002042256). All holdings appear in DuckDB with `asset_cat`, `issuer_cat`, fair values, and debt-specific fields populated.

### Step 8: Entity Resolution (Rule-Based v1)

**pipeline/resolution/normaliser.py**

Implement `normalise_name(raw_name: str) -> str`:
- Lowercase
- Strip common legal suffixes: LLC, Inc, Corp, Corporation, Ltd, LP, L.P., LLP, Co, Company, Holdings, Intermediate, Buyer, Borrower, Parent, Acquisition, Merger Sub, [Member]
- Remove punctuation except hyphens
- Normalise whitespace
- Strip leading/trailing whitespace

**pipeline/resolution/fuzzy_matcher.py**

Implement `find_matches(names: list[str], threshold: float = 0.85) -> list[tuple[str, str, float]]`:
- Use `rapidfuzz.process.cdist` or pairwise comparison
- Return pairs of names with similarity score above threshold
- Use token_set_ratio from rapidfuzz (handles word order differences)

**pipeline/resolution/attribute_matcher.py**

Implement `confirm_match(pos_a: dict, pos_b: dict) -> float`:
- Compare additional attributes to confirm or reject fuzzy name matches
- Same CUSIP (from N-PORT) → confidence 1.0 (definitive)
- Same spread ±25bps AND same maturity ±90 days → confidence +0.3
- Same industry sector → confidence +0.2
- Same instrument type (both first lien, both equity) → confidence +0.1
- Return aggregate confidence score

**pipeline/resolution/fund_classifier.py**

Implement `classify_fund(fund_name: str) -> str`:
- Rule-based classification of fund names into strategies
- Credit signals: "credit", "lending", "loan", "debt", "income", "senior", "direct lending", "CLO", "floating rate"
- PE signals: "equity", "buyout", "growth", "capital partners", "venture", "opportunities"
- Real estate signals: "real estate", "property", "REIT", "mortgage"
- If no signal or ambiguous → "other"
- Return one of: "credit", "equity", "real_estate", "other"

**pipeline/resolution/industry_standardiser.py**

Implement `standardise_industry(raw_label: str) -> str`:
- Map ~300+ raw industry labels to ~60 canonical GICS-aligned groups
- Build a lookup dict of known mappings (e.g., "Aerospace & Defense" / "Aerospace And Defense Sector [Member]" / "Aerospace and Defense [Member]" → "Aerospace & Defense")
- For unmatched labels, use fuzzy matching against the canonical list
- Return the canonical label or "Other" if no match

**pipeline/resolution/resolver.py**

Implement `resolve_entities(db_path: Path)`:
1. Load all unique issuer names from `holdings_bdc` and `holdings_nport`
2. Normalise all names
3. Group exact normalised matches → assign same canonical_entity_id
4. For remaining unmatched, run fuzzy matching
5. For fuzzy matches above threshold, run attribute matching to confirm
6. Classify fund investments (issuer_cat = private fund/registered fund) by strategy
7. Standardise all industry labels
8. Insert results into `entity_resolution` table

**Done when**: Entity resolution produces canonical entity IDs. Running on Q2 2025 data, known overlapping borrowers (like Club Car Wash, which appeared in both BDC and interval fund filings) are matched. Fund names are classified. Console output shows match statistics: N exact matches, N fuzzy matches, N unresolved.

### Step 9: Position Classification

**pipeline/indices/classifications.py**

Implement `classify_position(holding: dict, entity_info: dict) -> str | None`:

For N-PORT holdings:
- `asset_cat` in DIRECT_LENDING_ASSET_CATS and `issuer_cat` == CORPORATE_ISSUER_CAT → "direct_lending"
- `asset_cat` in DIRECT_EQUITY_ASSET_CATS and `issuer_cat` == CORPORATE_ISSUER_CAT → "direct_equity"
- `issuer_cat` in FUND_ISSUER_CATS and entity fund classification == "credit" → "credit_fund"
- `issuer_cat` in FUND_ISSUER_CATS and entity fund classification == "equity" → "equity_fund"
- Everything else → None (excluded from indices)

For BDC holdings:
- Parse the investment_type and investment_identifier fields
- Positions with debt-related type labels (first lien, second lien, term loan, revolver, unitranche, mezzanine, subordinated, unsecured) in operating companies → "direct_lending"
- Positions with equity-related type labels (common stock, preferred equity, warrants, equity interest) in operating companies → "direct_equity"
- Positions identified as fund/vehicle investments (from Investment Type Axis containing "Investment Vehicle", "CLO", "Fund", "JV", or from the entity resolution fund classification) → "credit_fund" or "equity_fund" based on strategy classification
- Preferred equity: if it has a stated coupon/spread AND maturity → "direct_lending". Otherwise → "direct_equity"

Implement `classify_all_positions(db_path: Path)`:
- Load all holdings from both tables
- Classify each
- Update `index_constituents` table with classifications

**Done when**: Every holding in the database has a classification or is explicitly excluded. Console output shows counts per classification.

### Step 10: Return Computation

**pipeline/indices/returns.py**

Implement `compute_position_returns(db_path: Path, period: str, prior_period: str)`:

For each position that exists in both the current and prior period (matched by vehicle CIK + issuer name or canonical entity ID + instrument type):

**Direct lending positions**:
```python
capital_return = (current.fair_value - prior.fair_value) / prior.fair_value
quarterly_income = (current.principal_amount * current.coupon_rate) / 4
income_return = quarterly_income / prior.fair_value
total_return = capital_return + income_return
```
If coupon_rate is not available, estimate from spread + assumed SOFR rate (use the 3-month SOFR rate for the quarter, which can be hardcoded for historical quarters or approximated as the fed funds rate from FRED — for v1, hardcode known historical values).

**Direct equity positions**:
```python
total_return = (current.fair_value - prior.fair_value) / prior.fair_value
capital_return = total_return
income_return = 0  # No income component in v1
```

**Fund positions (credit and equity)**:
```python
capital_change = current.fair_value - prior.fair_value
inferred_distribution = max(0, prior.cost - current.cost) if current.cost < prior.cost and current.fair_value >= prior.fair_value * 0.9 else 0
total_return = (capital_change + inferred_distribution) / prior.fair_value
```
The condition on fair_value prevents misclassifying a write-down as a distribution.

**New positions** (exist in current but not prior):
```python
total_return = (current.fair_value - current.cost) / current.cost
is_new_position = True
```

**Exited positions** (exist in prior but not current):
```python
# Position vanished — infer exit at last known fair value
# Return for this quarter is zero (the exit was at the mark)
# The P&L was already reflected in prior quarters' fair value changes
total_return = 0
is_exited_position = True
```

Insert all position-level returns into `index_constituents`.

**Done when**: Position returns are computed for at least two consecutive quarters. Spot-check a few positions manually against the raw filing data.

### Step 11: Index Construction

**pipeline/indices/index_builder.py**

Implement `build_indices(db_path: Path)`:

For each index ('direct_lending', 'direct_equity', 'credit_funds', 'equity_funds'):

1. Load all position returns for each quarter from `index_constituents` where `classification` matches
2. For each quarter, compute three weighted returns:
   - Fair-value weighted: weight_i = fair_value_i / sum(fair_values), index_return = sum(weight_i * return_i)
   - Equal weighted: weight_i = 1/N, index_return = sum(return_i) / N
   - Cost weighted: weight_i = cost_i / sum(costs), index_return = sum(weight_i * return_i)
3. Chain-link: index_level_t = index_level_{t-1} * (1 + quarterly_return)
4. Starting index_level = 100 for the first computable quarter (second quarter of data)
5. Compute rolling statistics: YTD return, trailing 12-month, annualised return, annualised volatility, max drawdown
6. For direct lending: compute weighted average spread, weighted average coupon, weighted average maturity, % first lien
7. Insert into `index_values` table

**pipeline/indices/vehicle_index.py**

Implement `build_vehicle_index(db_path: Path)`:

For BDCs:
- From `bdc_financials`, compute quarterly NAV total return per vehicle: (ending NAV per share + distributions per share - beginning NAV per share) / beginning NAV per share
- Weight by beginning-of-quarter total net assets
- Chain-link

For interval/tender funds:
- From `nport_fund_info`, compound the three monthly returns: (1 + r1) * (1 + r2) * (1 + r3) - 1
- Weight by beginning-of-quarter net assets
- Chain-link

Combine into a single vehicle-level index. Optionally split by vehicle type (traded BDC, non-traded BDC, interval fund, tender offer fund) and by predominant strategy (credit, equity).

Insert into `index_values`.

**Done when**: All five indices have time series in the database. Can query: `SELECT * FROM index_values WHERE index_id = 'direct_lending' AND weighting_method = 'fair_value' ORDER BY period`.

### Step 12: Output Generation

**pipeline/output/json_generator.py**

Generate the JSON files consumed by the website.

**data/output/indices.json**:
```json
{
  "direct_lending": {
    "name": "Direct Lending Index",
    "description": "Tracks the performance of direct loan positions held by SEC-registered wealth channel vehicles",
    "time_series": [
      {"period": "2023-03-31", "level": 100.0, "quarterly_return": null, "ytd_return": null},
      {"period": "2023-06-30", "level": 102.3, "quarterly_return": 0.023, "ytd_return": 0.023},
      ...
    ],
    "latest": {
      "period": "2025-06-30",
      "level": 118.4,
      "quarterly_return": 0.028,
      "ytd_return": 0.054,
      "trailing_12m_return": 0.112,
      "annualised_return": 0.089,
      "annualised_volatility": 0.034,
      "max_drawdown": -0.042,
      "num_constituents": 4523,
      "total_fair_value": 142000000000,
      "weighted_avg_spread_bps": 487,
      "weighted_avg_coupon_pct": 9.12,
      "pct_first_lien": 0.82,
      "pct_positive_quarters": 0.89
    }
  },
  "direct_equity": { ... },
  "credit_funds": { ... },
  "equity_funds": { ... },
  "vehicle_nav": { ... }
}
```

**data/output/summary.json**:
```json
{
  "as_of_date": "2025-06-30",
  "total_vehicles": 187,
  "total_fair_value": 285000000000,
  "indices": {
    "direct_lending": { "level": 118.4, "quarterly_return": 0.028, "trailing_12m": 0.112, "sparkline": [100, 102.3, ...] },
    "direct_equity": { ... },
    "credit_funds": { ... },
    "equity_funds": { ... },
    "vehicle_nav": { ... }
  }
}
```

**data/output/constituents/direct-lending/2025-Q2.json**:
```json
{
  "period": "2025-06-30",
  "index_id": "direct_lending",
  "num_constituents": 4523,
  "top_20": [
    {
      "name": "Acme Healthcare Holdings",
      "industry": "Health Care Services",
      "aggregate_fair_value": 245000000,
      "aggregate_cost": 248000000,
      "unrealised_gl_pct": -0.012,
      "num_vehicles_holding": 7,
      "avg_spread_bps": 525,
      "primary_seniority": "First Lien",
      "quarterly_return": 0.031
    },
    ...
  ],
  "sector_breakdown": [
    {"sector": "Software", "fair_value": 28500000000, "pct": 0.201},
    {"sector": "Health Care Services", "fair_value": 21300000000, "pct": 0.150},
    ...
  ],
  "seniority_breakdown": [
    {"seniority": "First Lien", "fair_value": 116000000000, "pct": 0.817},
    {"seniority": "Second Lien", "fair_value": 12000000000, "pct": 0.085},
    ...
  ],
  "vehicle_contributions": [
    {"name": "ARES CAPITAL CORP", "vehicle_type": "bdc", "num_positions": 423, "total_fair_value": 11500000000},
    ...
  ]
}
```

**data/output/universe.json**: List of all vehicles with metadata.

**pipeline/output/download_generator.py**

Generate CSV, XLSX (latest quarter only), and Parquet files for downloads:
- Index time series (one file per index + combined)
- Constituent-level data (full historical, Parquet only for size; latest quarter in CSV and XLSX)
- Universe list (CSV and XLSX)

Copy all output files to `website/public/data/` for the static site build.

**Done when**: All JSON files are valid and contain data. Download files are generated. Files copied to website public directory.

### Step 13: Website Build

**website/**

Build the Next.js static site per the frontend spec. Key implementation details:

**next.config.js**:
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',      // Static export, no server
  images: { unoptimized: true },
}
module.exports = nextConfig
```

**Data loading**: All data is loaded from JSON files in `public/data/` using `fetch` at build time (in `generateStaticParams` and page-level data loading). No runtime API calls.

**Pages to implement**:

1. **Homepage** (`src/app/page.tsx`): Load `summary.json`. Render four IndexCard components (one per index showing level, return, sparkline). Render a PerformanceChart showing all indices rebased to 100. Render a summary statistics table.

2. **Index detail pages** (`src/app/indices/[slug]/page.tsx`): Load from `indices.json` and `constituents/{slug}/{latest_quarter}.json`. Implement `generateStaticParams` returning `['direct-lending', 'direct-equity', 'credit-funds', 'equity-funds', 'vehicle-nav']`. Render: large performance chart, quarterly return bar chart, statistics panel, sector breakdown chart, top 20 constituents table, vehicle contribution table.

3. **Methodology** (`src/app/methodology/page.tsx`): Long-form markdown-style content page. Can be hardcoded in v1 — the methodology will evolve with the data.

4. **Data downloads** (`src/app/data/page.tsx`): List download files with direct links to `/data/downloads/`. Include an embedded data dictionary.

5. **About** (`src/app/about/page.tsx`): Static content per frontend spec.

**Key components**:

- `PerformanceChart`: Recharts `LineChart` with `ResponsiveContainer`. X-axis: quarter labels. Y-axis: index level. Toggle to show/hide individual series. Dark navy line colours with subtle differentiation.
- `ReturnBarChart`: Recharts `BarChart`. Positive returns in teal, negative in red. One bar per quarter.
- `DataTable`: Sortable HTML table with `thead`/`tbody` semantics. Tabular number formatting. Alternating row colours. Sticky header.
- `IndexCard`: Compact card showing index name, level (large), quarterly return with directional colour, 12m return, sparkline (Recharts `LineChart` with no axes, just the line).

**Styling**: Tailwind CSS. Dark navy (#0F1B2D) for headers. Inter font with tabular figures for numbers. Minimal colour — teal accent for positive, red for negative, greys for secondary. Off-white (#F8F9FA) backgrounds.

**Done when**: `npm run build` succeeds with static export. All five pages render with real data from the JSON files. No runtime errors. Lighthouse performance score >90.

### Step 14: GitHub Actions

**.github/workflows/weekly_update.yml**:
```yaml
name: Weekly Data Update
on:
  schedule:
    - cron: '0 2 * * 0'  # Every Sunday at 2am UTC
  workflow_dispatch:       # Allow manual trigger

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install pipeline dependencies
        run: |
          cd pipeline
          pip install -e .

      - name: Run incremental update
        run: python pipeline/run_incremental.py

      - name: Build website
        run: |
          cd website
          npm ci
          npm run build

      - name: Commit and push if changed
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add data/output/ website/public/data/
          git diff --staged --quiet || git commit -m "Weekly data update $(date +%Y-%m-%d)"
          git push
```

**.github/workflows/quarterly_rebuild.yml**:
Same structure but runs `python pipeline/run_full.py` and is scheduled for the 15th of March, June, September, December.

**pipeline/run_incremental.py**:
```python
"""Incremental update: check for new filings, process, recompute indices."""
# 1. Check EDGAR for new filings since last run
# 2. Download new filings to Layer 1
# 3. Parse into Layer 2
# 4. Run entity resolution on new names only
# 5. Recompute Layer 3 for the latest quarter
# 6. Generate website JSON and download files
```

**pipeline/run_full.py**:
```python
"""Full rebuild: re-discover universe, re-parse all filings, rebuild everything."""
# 1. Run full universe identification
# 2. Download all filings
# 3. Parse all filings into Layer 2
# 4. Run full entity resolution
# 5. Compute all historical index values
# 6. Generate all output files
```

**Done when**: Both workflows run successfully in GitHub Actions. Manual trigger works. Incremental update completes in <10 minutes.

---

## Testing Strategy

### Unit Tests

- `test_xbrl_parser.py`: Parse a known BDC filing, assert specific values match the filing (e.g., PFLT Q4 2025 total net assets = $1,040,429,000)
- `test_nport_parser.py`: Parse iDirect N-PORT, assert PlayPower Term Loan fair_value = 3,500,000, spread = 500bps
- `test_entity_resolution.py`: Assert that known matches resolve (normalise "ACP Avenu Buyer, LLC [Member]" and "ACP Avenu Buyer LLC" produce the same normalised form). Assert known non-matches don't resolve.
- `test_returns.py`: Hand-compute returns for 3-4 positions and assert the code matches. Test edge cases: new position, exited position, partial repayment.

### Integration Tests

- Full pipeline test: run `run_full.py` on a small subset of filings (5 BDCs, 3 interval funds, 2 quarters). Assert all tables are populated, indices are computed, JSON output is valid.
- Website build test: assert `npm run build` succeeds and all pages are generated.

### Fixtures

Store sample filings in `pipeline/tests/fixtures/`:
- One BDC XBRL instance document (PFLT or a smaller filer)
- One N-PORT XML filing (iDirect)
- Corresponding expected parsed output as JSON

---

## Definition of Done for v1

v1 is complete when:

1. **Universe**: >80% of known BDCs and >50% of known private-credit-focused interval/tender funds are identified and in the database.
2. **Data**: At least 4 consecutive quarters of position-level data are extracted for the majority of the universe.
3. **Entity Resolution**: >90% of positions have a canonical entity ID. Known cross-vehicle overlaps (same borrower in multiple vehicles) are identified.
4. **Indices**: All five indices have quarterly time series with at least 4 data points. Index values are reasonable (no returns >50% or <-50% in a single quarter, which would indicate a parsing error).
5. **Website**: All five pages render correctly with real data. Lighthouse score >90. Deployed on Vercel with a custom domain.
6. **Automation**: Weekly GitHub Actions workflow runs successfully at least once.
7. **Downloads**: CSV and Parquet files are downloadable from the website and contain complete constituent-level data.
8. **Documentation**: README explains what the project is and how to run the pipeline. Methodology page explains the index construction.
