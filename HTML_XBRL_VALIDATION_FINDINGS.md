# HTML-vs-XBRL Cross-Validation Findings

**Date:** 2026-04-18
**Module:** `pipeline/validate_html_extraction.py`
**CLI:** `python -m scripts.validate_html_xbrl --run`
**Output:** `data/output/html_xbrl_filing_comparison.csv`

## Overview

Position-level cross-validation of HTML template extraction against XBRL structured data for 47 CIKs with templates. For each XBRL-era filing, HTML is extracted using the per-CIK template and matched 1:1 against XBRL positions using fuzzy name matching + FV proximity.

**668 filings compared | 200,541 XBRL positions | 121,327 matched | 60.5% overall recall**

## Methodology

- **Name matching:** `rapidfuzz.fuzz.token_sort_ratio` on normalized names (HTML `investment_identifier` vs XBRL company name extracted from pipe/dash-separated identifier). Score >= 50 required.
- **FV proximity bonus:** +20 if FV within 5%, +10 if within 20%.
- **1:1 assignment:** Greedy sort by composite score, each position matched at most once.
- **Field tolerances:** FV 1%, rate 50bps, maturity 1 month, principal 5%.
- **Rate conversion:** XBRL decimal rates (0.105) multiplied by 100 for comparison with HTML percentage rates (10.5%).
- **Dollar unit detection:** Aggregate FV ratio (sum HTML FV / sum XBRL FV); 0.5-2.0 = OK.

## Aggregate Metrics

| Metric | Value |
|--------|-------|
| Overall recall | 60.5% |
| Rate accuracy (where available) | 72.4% |
| Maturity accuracy (where available) | 50.9% |
| Dollar unit correct | 335/404 filings (82.9%) |
| Drift detected | 92/668 filings (13.8%) |
| HTML/XBRL ratio | 1.31x (HTML includes comparative periods) |

## Quality Tiers

| Tier | Criteria | CIKs | XBRL Positions | Position Share | Tier Recall |
|------|----------|------|----------------|----------------|-------------|
| 1 | >= 85% recall | 12 | 90,031 | 44.9% | 93.6% |
| 2 | 50-85% recall | 10 | 37,481 | 18.7% | ~65% |
| 3 | 1-50% recall | 18 | 62,351 | 31.1% | ~20% |
| 4 | 0% recall | 7 | 10,678 | 5.3% | 0% |

## Per-CIK Results

### Tier 1: Production-Ready (>= 85% recall)

| CIK | Entity | Filings | XBRL | Matched | Recall | FV Acc | Rate Acc | DU Issues | Drift | Root Cause Notes |
|-----|--------|---------|------|---------|--------|--------|----------|-----------|-------|------------------|
| 1803498 | Blackstone Private Credit Fund | 15 | 20,467 | 20,395 | 99.6% | 87.0% | 96.9% | 1 | 2 | Best overall. 1 filing with format shift (maturity/par column swap). |
| 1396440 | Main Street Capital | 15 | 8,854 | 8,768 | 99.0% | 72.2% | 97.4% | 1 | 0 | Excellent. Minor DU issue on 1 filing. |
| 1501729 | FS Specialty Lending | 14 | 1,144 | 1,117 | 97.6% | 53.0% | 82.7% | 4 | 3 | Good recall but FV accuracy lower (53%) -- likely DU issues on 4 filings distorting FV comparison. |
| 1535778 | MSC Income Fund | 15 | 6,025 | 5,833 | 96.8% | 62.9% | 94.8% | 2 | 0 | Solid. |
| 1287750 | Ares Capital | 18 | 17,480 | 16,904 | 96.7% | 68.9% | 90.4% | 4 | 4 | Largest BDC. 4 drift filings pick wrong table (2-col instead of 13-col). |
| 1321741 | Gladstone Investment | 14 | 898 | 847 | 94.3% | 76.9% | N/A | 0 | 0 | No rate columns in template. Clean extraction. |
| 1487918 | OFS Capital | 15 | 1,664 | 1,568 | 94.2% | 61.5% | 76.7% | 1 | 0 | Good. |
| 1490927 | Franklin BSP Lending | 4 | 1,997 | 1,774 | 88.8% | 56.9% | N/A | 0 | 0 | Only 4 filings in XBRL era. |
| 1414932 | Oaktree Specialty Lending | 14 | 5,390 | 4,737 | 87.9% | 55.0% | 83.8% | 4 | 12 | 12/14 filings have drift (7-col template vs 13-col actual). Template needs variant for expanded format. DU issues on 4. |
| 1287032 | Prospect Capital | 15 | 3,500 | 3,003 | 85.8% | 48.4% | 18.2% | 2 | 1 | Low rate accuracy (18%) due to embedded rates in text field, not parsed. |
| 1476765 | Golub Capital BDC | 15 | 22,177 | 18,918 | 85.3% | 54.7% | 67.7% | 1 | 0 | Largest position count. FV accuracy 55% -- some positions matched but with value discrepancies. |
| 1552198 | WhiteHorse Finance | 16 | 435 | 370 | 85.1% | 4.8% | 9.4% | 14 | 1 | **Severe DU issues (14/16 filings)**. Recall is high but values are wrong -- template dollar unit doesn't match XBRL. FV/rate accuracy near-zero. |

### Tier 2: Usable with Caveats (50-85% recall)

| CIK | Entity | Filings | XBRL | Matched | Recall | FV Acc | Rate Acc | DU Issues | Drift | Root Cause Notes |
|-----|--------|---------|------|---------|--------|--------|----------|-----------|-------|------------------|
| 1512931 | Monroe Capital | 15 | 5,310 | 4,207 | 79.2% | 44.1% | 77.8% | 3 | 6 | 6 drift filings. Template needs variant for wider format. |
| 1521945 | Prospect Floating Rate | 12 | 707 | 556 | 78.6% | 69.2% | 21.6% | 3 | 0 | Low rate accuracy -- embedded rates. |
| 1377936 | Saratoga Investment | 14 | 2,079 | 1,597 | 76.8% | 22.8% | 61.1% | 12 | 0 | **DU issues on 12/14 filings.** Low FV accuracy is almost entirely DU-driven. |
| 1422183 | FS KKR Capital | 14 | 9,146 | 6,557 | 71.7% | 48.9% | 50.5% | 2 | 0 | Large BDC. 28% unmatched positions suggest HTML extracts fewer than XBRL reports. |
| 1544206 | Carlyle Secured Lending | 15 | 3,649 | 2,482 | 68.0% | 47.9% | 67.0% | 1 | 1 | 1 drift filing. Moderate performance. |
| 1572694 | Goldman Sachs BDC | 15 | 6,056 | 3,634 | 60.0% | 27.7% | 40.8% | 3 | 0 | Low FV accuracy. Name matching difficulties between HTML/XBRL identifier formats. |
| 1496099 | New Mountain Finance | 15 | 7,259 | 3,952 | 54.4% | 35.9% | 49.5% | 1 | 0 | ~46% of XBRL positions unmatched. Possible HTML missing continuation tables. |
| 1490349 | PhenixFIN | 14 | 303 | 162 | 53.5% | 11.2% | 0.0% | 11 | 1 | Small fund. **DU issues on 11/14.** |
| 1580345 | TriplePoint Venture Growth | 14 | 1,400 | 722 | 51.6% | 16.1% | N/A | 11 | 0 | **DU issues on 11/14.** No rate columns. |
| 81955 | Rand Capital | 13 | 1,572 | 806 | 51.3% | 54.8% | N/A | 0 | 0 | No DU or drift issues. 49% unmatched -- likely name format differences or HTML missing positions. |

### Tier 3: Needs Template Work (1-50% recall)

| CIK | Entity | Filings | XBRL | Matched | Recall | FV Acc | DU Issues | Drift | Primary Failure Mode |
|-----|--------|---------|------|---------|--------|--------|-----------|-------|---------------------|
| 1278752 | MidCap Financial | 13 | 9,245 | 4,305 | 46.6% | 32.8% | 5 | 0 | Large fund, DU issues + name matching |
| 1571329 | Logan Ridge Finance | 13 | 1,446 | 615 | 42.5% | 49.4% | 6 | 1 | DU issues on 6/13 |
| 1326003 | BlackRock Capital Investment | 7 | 1,155 | 460 | 39.8% | 24.4% | 4 | 0 | DU issues + grid spacing variants |
| 1578348 | Investcorp Credit Mgmt BDC | 12 | 846 | 316 | 37.4% | 57.9% | 1 | 0 | Small fund, partial extraction |
| 1370755 | BlackRock TCP Capital | 16 | 4,439 | 1,615 | 36.4% | 52.8% | 12 | 1 | **DU issues on 12/16 filings** |
| 1418076 | SLR Investment | 15 | 1,725 | 539 | 31.2% | 39.7% | 5 | 0 | DU issues + partial extraction |
| 17313 | Capital Southwest | 17 | 5,247 | 1,449 | 27.6% | 0.0% | 17 | 0 | **DU issues on ALL 17 filings.** 0% FV accuracy. Template dollar_unit completely wrong. |
| 1280784 | Hercules Capital | 14 | 4,721 | 1,090 | 23.1% | 53.7% | 7 | 0 | DU issues + venture-debt format |
| 1372807 | BCP Investment (Blue Owl) | 14 | 2,508 | 380 | 15.2% | 34.0% | 11 | 13 | **DU issues (11) + drift (13/14).** Template completely misaligned with XBRL-era HTML. |
| 1603480 | TCW Direct Lending | 14 | 606 | 88 | 14.5% | 50.9% | 3 | 1 | Table selection issue (5-col vs 9-col expected) |
| 1513363 | FIDUS Investment | 14 | 3,026 | 321 | 10.6% | 42.0% | 2 | 0 | Multi-row position format. company_row_no_financials mode confuses name extraction. |
| 1259429 | Oxford Square Capital | 15 | 231 | 22 | 9.5% | 5.5% | 13 | 0 | DU issues on 13/15. Small fund. |
| 1508655 | Sixth Street Specialty Lending | 14 | 2,714 | 230 | 8.5% | 20.8% | 4 | 0 | Large fund, low match rate. Name/format differences. |
| 1588272 | NexPoint Capital | 13 | 384 | 28 | 7.3% | 65.4% | 3 | 0 | Small fund, DU issues |
| 1504619 | PennantPark Floating Rate | 15 | 7,081 | 344 | 4.9% | 5.1% | 15 | 0 | **DU issues on ALL 15 filings.** Template picks wrong table. |
| 1383414 | PennantPark Investment | 18 | 7,186 | 320 | 4.5% | 3.3% | 18 | 2 | **DU issues on ALL 18 filings.** Template selects 2-col governance table instead of 8-col SOI. |
| 1633858 | Audax Credit BDC | 12 | 5,621 | 243 | 4.3% | 0.0% | 0 | 12 | **Drift on ALL 12 filings.** Template expects 4 cols, finds 11-14. Format changed entirely. |
| 1587987 | NewtekOne | 15 | 4,170 | 53 | 1.3% | 7.5% | 8 | 4 | DU issues + drift. Template misaligned. |

### Tier 4: Zero Extraction (0% recall)

| CIK | Entity | Filings | XBRL Positions | Root Cause |
|-----|--------|---------|----------------|------------|
| 845385 | Princeton Capital | 15 | 105 | Very small fund. Template extracts 0 rows from every filing. Likely table selection failure. |
| 1379785 | Barings BDC | 15 | 8,918 | **Large fund.** Template extracts 0 rows. Critical table selection failure -- HTML format different from template era. |
| 1487428 | Horizon Technology Finance | 15 | 454 | Template all-grid_index layout causes drift score = 0 for every table; engine picks wrong summary table. Known issue (see MEMORY.md). |
| 1495584 | Firsthand Technology | 18 | 94 | Very small VC BDC. Template picks wrong table (signatures page). 1 drift filing. |
| 1534254 | CION Investment | 15 | 0 | 0 XBRL positions -- CION uses aggregate-only XBRL, no position-level data. Not a template issue. |
| 1551901 | Stellus Capital | 15 | 1,107 | **Drift on ALL 15 filings.** Template uses ZWSP-contaminated headers. Template expects 6 cols, HTML has 7-8. Complete format mismatch. |
| 1577134 | Terra Income Fund 6 | 13 | 0 | 0 XBRL positions -- aggregate-only XBRL. Drift on all filings. Not a template issue. |

## Root Cause Analysis

### 1. Dollar Unit Mismatch (15 CIKs, 69 filings)

The most widespread issue. Template specifies `dollar_unit: 1000` but XBRL stores values in units (or vice versa). This causes FV values to differ by 1000x, breaking both matching and accuracy metrics.

**Worst offenders (DU issues on every filing):**
- Capital Southwest (17313): 17/17
- PennantPark Investment (1383414): 18/18
- PennantPark Floating Rate (1504619): 15/15

**Impact:** Dollar unit auto-correction in `compare_filing()` would immediately improve recall for these CIKs. When DU ratio is ~0.001 or ~1000, multiply HTML FV by the ratio before matching.

### 2. Wrong Table Selection (7 CIKs)

Template drift detection fails and the engine selects a non-SOI table (governance tables, signatures pages, summary tables).

**Affected CIKs:**
- Barings BDC (1379785): Picks wrong table entirely, 0% recall on 8,918 positions
- PennantPark Investment (1383414): Selects 2-column governance table
- Horizon Tech (1487428): all-grid_index layout makes every table score 0 drift
- Firsthand (1495584): Picks signatures table
- Ares Capital (1287750): 4 filings pick 2-col table (but 14 filings work fine)

### 3. Template Format Drift (6 CIKs with chronic drift)

Template was trained on one era but the XBRL-era HTML uses a different column layout.

**Affected CIKs:**
- Audax Credit BDC (1633858): ALL 12 filings drift. Template expects 4 cols, actual has 11-14.
- Stellus Capital (1551901): ALL 15 filings drift. ZWSP-contaminated headers + column count mismatch.
- BCP/Blue Owl (1372807): 13/14 filings drift. Template trained on 2018 6-col, XBRL era uses 12-col.
- Oaktree Specialty (1414932): 12/14 filings drift. Template expects 7 cols, actual has 13.
- Monroe Capital (1512931): 6/15 filings drift. Multiple format changes across era.
- NewtekOne (1587987): 4/15 filings drift + 8 DU issues.

### 4. Name Matching Failures

Even when HTML extraction works, some positions fail to match due to name format differences:
- XBRL uses pipe-separated identifiers ("Company | Instrument | Affiliation")
- HTML uses plain company names
- The `_extract_xbrl_company_name()` function handles most cases but some structured-comma formats (e.g., "Investment, Affiliation, Type, Company, Industry") extract the wrong segment.

### 5. Rate Accuracy Issues

Overall rate accuracy is 72.4%, but this masks two distinct patterns:
- **High-rate CIKs (>90%):** Blackstone, Main Street, Gladstone, MSC Income -- clean column-mapped rates
- **Low-rate CIKs (<20%):** Prospect Capital (18.2%), WhiteHorse (9.4%), Prospect Floating Rate (21.6%) -- rates embedded in text fields, not separately parsed. These need LLM step #15.

### 6. Maturity Accuracy

Only 50.9% overall. Low maturity accuracy is partly a matching artifact (maturity comparison uses same-month tolerance, but many HTML dates are partial "MM/YYYY" vs XBRL "YYYY-MM-DD") and partly because some templates don't extract maturity at all.

## Prioritized Fix List

### High Impact (would improve overall recall significantly)

1. **Dollar unit auto-correction in validator** -- When agg_fv_ratio is ~0.001 or ~1000, rescale HTML FV before matching. Would fix 15 CIKs (Capital Southwest, both PennantParks, Saratoga, TriplePoint, etc.).

2. **Barings BDC (1379785) template fix** -- 8,918 XBRL positions with 0% recall. Large fund. Table selection needs fixing.

3. **Audax Credit BDC (1633858) template retraining** -- 5,621 positions, 0% recall. Template completely outdated. Needs new variant for 11-14 column format.

4. **Oaktree Specialty Lending (1414932) additional variant** -- 5,390 positions, 88% recall but drifting. Add variant for 13-col expanded format.

5. **Stellus Capital (1551901) template fix** -- 1,107 positions, 0% recall. ZWSP headers need cleanup. Add variant for 7-8 col format.

### Medium Impact

6. **BCP/Blue Owl (1372807) template retraining** -- 2,508 positions. Add 2022 12-col variant.
7. **PennantPark Investment (1383414) table selection** -- 7,186 positions. Fix to select 8-col SOI instead of 2-col governance.
8. **PennantPark Floating Rate (1504619) table selection + DU** -- 7,081 positions. Fix table selection and dollar unit.
9. **MidCap Financial (1278752) DU fix** -- 9,245 positions, 47% recall. DU issues on 5/13.
10. **Goldman Sachs BDC (1572694) name matching** -- 6,056 positions, 60% recall. Improve identifier extraction.

### Low Impact (small funds or edge cases)

11. Horizon Tech (1487428): Add header_text field to template to enable drift-based table rejection
12. Princeton Capital (845385): Only 105 positions total
13. Firsthand Technology (1495584): Only 94 positions
14. CION (1534254) / Terra (1577134): No XBRL position data exists -- not fixable

## Index Error Bar Implications

The 12 Tier 1 CIKs (93.6% recall) represent 44.9% of validated XBRL positions. For these, HTML extraction is reliable for extending coverage to pre-XBRL periods.

- **FV-weighted extraction error for Tier 1:** ~6.4% of positions missed, ~31% of matched positions have >1% FV deviation
- **Rate extraction error for Tier 1:** ~10-15% of positions have >50bps rate deviation (excluding CIKs with no rate extraction)
- **Implication for DIRECT_LENDING index (FV 145.4):** Extraction noise is small relative to the price return signal. The main risk is systematic bias (dollar unit errors inflate/deflate FV), not random noise.

## How to Run

```bash
# Download HTML for XBRL-era filings (one-time, ~72s)
python -m scripts.validate_html_xbrl --download

# Run cross-validation (~47 min)
python -m scripts.validate_html_xbrl --run

# Specific CIKs only
python -m scripts.validate_html_xbrl --run --ciks 1287750,1803498

# Verbose logging
python -m scripts.validate_html_xbrl --run -v
```

## Output Files

- `data/output/html_xbrl_filing_comparison.csv` -- Per-filing metrics (668 rows)
  - Columns: cik, accession_number, filing_date, report_date, xbrl_count, html_count, matched_count, recall, fv_accuracy, rate_accuracy, mat_accuracy, principal_accuracy, agg_fv_ratio, dollar_unit_ok, variant_used, drift_detected
