"""Configuration constants for the SEC universe-building pipeline."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = DATA_DIR / "reference"
FX_RATES_FILE = REFERENCE_DIR / "fx_rates.csv"
# Current SEC registrant names per CIK (overlay written by
# scripts/refresh_entity_names.py; applied by pipeline.merge on rebuilds).
# EFTS display names are frozen at filing-date, so renamed funds go stale.
ENTITY_CURRENT_NAMES_FILE = REFERENCE_DIR / "entity_current_names.csv"
SEC_DATASETS_DIR = RAW_DIR / "sec_datasets"
FILINGS_DIR = RAW_DIR / "filings"
THIRD_PARTY_DIR = RAW_DIR / "third_party"
OUTPUT_DIR = DATA_DIR / "output"
OVERRIDES_DIR = DATA_DIR / "overrides"
OUTPUT_CACHE_DIR = OUTPUT_DIR / "cache"
SEC_DOWNLOAD_LOCK_DIR = OUTPUT_CACHE_DIR / "sec_download_locks"

# SEC reference data (company_tickers.json, etc.)
SEC_REFERENCE_DIR = RAW_DIR / "sec_reference"

# Listed price cache (per-ticker CSVs from yfinance)
LISTED_PRICES_CACHE_DIR = RAW_DIR / "listed_prices"

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

# Fund highlights wrapper overrides
FUND_HIGHLIGHTS_WRAPPER_DIR = OVERRIDES_DIR / "fund_highlights_wrappers"

# Ensure directories exist on import
for d in [SEC_DATASETS_DIR, FILINGS_DIR, THIRD_PARTY_DIR, OUTPUT_DIR,
          N2_HEADERS_CACHE_DIR, BDC_XBRL_CACHE_DIR,
          NPORT_TSV_CACHE_DIR, NPORT_XML_CACHE_DIR,
          BDC_HTML_CACHE_DIR, HTML_TEMPLATE_DIR,
          COMPANYFACTS_CACHE_DIR, REFERENCE_DIR,
          RAW_DIR / "filings" / "ncsr_html",
          RAW_DIR / "filings" / "sc_toi_html",
          OVERRIDES_DIR, OUTPUT_CACHE_DIR, SEC_DOWNLOAD_LOCK_DIR,
          SEC_REFERENCE_DIR, LISTED_PRICES_CACHE_DIR,
          FUND_HIGHLIGHTS_WRAPPER_DIR]:
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

# ---------------------------------------------------------------------------
# SEC bulk data sets (DERA)
# Quarterly ZIPs — format: {year}q{quarter}_{type}.zip
# Update DATASET_QUARTER to target a specific filing period.
# ---------------------------------------------------------------------------
DATASET_QUARTER = "2025q4"

# BDC data set — monthly ZIPs (e.g. 2026_06_bdc.zip)
# Path moved 2026: /files/datastandardsinnovation/data/... (was /files/structureddata/data/)
# Landing page: https://www.sec.gov/data-research/bdc-data-sets
BDC_DATASET_URL = (
    "https://www.sec.gov/files/datastandardsinnovation/data/"
    "business-development-company-bdc-data-sets/2026_06_bdc.zip"
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
BDC_FILINGS_INDEX_FILE = OUTPUT_DIR / "bdc_filings_index.csv"
BDC_HOLDINGS_FILE = OUTPUT_DIR / "bdc_holdings.csv"
BDC_HOLDINGS_PARQUET_FILE = OUTPUT_DIR / "bdc_holdings.parquet"
BDC_PARSE_PROGRESS_FILE = OUTPUT_DIR / "bdc_parse_progress.csv"
BDC_DEDUPE_AXIS_SPLITS_FILE = OUTPUT_DIR / "bdc_dedupe_axis_splits.csv"

# Audited opt-in SEC HTML downloads for agent workflows
SEC_DOWNLOAD_MANIFEST_FILE = OUTPUT_DIR / "sec_download_manifest.jsonl"

# N-CSR output files
NCSR_PARSE_PROGRESS_FILE = OUTPUT_DIR / "ncsr_parse_progress.csv"

# N-PORT output files
NPORT_HOLDINGS_FILE = OUTPUT_DIR / "nport_holdings.csv"
NPORT_HOLDINGS_PARQUET_FILE = OUTPUT_DIR / "nport_holdings.parquet"
NPORT_FILINGS_INDEX_FILE = OUTPUT_DIR / "nport_filings_index.csv"
NPORT_FUND_INFO_FILE = OUTPUT_DIR / "nport_fund_info.csv"
NPORT_PARSE_PROGRESS_FILE = OUTPUT_DIR / "nport_parse_progress.csv"

# Unified private markets holdings
UNIFIED_HOLDINGS_FILE = OUTPUT_DIR / "private_markets_holdings.csv"
UNIFIED_HOLDINGS_PARQUET_FILE = OUTPUT_DIR / "private_markets_holdings.parquet"
PROVENANCE_LEDGER_FILE = OUTPUT_DIR / "provenance_ledger.csv"
PROVENANCE_LEDGER_SUMMARY_FILE = OUTPUT_DIR / "provenance_ledger_summary.csv"
UNIVERSE_ORPHAN_HOLDINGS_FILE = OUTPUT_DIR / "universe_orphan_holdings.csv"

# Manual row-level corrections overlay (checked into data/overrides/)
ROW_CORRECTIONS_FILE = OVERRIDES_DIR / "row_corrections.csv"
BDC_XBRL_ORACLE_EXCEPTIONS_FILE = OVERRIDES_DIR / "bdc_xbrl_oracle_exceptions.json"

# Promoted agent-fix stores (gap 1): gate-PASS fixes with production consumers.
# agent_anchor -> shadow conservation engine (verified_override anchor kind);
# agent_b2_corrections -> raw BDC staging (comparative_period_filter);
# agent_investigate_rules -> tail of build_unified_holdings (pipeline.agent_promoted).
AGENT_ANCHOR_OVERRIDES_DIR = OVERRIDES_DIR / "agent_anchor"
AGENT_B2_CORRECTIONS_DIR = OVERRIDES_DIR / "agent_b2_corrections"
AGENT_INVESTIGATE_RULES_DIR = OVERRIDES_DIR / "agent_investigate_rules"
CONSERVATION_SCOPE_DIR = OVERRIDES_DIR / "conservation_scope"

# FV-conservation reconcile band, in percent of the anchor: |value_sum - anchor|
# <= band% counts as reconciled. Shared by the shadow conservation engine
# (flagging) and the B2 investigation loop stop rule so a loop-level "done"
# cannot land outside the engine's reconcile band (pre-2026-07 mismatch: the
# loop stopped at 1% while the engine flagged at 0.5%). Also consumed by the
# quarter acceptance contract (pipeline.quarter_acceptance).
FV_CONSERVATION_BAND_PCT = 0.5

# Quarter acceptance contract: thresholds are DATA (reviewed, versioned), the
# computed verdict is an output artifact. See pipeline/quarter_acceptance.py.
QUARTER_ACCEPTANCE_THRESHOLDS_FILE = REFERENCE_DIR / "quarter_acceptance_thresholds.json"
QUARTER_ACCEPTANCE_FILE = OUTPUT_DIR / "quarter_acceptance.json"
QUARTER_ACCEPTANCE_FUNDS_FILE = OUTPUT_DIR / "quarter_acceptance_funds.csv"

# Position match overrides (per-CIK JSON files with reject/force_pair directives)
POSITION_MATCH_OVERRIDES_DIR = OVERRIDES_DIR / "position_match_overrides"

# Unlisted (non-traded) BDC reference for v1 frontend filtering
UNLISTED_BDC_REFERENCE_FILE = (
    OVERRIDES_DIR / "bdc_xbrl_wrappers" / "unlisted_bdc_xbrl_reference.json"
)

# Wrapper cohort manifest -- the frontend sample scope. v2 (2026-06-15) is the
# 70 gate-verified v3-wrapper BDCs (68 clean + 2 no-anchor of the 77 v3 wrappers;
# 7 held back for FV-conservation over-inclusion -- see manifest basis_note).
# The prior v1_39_wrapper_manifest.json is retained for audit.
WRAPPER_COHORT_MANIFEST_FILE = (
    OVERRIDES_DIR / "wrapper_cohorts" / "v2_70_gate_verified_wrapper_manifest.json"
)

# Entity resolution overrides and outputs
ENTITY_OVERRIDES_FILE = OVERRIDES_DIR / "entity_overrides.json"
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
SOURCE_RECONCILIATION_DETAIL_FILE = OUTPUT_DIR / "source_reconciliation_detail.csv"
SOURCE_RECONCILIATION_METRICS_FILE = OUTPUT_DIR / "source_reconciliation_metrics.csv"
SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE = (
    OUTPUT_DIR / "source_reconciliation_calibration_review.csv"
)
SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE = (
    OUTPUT_DIR / "source_reconciliation_residual_classification.csv"
)
SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE = (
    OUTPUT_DIR / "source_reconciliation_residual_classification.md"
)
SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE = (
    OUTPUT_DIR / "source_reconciliation_source_only_detail.csv"
)
SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE = (
    OUTPUT_DIR / "source_reconciliation_source_only_clusters.csv"
)
SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE = (
    OUTPUT_DIR / "source_reconciliation_source_only_classification.md"
)
BDC_SOURCE_FACTS_CACHE_DIR = OUTPUT_CACHE_DIR / "bdc_source_facts"
BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE = BDC_SOURCE_FACTS_CACHE_DIR / "manifest.csv"
SOURCE_RECONCILIATION_CACHE_DIR = OUTPUT_CACHE_DIR / "source_reconciliation"
SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR = (
    SOURCE_RECONCILIATION_CACHE_DIR / "detail_by_cik"
)
SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR = (
    SOURCE_RECONCILIATION_CACHE_DIR / "metrics_by_cik"
)
SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE = (
    SOURCE_RECONCILIATION_CACHE_DIR / "manifest.csv"
)
SOURCE_RECONCILIATION_CACHE_STATUS_FILE = (
    SOURCE_RECONCILIATION_CACHE_DIR / "cache_status.csv"
)
POSITION_PURITY_DIAGNOSTICS_FILE = OUTPUT_DIR / "position_purity_diagnostics.csv"
POSITION_PURITY_METRICS_FILE = OUTPUT_DIR / "position_purity_metrics.csv"
FUND_STRATEGY_REFERENCE_FILE = OUTPUT_DIR / "fund_strategy_reference.csv"
FUND_STRATEGY_HOLDINGS_MIX_FILE = OUTPUT_DIR / "fund_strategy_holdings_mix.csv"
FUND_STRATEGY_VALIDATION_FILE = OUTPUT_DIR / "fund_strategy_validation.csv"
FUND_STRATEGY_REVIEW_QUEUE_FILE = OUTPUT_DIR / "fund_strategy_review_queue.csv"
FUND_STRATEGY_CORRECTION_CANDIDATES_FILE = (
    OUTPUT_DIR / "fund_strategy_correction_candidates.csv"
)
# Frozen per-quarter-pass copy (see run_quarter_pass pin stage). When present, unified
# rebuilds consume THIS instead of the live file above, breaking the validate->rebuild
# feedback loop that oscillates marginal fund-strategy classifications.
FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE = (
    OUTPUT_DIR / "fund_strategy_correction_candidates.pinned.csv"
)
FUND_STRATEGY_OVERRIDES_FILE = OVERRIDES_DIR / "fund_strategy_overrides.json"
COLUMN_QUALITY_METRICS_FILE = OUTPUT_DIR / "column_quality_metrics.csv"
ROW_VALIDATION_ISSUES_FILE = OUTPUT_DIR / "row_validation_issues.csv"
VALIDATE_ALL_RESIDUAL_SUMMARY_FILE = OUTPUT_DIR / "validate_all_residual_summary.csv"
DATA_QUALITY_METRICS_FILE = OUTPUT_DIR / "data_quality_metrics.csv"

# Position matching and index returns
POSITION_MATCHES_FILE = OUTPUT_DIR / "position_matches.csv"
POSITION_RETURNS_FILE = OUTPUT_DIR / "position_returns.csv"
INDEX_RETURNS_FILE = OUTPUT_DIR / "index_returns.csv"
POSITION_ID_EDGES_FILE = OUTPUT_DIR / "position_id_edges.csv"
MATCH_QUALITY_METRICS_FILE = OUTPUT_DIR / "match_quality_metrics.csv"
MATCH_GOLD_DIR = OUTPUT_DIR / "match_quality" / "gold"
# Stable identifier registry (opt-in; see docs/position_id_stable_identifier_design.md).
# Stateful artifact: lives under OVERRIDES_DIR (governed, NOT a rebuild target),
# so `rebuild_outputs.py --clean` and output snapshots never wipe it.
POSITION_ID_REGISTRY_DIR = OVERRIDES_DIR / "position_id_registry"
POSITION_ID_REGISTRY_FILE = POSITION_ID_REGISTRY_DIR / "registry.csv"
POSITION_ID_RETIREMENTS_FILE = POSITION_ID_REGISTRY_DIR / "retirements.csv"
POSITION_MATCH_COVERAGE_FILE = OUTPUT_DIR / "position_match_coverage.csv"
POSITION_MATCH_UNMATCHED_SUMMARY_FILE = OUTPUT_DIR / "position_match_unmatched_summary.csv"
POSITION_MATCH_RESIDUALS_FILE = OUTPUT_DIR / "position_match_residuals.csv"

# Oracle check outputs
ORACLE_OUTPUT_DIR = OUTPUT_DIR / "oracle"
ORACLE_CHECK_RESULTS_FILE = ORACLE_OUTPUT_DIR / "check_results.csv"
ORACLE_CHECK_FAILURES_FILE = ORACLE_OUTPUT_DIR / "check_failures.csv"
ORACLE_SUMMARY_MD_FILE = ORACLE_OUTPUT_DIR / "oracle_summary.md"

# V1 report-only validation rules engine
VALIDATION_RULES_AGGREGATE_FILE = OUTPUT_DIR / "validation_rules_aggregate.csv"
VALIDATION_RULES_DETAIL_FILE = OUTPUT_DIR / "validation_rules_detail.csv"
VALIDATION_RULES_HISTORY_FILE = OUTPUT_DIR / "validation_rules_history.csv"
VALIDATION_RULES_TREND_FILE = OUTPUT_DIR / "validation_rules_trend.csv"

# Derivatives (analytics-only; never index constituents)
BDC_DERIVATIVES_FILE = OUTPUT_DIR / "bdc_derivatives.csv"
DERIVATIVE_ROLE_REVIEW_FILE = OUTPUT_DIR / "derivative_role_review.csv"

# Per-CIK interest_rate reporting-convention classification (cash_leg vs all_in;
# measurement artifact consumed by the future all-in normalization transform)
RATE_CONVENTION_FILE = OUTPUT_DIR / "rate_convention.csv"
# Convention Adjudicator promoted verdicts (per-CIK leaf JSONs; merged into the
# classifier output -- see docs/adjudication_architecture/convention_adjudicator_spec.md)
RATE_CONVENTION_OVERRIDES_DIR = OVERRIDES_DIR / "rate_convention"
# Linkbase-derived analysis artifacts (XBRL concept fingerprints, dataset
# cal/pre tables, FV dimension buckets). Built by scripts/scan_rate_tag_fingerprint.py
# and scripts/analyze_bdc_dataset_linkbase.py; S0 signal consumed by rate_convention.
LINKBASE_ANALYSIS_DIR = OUTPUT_DIR / "linkbase_analysis"
S0_CONVENTION_SIGNAL_FILE = LINKBASE_ANALYSIS_DIR / "s0_convention_signal.csv"

# Fund-level income and fee uplift
BDC_FUND_INCOME_FILE = OUTPUT_DIR / "bdc_fund_income.csv"
BDC_FUND_HIGHLIGHTS_FILE = OUTPUT_DIR / "bdc_fund_highlights.csv"
BDC_FUND_HIGHLIGHTS_ORACLE_FILE = OUTPUT_DIR / "bdc_fund_highlights_oracle.csv"
FUND_HIGHLIGHTS_QUALITY_GATE_FILE = OUTPUT_DIR / "fund_highlights_quality_gate.csv"
FUND_HIGHLIGHTS_QUALITY_GATE_MD_FILE = OUTPUT_DIR / "fund_highlights_quality_gate.md"
FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE = OUTPUT_DIR / "fund_highlights_residual_profile.csv"
FUND_HIGHLIGHTS_RESIDUAL_PROFILE_MD_FILE = OUTPUT_DIR / "fund_highlights_residual_profile.md"
FEE_UPLIFT_FILE = OUTPUT_DIR / "fee_uplift.csv"
FUND_FINANCIALS_FILE = OUTPUT_DIR / "fund_financials.csv"
FUND_IDENTITY_FILE = OUTPUT_DIR / "fund_identity.csv"
BDC_SECTOR_BREAKDOWN_FILE = OUTPUT_DIR / "bdc_sector_breakdown.csv"
BDC_SECTOR_RECONCILIATION_FILE = OUTPUT_DIR / "bdc_sector_reconciliation.csv"
BDC_SECTOR_BREAKDOWN_RECONCILED_FILE = OUTPUT_DIR / "bdc_sector_breakdown_reconciled.csv"
BDC_LIEN_BREAKDOWN_FILE = OUTPUT_DIR / "bdc_lien_breakdown.csv"
BDC_INSTRUMENT_TYPE_BREAKDOWN_FILE = OUTPUT_DIR / "bdc_instrument_type_breakdown.csv"
# Per-position iXBRL descriptor field-status (maturity/lien/sector/ref + status)
BDC_IXBRL_FIELD_STATUS_FILE = OUTPUT_DIR / "bdc_ixbrl_field_status.csv"
FUND_FINANCIALS_VALIDATION_CURRENT_FILE = OUTPUT_DIR / "fund_financials_validation_current.csv"
FUND_FINANCIALS_QUALITY_METRICS_FILE = OUTPUT_DIR / "fund_financials_quality_metrics.csv"
FUND_FINANCIALS_CROSS_LEVEL_FILE = OUTPUT_DIR / "fund_financials_cross_level.csv"

# BDC listed prices and premium/discount
SEC_COMPANY_TICKERS_FILE = SEC_REFERENCE_DIR / "company_tickers.json"
BDC_LISTED_PRICES_FILE = OUTPUT_DIR / "bdc_listed_prices.csv"
BDC_PREMIUM_DISCOUNT_FILE = OUTPUT_DIR / "bdc_premium_discount.csv"

# Position-level PIK status
BDC_POSITION_PIK_EVIDENCE_FILE = OUTPUT_DIR / "bdc_position_pik_evidence.csv"
POSITION_PIK_STATUS_FILE = OUTPUT_DIR / "position_pik_status.csv"
PIK_TRANSITIONS_FILE = OUTPUT_DIR / "pik_transitions.csv"
PIK_SCHEDULE_PROXY_SUMMARY_FILE = OUTPUT_DIR / "pik_schedule_proxy_summary.csv"
PIK_SCHEDULE_PROXY_TRANSITIONS_FILE = OUTPUT_DIR / "pik_schedule_proxy_transitions.csv"

# GICS industry mapping
GICS_REFERENCE_FILE = REFERENCE_DIR / "gics_sub_industries.json"
GICS_HIERARCHY_FILE = REFERENCE_DIR / "gics_hierarchy.json"
GICS_LABEL_CACHE_FILE = OUTPUT_DIR / "gics_label_cache.csv"
COMPANY_GICS_CACHE_FILE = OUTPUT_DIR / "company_gics_cache.csv"

# GICS + aggregate header CC skill
AGGREGATE_HEADER_FLAGS_FILE = OUTPUT_DIR / "aggregate_header_flags.csv"
GICS_SKILL_BATCHES_DIR = OUTPUT_DIR / "gics_skill_batches"
GICS_SKILL_CLAIMS_FILE = OUTPUT_DIR / "gics_skill_claims.json"

# Unclassified review CC skill
UNCLASSIFIED_SKILL_BATCHES_DIR = OUTPUT_DIR / "unclassified_skill_batches"
UNCLASSIFIED_SKILL_CLAIMS_FILE = OUTPUT_DIR / "unclassified_skill_claims.json"
UNCLASSIFIED_NEEDS_REVIEW_FILE = OUTPUT_DIR / "unclassified_needs_review.csv"
UNCLASSIFIED_REVIEW_CACHE_FILE = OUTPUT_DIR / "unclassified_review_cache.csv"

# Lien position classification
LIEN_CACHE_FILE = OUTPUT_DIR / "lien_cache.csv"
LIEN_SKILL_BATCHES_DIR = OUTPUT_DIR / "lien_skill_batches"
LIEN_SKILL_CLAIMS_FILE = OUTPUT_DIR / "lien_skill_claims.json"

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

# SC TO-I/A tender offer repurchase filings
SC_TOI_HTML_CACHE_DIR = RAW_DIR / "filings" / "sc_toi_html"
SC_TOI_FILINGS_INDEX_FILE = OUTPUT_DIR / "sc_toi_filings_index.csv"
SC_TOI_RESULTS_FILE = OUTPUT_DIR / "sc_toi_repurchase_results.csv"
SC_TOI_PARSE_PROGRESS_FILE = OUTPUT_DIR / "sc_toi_parse_progress.csv"

# HTML holdings extraction outputs
HTML_EXTRACTION_FILE = OUTPUT_DIR / "html_extraction_holdings.csv"
HTML_EXTRACTION_EXPERIMENT_FILE = OUTPUT_DIR / "html_extraction_experiment.csv"

# HTML template validation (aggregate FV + carry rate checks)
HTML_TEMPLATE_VALIDATION_FILE = OUTPUT_DIR / "html_template_validation.csv"

# Provenance diagnostic artifacts (opt-in, not part of standard rebuild)
PROVENANCE_DIR = OUTPUT_DIR / "provenance"
HOLDINGS_WRAPPER_PROVENANCE_FILE = PROVENANCE_DIR / "holdings_wrapper_provenance.csv"
XBRL_CONCEPT_MAP_FILE = PROVENANCE_DIR / "xbrl_concept_map.json"
POSITION_PROVENANCE_INDEX_FILE = PROVENANCE_DIR / "position_provenance_index.csv"

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

# CIKs to exclude from N-PORT extraction (consumer/marketplace lending funds
# that report millions of individual loan rows with opaque numeric IDs).
# Excluded at extraction time so rows never enter nport_holdings.csv.
NPORT_EXCLUDE_CIKS: set[str] = {
    "1658645",   # Stone Ridge Trust V (~20M consumer loan rows)
    "1644771",   # RiverNorth Marketplace Lending (opaque numeric IDs, <$1B FV)
    "1678130",   # RiverNorth/DoubleLine Strategic Opp (opaque numeric IDs, <$1B FV)
    "2041175",   # NB Direct Private Lending (opaque numeric IDs, <$0.5B FV)
    "1500234",   # Ironwood Multi-Strategy Fund (feeder: single $3B+ position in master fund)
    "1547580",   # Victory Portfolios II (broad registered fund denominator contaminant)
}

# Manual scale overrides for fund_financials when automatic detection fails.
# Maps CIK (zero-padded) to multiplier applied to total_assets/total_liabilities/net_assets.
# Used for CIKs with too few rows for MEDIAN-based scale detection.
FUND_FINANCIALS_SCALE_OVERRIDES: dict[str, int] = {
    "0002012139": 1000,  # Owl Rock Core Income Corp: 2025-06-30 reported in raw dollars
}

# Optional audited exceptions for BDC aggregate/header row filtering.
# Rows are matched by CIK plus substring match_text, with optional report_date
# and accession_number narrowing.  Intended only for rows that cannot be
# classified safely by global rules.
BDC_AGGREGATE_ROW_OVERRIDES_FILE = OVERRIDES_DIR / "bdc_aggregate_row_overrides.json"
LEGACY_BDC_AGGREGATE_ROW_OVERRIDES_FILE = OUTPUT_DIR / "bdc_aggregate_row_overrides.json"

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
