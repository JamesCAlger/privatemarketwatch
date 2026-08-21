<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Holdings classification & EDA

## 1. Position Classification Stability Across Quarters (2026-04-07)

**Question:** How many positions (by position_id) change their index/asset classification between quarters?

### Summary

| Metric | Value |
|---|---|
| Multi-quarter positions (cik + issuer_name) | 165,604 |
| With index_classification change | 526 (0.32%) |
| With asset_category change | 685 (0.41%) |
| With issuer_category change | 38 (0.02%) |

Classification stability is **99.68%** -- only 526 of 165,604 multi-quarter positions ever change `index_classification`.

### Top Index Classification Transitions (2,436 quarter-over-quarter observations)

| From | To | Count |
|---|---|---|
| DIRECT_LENDING | DIRECT_EQUITY | 605 |
| DIRECT_EQUITY | DIRECT_LENDING | 548 |
| DIRECT_EQUITY | UNCLASSIFIED | 299 |
| UNCLASSIFIED | DIRECT_EQUITY | 297 |
| DIRECT_LENDING | UNCLASSIFIED | 286 |
| UNCLASSIFIED | DIRECT_LENDING | 260 |
| DIRECT_EQUITY | PRIVATE_EQUITY_FUND | 38 |
| PRIVATE_EQUITY_FUND | DIRECT_EQUITY | 29 |
| DIRECT_LENDING | PRIVATE_CREDIT_FUND | 27 |
| PRIVATE_CREDIT_FUND | DIRECT_LENDING | 25 |

### Top Asset Category Transitions

| From | To | Count |
|---|---|---|
| EQUITY_PREFERRED | EQUITY_COMMON | 494 |
| EQUITY_COMMON | EQUITY_PREFERRED | 490 |
| LOAN | EQUITY_COMMON | 407 |
| EQUITY_COMMON | LOAN | 379 |
| EQUITY_COMMON | OTHER | 247 |
| OTHER | EQUITY_COMMON | 245 |
| DEBT | OTHER | 212 |
| OTHER | DEBT | 194 |
| DEBT | LOAN | 122 |

### FV-Weighted Impact

| Transition | Count | Total FV ($B) | Avg FV ($M) |
|---|---|---|---|
| UNCLASSIFIED -> DIRECT_EQUITY | 295 | $8.26B | $28.0M |
| DIRECT_LENDING -> PRIVATE_CREDIT_FUND | 27 | $7.49B | $277.3M |
| DIRECT_EQUITY -> UNCLASSIFIED | 299 | $6.46B | $21.6M |
| DIRECT_EQUITY -> DIRECT_LENDING | 535 | $6.01B | $11.2M |
| DIRECT_LENDING -> DIRECT_EQUITY | 582 | $4.08B | $7.0M |
| DIRECT_LENDING -> UNCLASSIFIED | 284 | $3.16B | $11.1M |

### Top CIKs with Most Instability

| CIK | Entity | Transitions |
|---|---|---|
| 0001447247 | Partners Group Private Equity (Master Fund), LLC | 680 |
| 0001703079 | XAI OCTAGON FLOATING RATE & ALTERNATIVE INCOME TRUST | 257 |
| 0001476765 | GOLUB CAPITAL BDC, Inc. | 247 |
| 0000081955 | RAND CAPITAL CORP | 96 |
| 0001825248 | Franklin BSP Capital Corp | 86 |

### Key Findings

1. **All transitions are same-source** -- zero cross-source (BDC vs N-PORT) mismatches. Not a pipeline artifact.
2. **63.5% of transitions are BDC comparative periods** (same filing, two dates with different classifications). Only ~889 are genuine quarter-over-quarter reclassifications.
3. **Root causes**: (a) filer reclassifies loan->equity on restructuring, (b) multi-tranche positions under one issuer_name with different asset types, (c) catch-all names like "Non Affiliated" grouping unrelated positions.
4. **Biggest FV impact**: DIRECT_LENDING -> PRIVATE_CREDIT_FUND ($7.5B, driven by PennantPark's related-party position).
5. **No pipeline artifacts** -- these are genuine data characteristics, not classification bugs. No action needed.

---

## 2. Firm-Level Exposure Breakdown (2026-04-08)

**Question:** Can we show a split of exposure between different firms (Blackstone, Ares, Blue Owl, etc.) in the private equity and debt indices? What does concentration look like?

### Data Scope

- **Quarter analyzed:** 2025-12-31 (latest with full data)
- **Total index FV:** DIRECT_LENDING $439.4B (72,466 positions, 144 firms), DIRECT_EQUITY $46.8B (5,551 positions, 117 firms)
- **Smaller indices:** PRIVATE_EQUITY_FUND $7.9B (574 positions, 44 firms), PRIVATE_CREDIT_FUND $5.7B (115 positions, 37 firms)

### Top 20 Firms -- DIRECT_LENDING

| # | Entity | FV ($B) | Pos | % |
|---|---|---|---|---|
| 1 | Blackstone Private Credit Fund | 84.2 | 1,881 | 19.2% |
| 2 | Cliffwater Corporate Lending Fund | 36.2 | 7,280 | 8.2% |
| 3 | Blue Owl Credit Income Corp. | 33.7 | 753 | 7.7% |
| 4 | HPS Corporate Lending Fund | 26.1 | 802 | 5.9% |
| 5 | Apollo Debt Solutions BDC | 24.5 | 729 | 5.6% |
| 6 | Ares Capital Corp | 22.6 | 1,005 | 5.1% |
| 7 | Ares Strategic Income Fund | 20.4 | 1,018 | 4.6% |
| 8 | Blackstone Secured Lending Fund | 14.1 | 601 | 3.2% |
| 9 | Blue Owl Capital Corp | 13.5 | 528 | 3.1% |
| 10 | FS KKR Capital Corp | 12.4 | 497 | 2.8% |
| 11 | Blue Owl Technology Finance Corp. | 12.3 | 344 | 2.8% |
| 12 | Golub Capital Private Credit Fund | 9.8 | 965 | 2.2% |
| 13 | Golub Capital BDC, Inc. | 8.0 | 1,410 | 1.8% |
| 14 | Oaktree Strategic Credit Fund | 7.4 | 367 | 1.7% |
| 15 | Blue Owl Technology Income Corp. | 5.9 | 400 | 1.3% |
| 16 | Monroe Capital Income Plus Corp | 5.4 | 775 | 1.2% |
| 17 | Prospect Capital Corp | 5.0 | 162 | 1.1% |
| 18 | Barings Private Credit Corp | 4.5 | 666 | 1.0% |
| 19 | Franklin BSP Capital Corp | 4.5 | 479 | 1.0% |
| 20 | Main Street Capital Corp | 4.2 | 469 | 1.0% |

**Top 20 cumulative: 80.7% of index FV.**

### Top 20 Brands (consolidated) -- DIRECT_LENDING

Many fund managers operate multiple CIKs (separate BDC vehicles, interval funds). Consolidated:

| # | Brand | CIKs | FV ($B) | % | Cumulative % |
|---|---|---|---|---|---|
| 1 | Blackstone | 3 | 99.8 | 22.7% | 22.7% |
| 2 | Blue Owl / Owl Rock | 5 | 66.8 | 15.2% | 37.9% |
| 3 | Ares | 3 | 44.2 | 10.0% | 48.0% |
| 4 | Cliffwater | 1 | 36.2 | 8.2% | 56.2% |
| 5 | HPS | 2 | 28.1 | 6.4% | 62.6% |
| 6 | Apollo | 3 | 26.7 | 6.1% | 68.6% |
| 7 | Golub | 7 | 21.8 | 5.0% | 73.6% |
| 8 | FS KKR | 1 | 12.4 | 2.8% | 76.4% |
| 9 | Oaktree | 4 | 11.7 | 2.7% | 79.1% |
| 10 | Goldman Sachs/Barings | 3 | 7.6 | 1.7% | 80.8% |

### Concentration Analysis

| Index | Top 5 | Top 10 | Top 20 | Total Firms |
|---|---|---|---|---|
| DIRECT_LENDING | 46.6% | 65.5% | 80.7% | 144 |
| DIRECT_EQUITY | 43.5% | 66.6% | 85.1% | 117 |
| PRIVATE_CREDIT_FUND | 91.7% | 96.7% | 99.1% | 37 |
| PRIVATE_EQUITY_FUND | 84.3% | 95.4% | 99.1% | 44 |

DIRECT_LENDING and DIRECT_EQUITY are moderately concentrated -- similar to public credit indices. The fund-of-funds indices (PRIVATE_CREDIT_FUND, PRIVATE_EQUITY_FUND) are heavily concentrated in a few allocators.

Distribution stats for DIRECT_LENDING: median firm FV $0.25B, p25 $0.05B, p75 $1.6B, max $99.8B (Blackstone), stdev $13.4B. Highly right-skewed.

### Parent-Subsidiary Relationships

Major multi-CIK brand families found:

- **Golub** (7 CIKs, $22.4B): Golub Capital BDC, Golub Capital Private Credit Fund, Golub Capital BDC 4, Golub Capital Direct Lending Corp, Golub Capital Direct Lending Unlevered Corp, Golub Capital Private Income Fund I/S
- **KKR** (7 CIKs, $22.4B): FS KKR Capital Corp, KKR FS Income Trust, KKR FS Income Trust Select, KKR Enhanced US Direct Lending, KKR Real Estate Select Trust, Capital Group KKR Multi-Sector/Core Plus
- **Blue Owl / Owl Rock** (5 CIKs, $74.2B): Blue Owl Capital Corp, Blue Owl Capital Corp II, Blue Owl Credit Income Corp, Blue Owl Technology Finance Corp, Blue Owl Technology Income Corp
- **Ares** (6 CIKs, $54.4B): Ares Capital Corp, Ares Strategic Income Fund, Ares Private Markets Fund, Ares Core Infrastructure Fund, Antares Strategic/Private Credit Fund
- **Apollo** (4 CIKs, $29.1B): Apollo Debt Solutions BDC, Apollo Diversified Real Estate Fund, Apollo Origination II (Levered/UL)
- **Oaktree** (4 CIKs, $12.1B): Oaktree Strategic Credit, Oaktree Specialty Lending, Oaktree Gardens OLP, Oaktree Asset-Backed Income Fund
- **New Mountain** (4 CIKs, $7.6B): New Mountain Finance Corp, New Mountain Private Credit Fund, New Mountain Guardian IV BDC, New Mountain Guardian IV Income Fund
- **Barings** (3 CIKs, $8.9B): Barings Private Credit Corp, Barings BDC, Barings Capital Investment Corp
- **Monroe Capital** (3 CIKs, $6.3B): Monroe Capital Income Plus, Monroe Capital Corp, Monroe Capital Enhanced Corporate Lending
- **Nuveen Churchill** (3 CIKs, $3.2B): Nuveen Churchill Private Capital Income, Nuveen Churchill Direct Lending, Nuveen Churchill BDC V

### Source Breakdown (BDC XBRL vs N-PORT)

Most top brands are BDC-source only. Notable exceptions:
- **Cliffwater** ($38.8B): 100% N-PORT (it files as an interval fund, not a BDC)
- **Partners Group** ($7.8B): 100% N-PORT
- **Apollo** ($29.1B): $26.7B BDC + $2.4B N-PORT (Apollo Diversified Real Estate files N-PORT)
- **KKR** ($7.6B ex-FS KKR): $6.3B BDC + $1.2B N-PORT (Capital Group KKR funds file N-PORT)

### Time Series -- Top 5 Brand Shares of DIRECT_LENDING

| Quarter | Blackstone | Blue Owl | Ares | Cliffwater | HPS | Top 5 Total | Index $B | Firms |
|---|---|---|---|---|---|---|---|---|
| 2022-09-30 | 39.8% | 8.6% | 11.0% | 6.5% | 0.0% | 66.0% | 142.8 | 34 |
| 2022-12-31 | 38.0% | 8.2% | 10.6% | 6.4% | 0.0% | 63.2% | 150.4 | 36 |
| 2023-03-31 | 26.7% | 16.8% | 6.8% | 4.2% | 2.9% | 57.4% | 226.5 | 99 |
| 2023-06-30 | 22.9% | 17.6% | 7.3% | 4.8% | 3.1% | 55.6% | 223.7 | 102 |
| 2023-09-30 | 22.4% | 17.8% | 7.5% | 5.4% | 3.3% | 56.4% | 232.1 | 109 |
| 2023-12-31 | 20.8% | 18.1% | 7.7% | 6.1% | 3.9% | 56.5% | 243.1 | 115 |
| 2024-03-31 | 19.9% | 17.9% | 7.5% | 6.5% | 3.9% | 55.7% | 261.4 | 115 |
| 2024-06-30 | 20.1% | 18.2% | 7.9% | 6.7% | 4.1% | 57.1% | 292.6 | 118 |
| 2024-09-30 | 21.1% | 17.8% | 8.1% | 6.6% | 4.4% | 58.1% | 320.8 | 123 |
| 2024-12-31 | 21.9% | 14.9% | 8.9% | 7.1% | 5.2% | 58.0% | 343.9 | 131 |
| 2025-03-31 | 20.7% | 16.1% | 8.8% | 7.1% | 5.5% | 58.1% | 373.6 | 133 |
| 2025-06-30 | 20.1% | 15.6% | 9.1% | 7.3% | 5.8% | 57.9% | 399.5 | 138 |
| 2025-09-30 | 20.9% | 15.9% | 10.0% | 8.2% | 6.5% | 61.5% | 405.3 | 143 |
| 2025-12-31 | 22.7% | 15.2% | 10.0% | 8.2% | 6.4% | 62.6% | 439.4 | 144 |

Note: Pre-2022Q3 data is dominated by N-PORT filers (Cliffwater, Partners Group) because BDC XBRL coverage starts ~2022. The jump from 11 firms in 2022Q2 to 34 in 2022Q3 reflects the SEC XBRL mandate taking effect.

### HHI (Herfindahl-Hirschman Index)

The DIRECT_LENDING index transitioned from highly concentrated (HHI >2500, pre-2023) to unconcentrated (HHI <1500, from 2023Q1 onward) as BDC XBRL coverage expanded. Current HHI is ~1,052 with 106 distinct brands -- comparable to broadly diversified public credit indices. The early-period concentration is an artifact of the data coverage ramp-up, not a real market feature.

### PRIVATE_EQUITY_FUND Top Firms

| # | Entity | FV ($B) | % |
|---|---|---|---|
| 1 | Blackstone Private Credit Fund | 1.9 | 24.6% |
| 2 | Ares Private Markets Fund | 1.9 | 24.5% |
| 3 | Partners Group Private Equity Fund | 1.6 | 19.8% |
| 4 | NB Private Markets Access Fund | 0.7 | 8.7% |
| 5 | Apollo Origination II (UL) | 0.5 | 6.7% |

Top 5 = 84.3%. These are allocators to PE funds, not the PE funds themselves.

### PRIVATE_CREDIT_FUND Top Firms

| # | Entity | FV ($B) | % |
|---|---|---|---|
| 1 | Cliffwater Corporate Lending Fund | 3.8 | 67.3% |
| 2 | Bluerock Private Real Estate Fund | 0.5 | 8.1% |
| 3 | Franklin BSP Capital Corp | 0.5 | 7.9% |
| 4 | Blue Owl Credit Income Corp. | 0.3 | 4.9% |
| 5 | PennantPark Investment Corp | 0.2 | 3.5% |

Top 5 = 91.7%. Cliffwater dominates (it holds positions in other private credit funds).

### Key Findings

1. **Yes, firm-level exposure splits are feasible.** Entity_name cleanly identifies the reporting fund, and brand-level grouping captures parent-subsidiary relationships.
2. **DIRECT_LENDING is moderately concentrated.** Top 5 brands hold ~47% at the entity level, ~63% at the consolidated brand level. Blackstone alone is ~23%.
3. **Brand consolidation matters significantly.** Blue Owl goes from 7.7% (largest single CIK) to 15.2% (5 CIKs combined). Golub goes from 2.2% to 5.0% (7 CIKs). KKR goes from 2.8% (FS KKR alone) to ~4.6% (7 CIKs including Capital Group vehicles).
4. **Concentration has been stable since 2023Q1** when broad BDC coverage began. Top 5 brand share has hovered at 56-63%, and HHI at 900-1100. The index is not becoming more or less concentrated.
5. **The fund-of-funds indices are extremely concentrated** -- top 3-5 firms hold 85-92% of FV. These are really a handful of large allocators.
6. **Source split is clean.** Most large brands are 100% BDC-source. Cliffwater ($38.8B) and Partners Group ($7.8B) are the main N-PORT-only brands. Very few brands have mixed BDC+N-PORT sources.

---

## 5. BDCs with Holdings but Missing from Unified (2026-05-04)

**Question:** 20 BDCs have position-level data in `bdc_holdings.csv` (23,703 total rows, all with `latest=2025-12-31` except one) but zero rows in `private_markets_holdings.csv` from 2022Q4 onwards. Why?

These are mostly newer private BDCs (Fidelity, Sixth Street, MSD, Diameter, TCW, etc.) with substantial portfolios. Possible causes: comparative-period-only rows (`period < report_date`), classification falling to UNCLASSIFIED, or CIK format mismatch in the unified pipeline.

### CIK List

| CIK | Holdings | Entity Name |
|---|---|---|
| 0000845385 | 253 | REGAL ONE CORP |
| 0001577134 | 10 | Terra Income Fund 6, Inc. |
| 0001817825 | 1,502 | MSC Capital LLC |
| 0001825265 | 1,420 | TCW Direct Lending VIII LLC |
| 0001849894 | 3,356 | MSD Investment, LLC |
| 0001860424 | 1,899 | Onex Falcon Direct Lending BDC Fund |
| 0001899996 | 5,251 | Fidelity Private Credit Central Fund LLC |
| 0001916099 | 1,267 | Diameter Credit Co |
| 0001916608 | 924 | TCW Star Direct Lending LLC |
| 0001920453 | 4,237 | Fidelity Private Credit Fund |
| 0001925309 | 1,968 | Sixth Street Lending Partners |
| 0001950572 | 88 | BIP Ventures Evergreen BDC |
| 0001985375 | 499 | Muzinich Corporate Lending Income Fund, Inc. |
| 0001998387 | 121 | 5C Lending Partners Corp. |
| 0002020354 | 383 | West Bay BDC LLC |
| 0002041841 | 157 | Lord Abbett Private Credit Fund S |
| 0002043133 | 15 | TCW Steel City Perpetual Levered Fund LP |
| 0002043759 | 146 | LAGO Evergreen Credit |
| 0002045370 | 350 | Remora Capital Corp |
| 0002089126 | 37 | PENNANTPARK PRIVATE INCOME FUND |

### Root Cause: Overly Aggressive Aggregate Filter

**Status: Diagnosed.** The `_sql_is_bdc_aggregate()` filter in `unified_holdings.py` removes 100% of rows for 17 of 20 CIKs. These are not genuinely aggregate rows -- they are position-level holdings whose XBRL identifiers embed the full dimension hierarchy path, triggering false-positive matches on substring patterns designed for section headers.

**Confirmed non-causes:**
- All 20 CIKs are in `combined_universe.csv` (vehicle_type=bdc)
- 19 of 20 have current-period data (`period = report_date`); only Terra Income Fund (0001577134) has comparatives only
- No CIK-level filtering exists in the pipeline -- all filtering is row-level
- CIK format is correct (10-digit padded)

### Filter Pipeline Trace (2025-12-31)

| CIK | Entity | Cur Rows | Agg Filtered | Artifact Rm | Surviving |
|---|---|---|---|---|---|
| 0001899996 | Fidelity Private Credit Central | 349 | 349 | 0 | **0** |
| 0001920453 | Fidelity Private Credit Fund | 345 | 345 | 0 | **0** |
| 0001849894 | MSD Investment | 203 | 203 | 0 | **0** |
| 0001925309 | Sixth Street Lending Partners | 120 | 120 | 0 | **0** |
| 0001860424 | Onex Direct Lending BDC | 93 | 93 | 0 | **0** |
| 0001916099 | Diameter Credit Co | 167 | 167 | 0 | **0** |
| 0001817825 | Steele Creek Capital | 277 | 277 | 0 | **0** |
| 0001825265 | TCW Direct Lending VIII | 65 | 65 | 0 | **0** |

### False-Positive Patterns

Three patterns in `_BDC_AGGREGATE_PATTERNS` and related filter clauses cause false positives:

**1. "non-control" / "non-controlled" substring match (primary, 80% of filtered rows)**

These patterns match section headers like "Non-Controlled/Non-Affiliated Investments" but also match position-level identifiers that embed the affiliation dimension into the identifier string:

```
INTENDED:  "Non-Controlled/Non-Affiliated Investments"  (section header, 41 chars)
FALSE POS: "Investments -- non-controlled/ non-affiliate Equity Construction & Engineering BPCP Crafts Intermediate" (position, 103 chars)
FALSE POS: "Non-controlled/Non-affiliated investments Debt Investments Automotive Burgess Point Purchaser" (position, 92 chars)
```

Affected CIKs: 0001899996, 0001920453, 0001849894, 0001860424, 0001916099, 0001817825, 0001985375, 0001998387, 0002045370, 0002043759, 0001950572 (11 CIKs).

**This also causes silent data loss for 38 existing working BDCs**, which have 12,825 rows matching "non-control" that are >80 chars (likely position-level). Those CIKs still appear in the output because they have other non-matching rows, but are missing positions.

**2. Category-prefix + guard failure (secondary)**

The filter `starts_with(_lower_id, 'investments ')` with guard `NOT contains(_raw_id, ' - ')` misses BDCs using double-dash `" -- "`, comma, or space as separators:

```
INTENDED:  "Investments" + guard catches "Investments - non-controlled/non-affiliated First Lien..."
FALSE POS: "Investments -- non-controlled/ non-affiliate Equity..." (' -- ' does NOT contain ' - ')
```

Also affects "debt investments " prefix for Sixth Street (0001925309) and "equity investments " prefix. Affected CIKs: 0001899996, 0001920453, 0001925309, 0001916099, 0001825265.

**3. Percentage-suffix regex `\d+\.?\d*%\s*$` (tertiary)**

Catches identifiers ending with interest rate info (e.g., "...SOFR + 5.25%"). Sixth Street embeds par, maturity, and rate in the identifier string.

Affected CIKs: 0001925309 (525/1154 rows), 0001825265 (245/815 rows).

### Identifier Format Examples

These BDCs concatenate the entire XBRL typed dimension hierarchy into a single `investment_identifier` field:

| CIK | Identifier Format |
|---|---|
| 0001899996 (Fidelity) | `Investments -- non-controlled/ non-affiliate Equity {Industry} {Company} {Instrument}` |
| 0001920453 (Fidelity) | `Investments - non-controlled / non-affiliated First Lien Debt {Industry} {Company} {Rate}` |
| 0001849894 (MSD) | `Investments Investments - non-controlled/non-affiliated First Lien Debt {Industry} {Company}` |
| 0001925309 (Sixth St) | `Debt Investments {Industry} {Company} First-lien loan ($X par, due M/YYYY) Interest rate X.X%` |
| 0001860424 (Onex) | `Non-controlled/Non-affiliated investments Debt Investments {Industry} {Company}` |
| 0001916099 (Diameter) | `Investments Non-Controlled/Non-Affiliated First Lien Debt {Industry} {Company}` |
| 0001817825 (Steele Creek) | `Non-controlled/Non-Affiliated Investments -X% of Shareholder's Equity - Investments...` |

### Impact

| Metric | Value |
|---|---|
| Missing CIKs | 20 (all in universe, all BDC) |
| Missing position-level rows (2025-12-31) | ~2,197 (after excluding subtotals) |
| Missing position-level FV (2025-12-31) | ~$8.4B |
| Current unified FV (2025-12-31) | $561.2B |
| FV increase if fixed | ~1.5% |
| Additional silent data loss (existing BDCs) | ~12,825 rows across 38 CIKs |

### Top Missing Funds by FV (2025-12-31)

| CIK | Entity | Rows | FV ($M) |
|---|---|---|---|
| 0001916099 | Diameter Credit Co | 167 | 2,532 |
| 0001920453 | Fidelity Private Credit Fund | 345 | 2,101 |
| 0001899996 | Fidelity Private Credit Central | 349 | 1,621 |
| 0002045370 | Remora Capital Corp | 173 | 1,042 |
| 0002041841 | Lord Abbett Private Credit Fund | 59 | 618 |
| 0001985375 | Muzinich Corporate Lending | 122 | 567 |
| 0001817825 | Steele Creek Capital | 277 | 461 |
| 0002020354 | West Bay BDC | 126 | 444 |

### Recommended Fix

Add a **length guard** to the "non-control"/"non-controlled" patterns: only match when the identifier is short (<60-80 chars). Section headers are typically 25-55 chars; position identifiers with embedded hierarchy are 80-200+ chars. This distinguishes genuine subtotals from positions.

For the category-prefix guard: extend to also recognize `" -- "` (double dash) as a separator, not just `" - "`.

For the percentage-suffix regex: add a guard that the identifier doesn't contain company name indicators (Inc., LLC, Corp., etc.) or is short.

### Data Quality Notes

Several of these BDCs have sparse XBRL financial tagging:
- Sixth Street (0001925309): 120 positions but only 14 have FV as a separate XBRL fact. Par, maturity, and rate are embedded in the identifier string (e.g., "$303,927 par, due 2/2032").
- MSD (0001849894): 203 positions but only 14 with FV. Most financial data is embedded in the identifier.
- Onex (0001860424): 93 positions, 0 with FV. All data embedded in identifier.

These BDCs would benefit from identifier parsing to extract embedded financial values, similar to the existing BDC identifier parsing for pipe/comma-delimited formats.

---

## 2026-06-16 - Derivative universe characterization + hedge-vs-portfolio base rates

Question: what kinds of derivatives exist across the BDC universe, and can we tell whether a
derivative is a financing/ALM hedge of the BDC's own borrowings vs. a portfolio asset --
specifically, could interest-rate (IR) swaps be converting floating-rate portfolio loans to
fixed rather than hedging the BDC's own debt? (Prerequisite for an analytics-only Derivatives
bucket; derivatives must NEVER become index constituents.)

Method (cache-only, read-only, scan of all 2,977 cached XBRL filings): (1) extract member
names on `us-gaap:DerivativeInstrumentRiskAxis` and categorize instrument types + distinct
CIKs; (2) hedge-designation prevalence (`HedgingDesignationAxis` /
`DesignatedAsHedgingInstrumentMember` / FairValue+CashFlowHedging); (3) hedged-item naming
(do IR-swap members name own Notes/Facility vs a portfolio asset?); (4) notional-to-debt
reconciliation: per CIK-quarter sum IR-derivative period-end notional vs `fund_financials`
borrowings; (5) scale vs portfolio; (6) definitional test: do derivatives appear under
`InvestmentOwnedAtFairValue` (schedule of investments) or only in the derivatives note?
(7) spot-check of the 5 SOI-overlap CIKs.

Findings:
1. COVERAGE: 111 / ~425 BDCs hold any derivative facts (~26%). Per-contract, dimensioned on
   DerivativeInstrumentRiskAxis.
   CORRECTION (2026-06-16, net-FV reliability spot-check): an earlier claim that the standard
   net-FV concepts "appear ZERO times" was a REGEX BUG -- the scan used `<[a-z0-9]+:` which
   excludes the hyphen in the `us-gaap` prefix, silently skipping every us-gaap concept. With
   correct matching the standard ASC-815 net-FV concepts are WELL covered:
   `DerivativeLiabilities` 76 CIKs, `DerivativeAssets` 68, `DerivativeFairValueOfDerivative-
   Liability` 47, `DerivativeFairValueOfDerivativeAsset` 46. 78/111 derivative CIKs (~70%) have
   a tagged net-FV concept. Net derivative FV should therefore be READ as
   `DerivativeFairValueOfDerivativeAsset - DerivativeFairValueOfDerivativeLiability` (or
   `DerivativeAssets - DerivativeLiabilities`), NOT derived from gross gain/loss. The gross
   unrealized gain/loss concepts are the RARE path (3 CIKs, e.g. 1742313); per-contract gross
   gain/loss is $0 at period-end for most IR-swap filers, so deriving from them would wrongly
   yield zero. Use gross gain-loss only as a last-resort fallback.
2. TYPES (distinct CIKs): FX forwards 53, interest-rate swaps 48, FX/currency-other 26,
   IR floors 12 (see caveat 8), options/stock-options 10, IR caps/collars 4, currency swaps 3,
   total return swaps 2, futures 1.
3. HEDGE DESIGNATION: `DesignatedAsHedgingInstrumentMember` in 186 files / 25 CIKs;
   `HedgingDesignationAxis` 246 files / 32 CIKs; `NotDesignatedAsHedgingInstrumentMember` = 0
   (filers tag designated hedges; undesignated economic hedges just lack the axis).
4. HEDGED-ITEM NAMING (decisive): of 131 distinct IR-swap member names, 60 explicitly name the
   BDC's OWN notes by maturity year (InterestRateSwap2029NotesMember, ...EUR2031NotesMember,
   ...June2028NotesMember). ZERO name a portfolio loan / borrower / investment. (The
   `DerivativeAssetInterestRateSwap*Member` names are the ASC-815 balance-sheet position of the
   swap, not "an asset being hedged.")
5. NOTIONAL-TO-DEBT (287 filings, 43 CIKs with both figures): ratio = IR notional / own debt
   median 0.42 (p25 0.21, p75 0.82). ~88% of filings have ratio <= 1.5 (consistent with
   hedging some-to-all of own borrowings; partial-hedge ratios < 1 are normal). Tail > 1.5x =
   34 filings / 12 CIKs (review set; partly gross-notional double-count of pay/receive legs).
6. SCALE vs PORTFOLIO: borrowings ~0.47x portfolio FV (median), so IR notional ~0.20x of the
   portfolio -- far too small to be converting the (much larger) floating-rate loan book to
   fixed; it tracks the debt scale.
7. DEFINITIONAL TEST (schedule-of-investments vs derivatives note): IR derivatives appear in
   the derivatives note for 49 CIKs vs only 5 with any `InvestmentOwnedAtFairValue` overlap;
   TRS 0 SOI / 2 note; FX 1 SOI / 51 note. Derivatives of every type live in the
   risk-management note, NOT the schedule of investments.
8. SPOT-CHECK of the 5 IR-SOI-overlap CIKs: 1422183 (FS KKR), 1736035, 1803498 (Blackstone
   PCF) = the BDC's OWN swaps tagged with the `InvestmentOwnedAtFairValue` CONCEPT but
   dimensioned ONLY by a generic numbered swap member with NO issuer dimension (Blackstone
   values are negative -> derivative MTM, not loans). 1825384 = negligible (0 in recent
   filings). 1989817 = FALSE POSITIVE: dimension is `InvestmentInterestRateFloorAxis`
   (`InvestmentInterestRateFloorOneMember`) -- a portfolio LOAN's rate-floor attribute
   ($78M->$167M->$202M), not a floor derivative; the member-text regex over-matched
   "InterestRateFloor".

Conclusion: BDC interest-rate derivatives are overwhelmingly liability/ALM hedges of the
fund's OWN issued notes (BDCs issue fixed-rate notes and swap to floating to match their
floating-rate assets) -- the OPPOSITE of converting portfolio loans to fixed. No member names
a portfolio borrower; notional ties to debt not the loan book; they sit in the derivatives
note. The hypothesis that IR swaps convert portfolio loans floating->fixed is unsupported in
every edge case examined.

Lessons for a build:
- CONCEPT NAME is not a reliable portfolio-vs-derivative discriminator (some filers tag own
  swaps as `InvestmentOwnedAtFairValue`). The reliable discriminator is the ISSUER /
  portfolio-company dimension: real holdings carry a borrower identifier; swaps carry ONLY
  DerivativeInstrumentRiskAxis. The current extractor keys on the investment-identifier
  dimension, which these swaps lack -> it correctly never pulls them into bdc_holdings today
  (no leakage).
- `InvestmentInterestRateFloorAxis` (a LOAN attribute) must NOT be conflated with
  interest-rate-floor DERIVATIVES; the "IR floor: 12 CIKs / 2,096 facts" count is an upper
  bound contaminated by loan rate-floor attributes.
- Hedge-vs-portfolio is a calibrated classification (epistemic uncertainty), not aleatory: hard
  evidence (designation tag, own-notes naming, SOI-vs-note location, notional reconciliation)
  resolves the large majority; a ~5-12 CIK residual warrants per-filer review, not a guess.

Design follow-up: see `docs/derivative_role_classifier_design.md`.


## iXBRL capture of instrument type (revolver / DDTL / term loan), like lien (2026-06-17)

**Question:** lien rank is recovered from BDC iXBRL via subtotal dimension members +
document-order grouping + subtotal reconciliation (pipeline/bdc_lien_hierarchy.py,
mapping member local-names like `DebtSecuritiesFirstLienMember` -> lien tier). Can
the per-row instrument type (Revolver / Delayed Draw / Term Loan), which lives in row
text not a clean per-leaf tag, be captured the same way?

**Answer: yes, strongly viable -- it reuses the lien machinery almost directly.**
Instrument type is heavily tagged in the SAME explicit dimension members. Member-name
occurrence counts across the 2,977 cached XBRL instances (rg over data/raw/filings/bdc_xbrl):

- Dedicated instrument-type members: `RevolvingCreditFacilityMember` 44,129;
  `DelayedDrawTermLoanMember` 28,134; `RevolverMember` 26,067; `TermLoanMember` 17,764;
  `UnitrancheDebtMember` 6,208.
- COMBINED lien+type members (one member carries BOTH): `FirstLienSeniorSecuredRevolvingLoanMember`
  14,699; `FirstLienSeniorSecuredTermLoanMember` 13,039; `FirstLienSeniorSecuredDelayedDrawTermLoanMember`
  5,652; `FirstLienDelayedDrawTermLoanMember` 4,300; `FirstLienRevolvingLoanMember` 3,912; etc.
- For comparison, lien-only members: `DebtSecuritiesFirstLienMember` 25,603;
  `UnsecuredDebtMember` 25,782; `DebtSecuritiesSecondLienMember` 13,195.

**Mechanism:** identical to lien. These are SUBTOTAL members; leaf positions still carry only
`InvestmentIdentifierAxis`, so type is recovered by the existing document-order grouping in
bdc_lien_hierarchy.py with the existing subtotal-reconciliation gate (TOL 0.5%). For the
combined members, the SAME member string the lien mapper already reads also yields the type --
so it is a second attribute parsed from the same recovered run, near-zero extra work.

**Recommended implementation (not yet done -- "see if" scope):**
1. Add `_instrument_type(member_localname)` in bdc_lien_hierarchy.py: RevolvingCreditFacility/Revolver
   -> "Revolver"; DelayedDrawTermLoan -> "Delayed Draw Term Loan"; TermLoan -> "Term Loan";
   Unitranche -> "Unitranche". EXCLUDE rate-index members (`TermLoanPrimeIndexOneMember` etc. -- these
   encode the reference rate, not the instrument type).
2. Carry an `instrument_type_xbrl` + `instrument_type_status` (value/derived/validation_needed) field
   through the iXBRL field-status overlay, mirroring lien_position, gated by the same reconciliation.
3. Measure per-CIK coverage like lien (DIRECT_LENDING lien is ~83%); report it. Keep the text-parsed
   `instrument_description` / `_inst_subtype` as the fallback where no member exists.
4. False-positive guards: combined members must not let an instrument-type substring leak a wrong lien
   (and vice versa); add a test that `FirstLienSeniorSecuredTermLoanMember` -> lien First + type Term Loan.

**Caveat:** coverage of type vs lien differs per filer -- some tag lien-only (`DebtSecuritiesFirstLienMember`),
some type-only (`RevolverMember`); a minority may tag the combined member directly on the leaf (even
easier -- no document-order needed). Coverage must be measured, not assumed.

## 2026-06-17 - iXBRL field-status overlay was joining on the WRONG key; fix recovers lien/maturity

Question (from gold labeling): a lot of flattened-filer direct loans show "First Lien Debt" in the
source section header but production `lien_position` is None (e.g. Gannett Fleming, BCRED). The iXBRL
bridge clearly captures lien -- so why isn't it in production?

Root cause: the bridge field-status artifact (`bdc_ixbrl_field_status.csv`, 1.18M rows / 195 CIKs)
DOES capture it -- BCRED 2025-12-31 has lien_status='value' for 2,810 positions, maturity for ~2,646.
But `apply_ixbrl_field_status_overlay` keyed production on `_raw_id_lower(bdc_investment_identifier)` --
the STRIPPED identifier -- while the artifact keys on `raw_id_lower` = the FULL inline-XBRL member
(carrying the affiliation suffix, e.g. `"... | Non-Affiliated Issuer"`). For flattened filers those
never match, so the captured values were dropped at the merge. Production lien stayed ~709 (35%),
maturity ~709, both mostly from the text classifier on structured filers, NOT the bridge.

PROTOTYPE (`scripts/gold/prototype_lien_overlay.py`, read-only, BCRED 2025-12-31, 2,002 positions):
re-keying on the full XBRL member -- which production preserves in `bdc_dimensions_raw`
(`...axis=<member>`) and the artifact stores in `raw_id_lower` -- gives:
  - match rate     37% -> 100%
  - lien filled    709 (35%) -> 1,995 (100%)   [+1,286; residual 7 are equity/JV with no lien]
  - maturity       709 (35%) -> 1,891 (94%)    [+1,182; residual are equity/no-maturity]
Gannett Fleming flips None -> First Lien.

FIX IMPLEMENTED: `apply_ixbrl_field_status_overlay` now keys the production side on the full member
from `bdc_dimensions_raw` (strip `^[^=]*=`, `_norm_text`, lower), falling back to
`bdc_investment_identifier` when dims is absent. Blank-only / no-clobber is unchanged, so it is purely
additive -- structured filers and the text classifier are untouched (can only FILL more blanks, never
change a value). Test added: `test_ixbrl_overlay_keys_on_full_member_via_dims` (recovers via dims;
control without dims reproduces the miss). `tests/test_bdc_xbrl_html_bridge_fields.py` 33 passed.

Scope: universe-wide across the 195 artifact CIKs; flattened filers dominate the gap (cohort had
~$393B of blank-lien direct-lending FV, mostly recoverable). NOT YET DONE: a `--unified` rebuild to
land it in the production parquet + measure the universe-wide lien/maturity lift (deferred -- it would
regenerate the parquet the gold set is currently being labeled against; run on explicit go).

## Per-position instrument-type XBRL reconciliation: measured ~0 lift (2026-06-17)

Tested whether per-position instrument_type coverage (text classifier, 40.5% of
DIRECT_LENDING) could be lifted for subtotal-tagging filers (e.g. Ares) by
recovering per-leaf type from XBRL document order + a subtotal reconciliation gate
(the recover_lien-style engine, `pipeline.bdc_lien_hierarchy.recover_instrument_type`).

RESULT (cache-only build over 2,977 filings): only 423 leaves reconciled cleanly
(403 Unitranche, 13 Revolver, 7 Term Loan), 12 CIKs. Joined to holdings by
(cik, report_date, lower(bdc_investment_identifier)), they fill **6** currently-blank
DL rows. Projected DL coverage 40.5% -> 40.5%. Ares (1287750): 0 additional (stays
19.9% on its 13,010 DL positions).

WHY it fails: (1) leaf runs rarely close on a type-bearing subtotal that reconciles
exactly -- type subtotals are nested with sector/lien partitions so contiguous
typeless runs don't sum to a single type subtotal; (2) the recovered leaf
identifier (typed-member string) rarely matches the parsed `bdc_investment_identifier`
in holdings. This is the same reason production lien does NOT use the recover_lien
engine for per-position lien (it's unused) -- per-position lien comes from the HTML
section-header walk, not XBRL leaf-run reconciliation.

DECISION: do NOT wire per-position XBRL recovery into the unified overlay (no
benefit). The engine primitive + tests are kept as documented evidence;
no production artifact is built. The real lever to lift coverage is the HTML
section-header walk (extend `_SECTION_PATTERNS` in bdc_xbrl_html_bridge.py to
instrument-type section headers like "First Lien Senior Secured Term Loans"), the
same mechanism that gives lien its 67% per-position coverage -- a larger, separate
piece of work, not attempted here.

