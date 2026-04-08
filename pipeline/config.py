"""Configuration constants for the SEC universe-building pipeline."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEC_DATASETS_DIR = RAW_DIR / "sec_datasets"
FILINGS_DIR = RAW_DIR / "filings"
THIRD_PARTY_DIR = RAW_DIR / "third_party"
OUTPUT_DIR = DATA_DIR / "output"

# Cache for downloaded N-2 cover pages (150KB each)
N2_HEADERS_CACHE_DIR = RAW_DIR / "n2_headers_cache"

# Cache for downloaded XBRL instance documents (10-K/10-Q filings)
BDC_XBRL_CACHE_DIR = RAW_DIR / "filings" / "bdc_xbrl"

# N-PORT holdings extraction cache directories
NPORT_TSV_CACHE_DIR = SEC_DATASETS_DIR / "nport_quarterly"
NPORT_XML_CACHE_DIR = RAW_DIR / "filings" / "nport_xml"

# Ensure directories exist on import
for d in [SEC_DATASETS_DIR, FILINGS_DIR, THIRD_PARTY_DIR, OUTPUT_DIR,
          N2_HEADERS_CACHE_DIR, BDC_XBRL_CACHE_DIR,
          NPORT_TSV_CACHE_DIR, NPORT_XML_CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# EDGAR HTTP settings
# ---------------------------------------------------------------------------
# SEC requires a User-Agent with company name, contact name, and email.
# Update this to your own information before running.
USER_AGENT = "algercjames@gmail.com"

# SEC fair-access policy: max 10 requests per second
REQUEST_DELAY_SECONDS = 0.11  # ~9 req/sec to stay safely under limit
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # seconds multiplied by retry number

# ---------------------------------------------------------------------------
# Multi-quarter N-CEN: scan all available quarters
# ---------------------------------------------------------------------------
NCEN_QUARTERS = [
    "2022q1", "2022q2", "2022q3", "2022q4",
    "2023q1", "2023q2", "2023q3", "2023q4",
    "2024q1", "2024q2", "2024q3", "2024q4",
    "2025q1", "2025q2", "2025q3", "2025q4",
]

# N-2 index scan range
INDEX_SCAN_START_YEAR = 2015

# Activity confirmation — months back to consider "active"
ACTIVITY_LOOKBACK_MONTHS = 18

# EFTS text search queries for interval/tender discovery
EFTS_INTERVAL_QUERIES = [
    '"interval fund"',
    '"Rule 23c-3"',
    '"periodic repurchase offer"',
]
EFTS_TENDER_QUERIES = [
    '"tender offer fund"',
    '"periodic tender offer"',
]

# ---------------------------------------------------------------------------
# SEC bulk data sets (DERA)
# Quarterly ZIPs — format: {year}q{quarter}_{type}.zip
# Update DATASET_QUARTER to target a specific filing period.
# ---------------------------------------------------------------------------
DATASET_QUARTER = "2025q4"

# BDC data set — monthly ZIPs (e.g. 2026_02_bdc.zip)
# Path: /files/structureddata/data/business-development-company-bdc-data-sets/
BDC_DATASET_URL = (
    "https://www.sec.gov/files/structureddata/data/"
    "business-development-company-bdc-data-sets/2026_02_bdc.zip"
)

# N-CEN data set (quarterly TSV files inside ZIP)
NCEN_DATASET_URL = (
    f"https://www.sec.gov/files/dera/data/"
    f"form-n-cen-data-sets/{DATASET_QUARTER}_ncen.zip"
)

# N-PORT data set (quarterly TSV files inside ZIP)
NPORT_DATASET_URL = (
    f"https://www.sec.gov/files/dera/data/"
    f"form-n-port-data-sets/{DATASET_QUARTER}_nport.zip"
)

# ---------------------------------------------------------------------------
# Third-party list URLs
# ---------------------------------------------------------------------------
INTERVAL_FUND_TRACKER_URL = "https://www.intervalfundtracker.com"
TENDER_OFFER_FUNDS_URL = "https://www.tenderofferfunds.com"
SURE_DIVIDEND_BDC_URL = "https://www.suredividend.com/bdc-list/"
CEFA_INTERVAL_URL = "https://www.cefa.com/FundSelector/IntervalFunds"

# ---------------------------------------------------------------------------
# Output file names
# ---------------------------------------------------------------------------
BDC_UNIVERSE_FILE = OUTPUT_DIR / "bdc_universe.csv"
FUND_UNIVERSE_FILE = OUTPUT_DIR / "fund_universe.csv"
COMBINED_UNIVERSE_FILE = OUTPUT_DIR / "combined_universe.csv"
COMBINED_UNIVERSE_JSON = OUTPUT_DIR / "combined_universe.json"
VALIDATION_REPORT_FILE = OUTPUT_DIR / "validation_report.csv"
EXHAUSTIVE_FUND_UNIVERSE_FILE = OUTPUT_DIR / "exhaustive_fund_universe.csv"
BDC_FILINGS_INDEX_FILE = OUTPUT_DIR / "bdc_filings_index.csv"
BDC_HOLDINGS_FILE = OUTPUT_DIR / "bdc_holdings.csv"
BDC_PARSE_PROGRESS_FILE = OUTPUT_DIR / "bdc_parse_progress.csv"

# N-PORT output files
NPORT_HOLDINGS_FILE = OUTPUT_DIR / "nport_holdings.csv"
NPORT_FILINGS_INDEX_FILE = OUTPUT_DIR / "nport_filings_index.csv"
NPORT_FUND_INFO_FILE = OUTPUT_DIR / "nport_fund_info.csv"
NPORT_PARSE_PROGRESS_FILE = OUTPUT_DIR / "nport_parse_progress.csv"

# Unified private markets holdings
UNIFIED_HOLDINGS_FILE = OUTPUT_DIR / "private_markets_holdings.csv"

# Entity resolution outputs
ENTITY_LOOKUP_FILE = OUTPUT_DIR / "entity_lookup.csv"
ENTITY_STATS_FILE = OUTPUT_DIR / "entity_resolution_stats.csv"

# Holdings validation outputs
HOLDINGS_VALIDATION_REPORT_FILE = OUTPUT_DIR / "holdings_validation_report.csv"
HOLDINGS_SPOT_CHECK_FILE = OUTPUT_DIR / "holdings_spot_check.csv"
HOLDINGS_COVERAGE_FILE = OUTPUT_DIR / "holdings_coverage.csv"
HOLDINGS_CROSS_SOURCE_FILE = OUTPUT_DIR / "holdings_cross_source.csv"
HOLDINGS_TOTAL_ASSETS_FILE = OUTPUT_DIR / "holdings_total_assets.csv"

# Position matching and index returns
POSITION_MATCHES_FILE = OUTPUT_DIR / "position_matches.csv"
POSITION_RETURNS_FILE = OUTPUT_DIR / "position_returns.csv"
INDEX_RETURNS_FILE = OUTPUT_DIR / "index_returns.csv"

# Fund-level income and fee uplift
BDC_FUND_INCOME_FILE = OUTPUT_DIR / "bdc_fund_income.csv"
FEE_UPLIFT_FILE = OUTPUT_DIR / "fee_uplift.csv"

# LLM review outputs
LLM_REVIEW_CANDIDATES_FILE = OUTPUT_DIR / "llm_review_candidates.csv"
LLM_REVIEW_LOOKUP_FILE = OUTPUT_DIR / "llm_review_lookup.csv"

# Identifier extraction outputs
IDENTIFIER_EXTRACTION_LOOKUP_FILE = OUTPUT_DIR / "identifier_extraction_lookup.csv"

# ---------------------------------------------------------------------------
# Database (for --load-db)
# ---------------------------------------------------------------------------
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://localhost:5432/private_markets"
)

# ---------------------------------------------------------------------------
# Frontend display cutoff -- exclude incomplete quarters from the frontend.
# Set to None to include all available quarters.
# ---------------------------------------------------------------------------
INDEX_DISPLAY_END_QUARTER: str | None = "2025q4"

# ---------------------------------------------------------------------------
# N-PORT holdings extraction settings
# ---------------------------------------------------------------------------
NPORT_QUARTERS = [
    "2019q4",
    "2020q1", "2020q2", "2020q3", "2020q4",
    "2021q1", "2021q2", "2021q3", "2021q4",
    "2022q1", "2022q2", "2022q3", "2022q4",
    "2023q1", "2023q2", "2023q3", "2023q4",
    "2024q1", "2024q2", "2024q3", "2024q4",
    "2025q1", "2025q2", "2025q3", "2025q4",
    "2026q1",
]

NPORT_DATASET_URL_TEMPLATE = (
    "https://www.sec.gov/files/dera/data/"
    "form-n-port-data-sets/{quarter}_nport.zip"
)

# ---------------------------------------------------------------------------
# BDC XBRL holdings extraction settings
# ---------------------------------------------------------------------------
BDC_XBRL_START_YEAR = 2013
BDC_FILING_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
