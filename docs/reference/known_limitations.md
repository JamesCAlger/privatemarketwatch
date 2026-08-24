# Known Limitations & Technical Details

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

## Known Limitations

- **BDC XBRL coverage starts ~2022-2023.** The SEC phased in investment-level XBRL tagging for BDCs. Pre-2022 filings are plain HTML with no structured data. Some 2022-2023 filings have only aggregate XBRL (category-level totals, not individual positions). HTML template extraction covers pre-XBRL filings back to 2013.
- **HTML template coverage is per-CIK.** Each BDC requires a v3.0 template mapping its specific table layout. ~3,662 pre-XBRL filings across ~190 CIKs need templates. Templates are created via `--auto-detect` + manual validation.
- **Industry/type/affiliation are mostly empty.** Most BDCs embed this metadata in the `investment_identifier` string (e.g., "Senior Secured Loans | First Lien | Acme Corp | Technology") rather than using separate XBRL dimensions. Parsing these out requires string splitting, which is filer-specific.
- **N-PORT consumer/marketplace lending positions.** Four N-PORT CIKs (0001658645 Stone Ridge Trust V, 0001678130 RiverNorth/DoubleLine, 0001644771 RiverNorth series, 0002041175 NB Asset-Based Credit) report individual consumer loans with opaque numeric IDs. These are excluded from unified holdings at the staging level via `NPORT_EXCLUDE_CIKS` in `config.py`. The data is preserved in `nport_holdings.csv` but filtered out during `--unified`. The frontend export additionally filters via `CONSUMER_LENDING_EXCLUDE_CIKS` in `pipeline/export/helpers.py`.
- **2 BDCs with holdings but missing from unified.** Two CIKs have `bdc_holdings.csv` rows but do not appear in `private_markets_holdings.csv`: (1) Terra Income Fund 6 (0001577134, 10 rows) -- all rows are prior-period comparatives with no current-period data; (2) Lord Abbett Private Credit Fund S (0002041841, 157 rows) -- aggregate-only XBRL where position-level rows have NULL across all financial fields. Both exclusions are correct. Lord Abbett is a candidate for HTML template extraction (~55 positions, $319M total). The original 20 missing CIKs (Investigation #5) were reduced to 2 by aggregate filter improvements.
- **Sub-materiality row-level extraction defects are tracked, not remediated.** The TRACK_ONLY-demoted validation rules (C104, C404, X03, and since 2026-07-21 X08, X10, PP01) catch REAL errors, not just noise: B1 adjudication (ens2 + recal1, 2026-07) confirmed real extraction defects among their flags — sign flips, note-markers-extracted-as-values, dash-vs-zero cells, stale maturity dates — and the row-level unique-catch analysis (`data/output/data_investigation_results.md` 2026-07-21 part 2) showed 16 such culprit rows are flagged by NO other rule. They were demoted anyway because every known instance sits below the materiality threshold: stored fair-value impact $1K–$2.2M per row, far under the 0.5% fv_conservation band against fund-level totals, with bounded product impact. The trade is deliberate — B1 adjudication budget goes to material errors; sub-materiality defects keep firing into `row_validation_issues.csv` (severity INFO / action TRACK_ONLY) as evidence for investigators but are not queued for review. Consequence: holdings rows may carry known-class small-value extraction errors that nothing in the system will auto-remediate.
- **Multi-dimension-path BDC duplicates (resolved).** BDCs that tag the same position under multiple XBRL dimension hierarchies are handled by the `no_dim_dupes` CTE in `unified_holdings.py` (case/punctuation-normalized partition key excluding cost) and the `_canonical_casing` CTE in `staging_bdc.py` (majority casing vote per CIK). These BDCs show `pct_of_net_assets` sums of 200-400% (corrected using consolidated `net_assets` from fund_financials). Residual: 48 rows with non-deterministic cost proxy from upstream dedup tie-breaking (0.007% of total).

## Resumability

All three phases of holdings extraction are resumable:
- **Filing index:** Cached to CSV, skipped if < 24h old
- **XBRL downloads:** Cached per-file in `data/raw/filings/bdc_xbrl/`, skipped if file exists and > 1KB
- **Parsing:** Progress tracked in `bdc_parse_progress.csv`, only unparsed filings are processed

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

See **[`docs/oversubscription_data.md`](../oversubscription_data.md)** for full analysis of data availability for fund-level oversubscription rates. Summary: N-PORT gives a binary cap signal for interval funds (already in `fund_financials.csv` as `redemption_pressure`); exact demand-side data requires parsing SC TO-I/A filings (non-traded BDCs, tender offer funds) and N-CSR/N-CSRS narratives (interval funds).
