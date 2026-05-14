"""Configuration constants for the SEC universe-building pipeline."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = DATA_DIR / "reference"
SEC_DATASETS_DIR = RAW_DIR / "sec_datasets"
FILINGS_DIR = RAW_DIR / "filings"
THIRD_PARTY_DIR = RAW_DIR / "third_party"
OUTPUT_DIR = DATA_DIR / "output"
OVERRIDES_DIR = DATA_DIR / "overrides"

# Cache for downloaded N-2 cover pages (150KB each)
N2_HEADERS_CACHE_DIR = RAW_DIR / "n2_headers_cache"

# Cache for downloaded XBRL instance documents (10-K/10-Q filings)
BDC_XBRL_CACHE_DIR = RAW_DIR / "filings" / "bdc_xbrl"

# N-PORT holdings extraction cache directories
NPORT_TSV_CACHE_DIR = SEC_DATASETS_DIR / "nport_quarterly"
NPORT_XML_CACHE_DIR = RAW_DIR / "filings" / "nport_xml"

# HTML holdings extraction cache (pre-XBRL 10-K/10-Q filings)
BDC_HTML_CACHE_DIR = RAW_DIR / "filings" / "bdc_html"

# HTML template-based extraction
HTML_TEMPLATE_DIR = RAW_DIR / "filing_templates"

# companyfacts API cache (one JSON per CIK, ~100KB each)
COMPANYFACTS_CACHE_DIR = RAW_DIR / "companyfacts_cache"

# Ensure directories exist on import
for d in [SEC_DATASETS_DIR, FILINGS_DIR, THIRD_PARTY_DIR, OUTPUT_DIR,
          N2_HEADERS_CACHE_DIR, BDC_XBRL_CACHE_DIR,
          NPORT_TSV_CACHE_DIR, NPORT_XML_CACHE_DIR,
          BDC_HTML_CACHE_DIR, HTML_TEMPLATE_DIR,
          COMPANYFACTS_CACHE_DIR, REFERENCE_DIR,
          RAW_DIR / "filings" / "ncsr_html",
          OVERRIDES_DIR]:
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

# Manual row-level corrections overlay (checked into data/overrides/)
ROW_CORRECTIONS_FILE = OVERRIDES_DIR / "row_corrections.csv"

# Entity resolution outputs
ENTITY_LOOKUP_FILE = OUTPUT_DIR / "entity_lookup.csv"
ENTITY_STATS_FILE = OUTPUT_DIR / "entity_resolution_stats.csv"

# Holdings validation outputs
HOLDINGS_VALIDATION_REPORT_FILE = OUTPUT_DIR / "holdings_validation_report.csv"
HOLDINGS_SPOT_CHECK_FILE = OUTPUT_DIR / "holdings_spot_check.csv"
HOLDINGS_COVERAGE_FILE = OUTPUT_DIR / "holdings_coverage.csv"
HOLDINGS_CROSS_SOURCE_FILE = OUTPUT_DIR / "holdings_cross_source.csv"
HOLDINGS_TOTAL_ASSETS_FILE = OUTPUT_DIR / "holdings_total_assets.csv"
CLASSIFICATION_VALIDATION_FILE = OUTPUT_DIR / "classification_validation.csv"
HOLDINGS_GAV_RECONCILIATION_FILE = OUTPUT_DIR / "holdings_gav_reconciliation.csv"
HOLDINGS_PCT_SUM_FILE = OUTPUT_DIR / "holdings_pct_sum.csv"
HOLDINGS_COUNT_STABILITY_FILE = OUTPUT_DIR / "holdings_count_stability.csv"
HOLDINGS_INCOME_YIELD_FILE = OUTPUT_DIR / "holdings_income_yield.csv"
COLUMN_QUALITY_METRICS_FILE = OUTPUT_DIR / "column_quality_metrics.csv"
ROW_VALIDATION_ISSUES_FILE = OUTPUT_DIR / "row_validation_issues.csv"
DATA_QUALITY_METRICS_FILE = OUTPUT_DIR / "data_quality_metrics.csv"

# Position matching and index returns
POSITION_MATCHES_FILE = OUTPUT_DIR / "position_matches.csv"
POSITION_RETURNS_FILE = OUTPUT_DIR / "position_returns.csv"
INDEX_RETURNS_FILE = OUTPUT_DIR / "index_returns.csv"

# Fund-level income and fee uplift
BDC_FUND_INCOME_FILE = OUTPUT_DIR / "bdc_fund_income.csv"
FEE_UPLIFT_FILE = OUTPUT_DIR / "fee_uplift.csv"
FUND_FINANCIALS_FILE = OUTPUT_DIR / "fund_financials.csv"
FUND_IDENTITY_FILE = OUTPUT_DIR / "fund_identity.csv"
BDC_SECTOR_BREAKDOWN_FILE = OUTPUT_DIR / "bdc_sector_breakdown.csv"
FUND_FINANCIALS_VALIDATION_CURRENT_FILE = OUTPUT_DIR / "fund_financials_validation_current.csv"
FUND_FINANCIALS_QUALITY_METRICS_FILE = OUTPUT_DIR / "fund_financials_quality_metrics.csv"
FUND_FINANCIALS_CROSS_LEVEL_FILE = OUTPUT_DIR / "fund_financials_cross_level.csv"

# GICS industry mapping
GICS_REFERENCE_FILE = REFERENCE_DIR / "gics_sub_industries.json"
GICS_HIERARCHY_FILE = REFERENCE_DIR / "gics_hierarchy.json"
GICS_LABEL_CACHE_FILE = OUTPUT_DIR / "gics_label_cache.csv"
COMPANY_GICS_CACHE_FILE = OUTPUT_DIR / "company_gics_cache.csv"

# LLM review outputs
LLM_REVIEW_CANDIDATES_FILE = OUTPUT_DIR / "llm_review_candidates.csv"
LLM_REVIEW_LOOKUP_FILE = OUTPUT_DIR / "llm_review_lookup.csv"

# LLM fund classification validation
LLM_FUND_VALIDATION_CACHE_FILE = OUTPUT_DIR / "llm_fund_validation_cache.csv"
LLM_FUND_VALIDATION_RESULTS_FILE = OUTPUT_DIR / "llm_fund_validation_results.csv"
LLM_FUND_CLASSIFICATION_REVIEW_FILE = OUTPUT_DIR / "llm_fund_classification_review.csv"

# Identifier extraction outputs
IDENTIFIER_EXTRACTION_LOOKUP_FILE = OUTPUT_DIR / "identifier_extraction_lookup.csv"

# N-CSR filing and financial highlights extraction
NCSR_HTML_CACHE_DIR = RAW_DIR / "filings" / "ncsr_html"
NCSR_FILINGS_INDEX_FILE = OUTPUT_DIR / "ncsr_filings_index.csv"
NCSR_FINANCIALS_FILE = OUTPUT_DIR / "ncsr_financials.csv"

# HTML holdings extraction outputs
HTML_EXTRACTION_FILE = OUTPUT_DIR / "html_extraction_holdings.csv"
HTML_EXTRACTION_EXPERIMENT_FILE = OUTPUT_DIR / "html_extraction_experiment.csv"

# HTML template validation (aggregate FV + carry rate checks)
HTML_TEMPLATE_VALIDATION_FILE = OUTPUT_DIR / "html_template_validation.csv"

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

# CIKs to exclude from unified holdings (consumer/marketplace lending funds
# that report millions of individual loan rows with opaque numeric IDs).
# Data is kept in nport_holdings.csv but filtered out during --unified.
NPORT_EXCLUDE_CIKS: set[str] = {
    "1658645",   # Stone Ridge Trust V (~20M consumer loan rows)
    "1644771",   # RiverNorth Marketplace Lending (opaque numeric IDs, <$1B FV)
    "1678130",   # RiverNorth/DoubleLine Strategic Opp (opaque numeric IDs, <$1B FV)
    "2041175",   # NB Direct Private Lending (opaque numeric IDs, <$0.5B FV)
}

# ---------------------------------------------------------------------------
# BDC XBRL holdings extraction settings
# ---------------------------------------------------------------------------
BDC_XBRL_START_YEAR = 2013
BDC_FILING_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A"}

# ---------------------------------------------------------------------------
# CIK-to-manager-brand mapping (curated for manager concentration charts)
# Only CIKs with actual position-level holdings data are included.
# Unmapped CIKs fall back to entity_name in the frontend export.
# ---------------------------------------------------------------------------
CIK_TO_MANAGER_BRAND: dict[str, str] = {
    # Ares
    "0001287750": "Ares",
    "0001918712": "Ares",
    "0002031750": "Ares",
    # Apollo
    "0001837532": "Apollo",
    "0002052152": "Apollo",
    "0002052153": "Apollo",
    # Bain Capital
    "0001899017": "Bain Capital",
    "0001655050": "Bain Capital",
    # Barings
    "0001379785": "Barings",
    "0001811972": "Barings",
    "0001859919": "Barings",
    # BlackRock
    "0001326003": "BlackRock",
    "0001370755": "BlackRock",
    # Blackstone
    "0001803498": "Blackstone",
    "0002049733": "Blackstone",
    "0001736035": "Blackstone",
    # Blue Owl
    "0001655888": "Blue Owl",
    "0001655887": "Blue Owl",
    "0001807427": "Blue Owl",
    "0001812554": "Blue Owl",
    "0001747777": "Blue Owl",
    "0001889668": "Blue Owl",
    "0001869453": "Blue Owl",
    # Carlyle
    "0001702510": "Carlyle",
    "0001851277": "Carlyle",
    "0001544206": "Carlyle",
    # Crescent Capital
    "0001633336": "Crescent Capital",
    "0001954360": "Crescent Capital",
    # Eagle Point
    "0002013536": "Eagle Point",
    "0001992148": "Eagle Point",
    "0002027033": "Eagle Point",
    # Franklin BSP
    "0001825248": "Franklin BSP",
    "0001490927": "Franklin BSP",
    "0002063946": "Franklin BSP",
    "0002018545": "Franklin BSP",
    # FS KKR
    "0001422183": "FS KKR",
    "0001501729": "FS KKR",
    # Gladstone
    "0001143513": "Gladstone",
    "0001321741": "Gladstone",
    # Golub Capital
    "0001476765": "Golub Capital",
    "0001868878": "Golub Capital",
    "0001715268": "Golub Capital",
    "0001901612": "Golub Capital",
    "0001901606": "Golub Capital",
    "0001930087": "Golub Capital",
    # Goldman Sachs
    "0001572694": "Goldman Sachs",
    "0001865174": "Goldman Sachs",
    "0001920145": "Goldman Sachs",
    "0001796242": "Goldman Sachs",
    # HPS
    "0001989817": "HPS",
    "0001838126": "HPS",
    # Hercules Capital
    "0001280784": "Hercules Capital",
    # KKR
    "0002012839": "KKR",
    "0001930679": "KKR",
    "0001975736": "KKR",
    "0001803958": "KKR",
    "0002040315": "KKR",
    "0002040318": "KKR",
    # Main Street
    "0001396440": "Main Street Capital",
    # MidCap
    "0002006758": "MidCap",
    "0001278752": "MidCap",
    # Monroe Capital
    "0001512931": "Monroe Capital",
    "0001742313": "Monroe Capital",
    # Morgan Stanley
    "0001782524": "Morgan Stanley",
    # Neuberger Berman
    "0001487610": "Neuberger Berman",
    "0001818105": "Neuberger Berman",
    "0002041175": "Neuberger Berman",
    # New Mountain
    "0001496099": "New Mountain",
    "0001781870": "New Mountain",
    "0001925531": "New Mountain",
    "0001976719": "New Mountain",
    "0002037804": "New Mountain",
    "0001766037": "New Mountain",
    # Nuveen Churchill
    "0002071136": "Nuveen Churchill",
    "0001737924": "Nuveen Churchill",
    "0001911066": "Nuveen Churchill",
    # Oaktree
    "0001414932": "Oaktree",
    "0001872371": "Oaktree",
    "0001974793": "Oaktree",
    # PennantPark
    "0001383414": "PennantPark",
    "0001504619": "PennantPark",
    # PIMCO
    "0001905824": "PIMCO",
    # Prospect Capital
    "0001287032": "Prospect Capital",
    "0002027076": "Prospect Capital",
    "0001521945": "Prospect Capital",
    # SLR
    "0001825590": "SLR",
    "0002028686": "SLR",
    "0001832148": "SLR",
    "0001418076": "SLR",
    "0001932591": "SLR",
    # Stellus
    "0001551901": "Stellus",
    "0001901037": "Stellus",
    # Stone Point
    "0001825384": "Stone Point",
    "0002031283": "Stone Point",
    # T. Rowe Price / OHA
    "0001955010": "T. Rowe Price",
    "0001901164": "T. Rowe Price",
    # TCW
    "0001603480": "TCW",
    "0001715933": "TCW",
    # TPG
    "0001913724": "TPG",
    # TriplePoint
    "0001792509": "TriplePoint",
    "0001580345": "TriplePoint",
    # Trinity Capital
    "0001786108": "Trinity Capital",
    # Varagon
    "0001784700": "Varagon",
    # WhiteHorse
    "0001552198": "WhiteHorse",
    # WTI
    "0001850938": "WTI",
    "0001987731": "WTI",
    # Kayne Anderson
    "0001747172": "Kayne Anderson",
    "0001850787": "Kayne Anderson",
    # Cliffwater
    "0001735964": "Cliffwater",
    # PGIM
    "0001923622": "PGIM",
    # AG Twin Brook
    "0001666384": "AG Twin Brook",
    # Kennedy Lewis
    "0001911321": "Kennedy Lewis",
    # Investcorp
    "0001578348": "Investcorp",
    "0001948565": "Investcorp",
    # Partners Group
    "0001447247": "Partners Group",
    # Lord Abbett
    "0002008748": "Lord Abbett",
    # CION
    "0001534254": "CION",
    # Saratoga
    "0001377936": "Saratoga",
    # Capital Southwest
    "0000017313": "Capital Southwest",
    # AB (AllianceBernstein)
    "0001634452": "AllianceBernstein",
    "0001982701": "AllianceBernstein",
    # Antares
    "0001976336": "Antares",
    "0001993402": "Antares",
    # Palmer Square
    "0001608016": "Palmer Square",
    "0001794776": "Palmer Square",
    # Fortress
    "0002012139": "Fortress",
    # Manulife
    "0001988280": "Manulife",
    # OFS Capital
    "0001487918": "OFS Capital",
    # Horizon Technology
    "0001487428": "Horizon Technology",
    # First Trust
    "0002021979": "First Trust",
    # Audax
    "0001633858": "Audax",
    # BC Partners
    "0001726548": "BC Partners",
    # RiverNorth
    "0001501072": "RiverNorth",
    "0001678130": "RiverNorth",
    "0001644771": "RiverNorth",
    # StepStone
    "0002066799": "StepStone",
    # HarbourVest
    "0002020407": "HarbourVest",
    # Coller
    "0002033620": "Coller",
    "0001969180": "Coller",
    # Vista
    "0001919369": "Vista",
    # Chicago Atlantic
    "0001843162": "Chicago Atlantic",
    # Brightwood
    "0001895316": "Brightwood",
}
