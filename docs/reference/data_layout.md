# Data Layout

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

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
    bdc_position_pik_evidence.csv      # Raw BDC position-level PIK income/accrual/capitalization evidence
    position_pik_status.csv            # Strict current PIK status plus separate PIK terms flags per holding-quarter
    pik_transitions.csv                # Strict current-evidence not_paying/new evidence -> paying transitions
    pik_schedule_proxy_summary.csv     # S&P-style PIK schedule-rate proxy summary (1,834 rows in latest rebuild)
    pik_schedule_proxy_transitions.csv # PIK terms-started proxy transitions (3,706 rows in latest rebuild)
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
