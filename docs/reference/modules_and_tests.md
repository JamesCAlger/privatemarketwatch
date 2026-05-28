# Modules & Tests

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

## Modules

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
| `pipeline/bdc_position_pik.py` | Position-level BDC PIK income/accrual/capitalization evidence extraction from cached XBRL (no network) |
| `pipeline/pik_status.py` | Strict current PIK status plus researcher-comparable PIK schedule-rate proxy summaries and terms-started transitions |
| `pipeline/bdc_sector_breakdown.py` | Per-industry aggregate data (FV, cost, % of net assets) from XBRL `EquitySecuritiesByIndustryAxis`. See [`docs/bdc_sector_breakdown.md`](../bdc_sector_breakdown.md) |
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

## Tests

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
