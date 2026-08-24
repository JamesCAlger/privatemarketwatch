<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Quarter-over-quarter EDA

## 2026-07-24 - Why Q1 2026 has fewer facts than Q4 2025 (quarter-over-quarter EDA)

Question: the shadow ledger has ~10.3K rows for 2026-03-31 vs ~15.2K for
2025-12-31. Is Q1 under-filed, under-extracted, or is the gap structural?

Method: scripts/tmp_eda_q4_q1_facts.py (DuckDB aggregations over
bdc_filings_index, bdc_holdings, private_markets_holdings.parquet,
fund_financials, shadow ledger). Run 2026-07-24 on post-q1shakedown outputs.

Findings -- the gap is structural, not a coverage defect:

1. COMPARATIVE RESTATEMENT is the dominant effect (~45% of Q4 holdings
   facts). Q4 2025: 62,835 current-period rows + 52,405 comparative rows
   restated inside later (Q1) filings = 115K. Q1 2026: 63,737 current rows +
   ZERO comparatives, because no Q2 2026 filings exist yet. Q1 gains its
   comparative layer when Q2 10-Qs arrive (~Aug 2026). Current-period BDC
   volume is FLAT quarter-over-quarter (62.8K -> 63.7K rows; 171 -> 174 CIKs).
2. FORM MIX: Q4 was 10-K season (164 10-K + 21 10-Q); Q1 is 10-Q-only
   (185 10-Q + 2 10-K). Annual filings carry richer disclosure, which shows
   up as more oracle CHECKS (3,355 -> 2,309) at flat oracle UNITS
   (15,718 -> 15,722) and more fund_financials rows (354 -> 198, though Q1
   rows are DENSER: 6.14 vs 4.97 of 8 core facts, thanks to the fresh
   companyfacts).
3. N-PORT LAG: unified holdings Q4 has 278 CIKs / $701.6B vs Q1 171 /
   $568.7B. The ~107 missing CIKs are N-PORT-sourced interval/tender funds --
   the latest DERA N-PORT dataset is 2025q4 (Q1 2026 zip not yet published).
   Irrelevant to the v1 BDC cohort; explains most of the unified row/FV gap.
4. LATE FILERS are negligible: only 2 BDCs with Q4 current-period holdings
   lack Q1 (MONROE CAPITAL Corp, Nuveen Churchill BDC V).
5. html_extract has zero Q1 ledger rows -- expected (pre-XBRL HTML lane has
   no Q1 targets; all Q1 filers are XBRL).

Implication: Q1 2026 per-fund current-period coverage is at parity with Q4.
Ledger-row comparisons across quarters should normalize for the comparative
layer and filing-season form mix, or compare current-period-only slices.

## 2026-07-24 (part 2) - Per-fact shadow rule-firing comparison, Q4 2025 vs Q1 2026

Question: normalized per fact, does Q1 2026 fire more or fewer shadow rules
than Q4 2025, and do the same rules fire?

Method: scripts/tmp_eda_rule_firings.py (DuckDB over the shadow ledger;
firing = fail-status row). Post-q1shakedown outputs.

Findings:
1. PER-FACT RATE IS LOWER IN Q1: 1.449 fails per 1k units vs 2.505 for Q4
   (-42%); 10.71% vs 12.58% of non-skip checks. Q1 actually checks MORE
   units (645K vs 631K) while failing less.
2. NO NEW FAILURE MODES: zero rules fire in Q1 that did not fire in Q4.
   44 rules fire in both quarters (Q4 1,486 / Q1 935 fails); 17 rules fire
   only in Q4 (94 fails); 64 rules never fail.
3. Of the 17 Q4-only rules, most have NO Q1 targets (html_agg, SRC_BDC02/03,
   C006/C301/C303/C304, blocking_pipeline_only_position, F13) -- lane not
   applicable, not resolved. Genuinely clean in Q1 with live coverage:
   F24 (166 checks), oracle D01/D02 (167), gav_reconciliation (169).
4. RATE MOVERS (same rule, different rate):
   - Improved: F16 95%->20%, A04/E01 45.5%->27.8%, F20 27%->12.4%, F28,
     F22, F25 -- consistent with fresher companyfacts and 10-Q-only mix.
   - Worsened: fv_conservation 18.1%->36.5% and cost_conservation
     12.7%->19.2% (the acceptance-FAIL driver), A07 pct-of-net-assets sum
     39.2%->50.3%, E07 position-count-vs-filing 94.4%->98.6% (near-always
     fails both quarters -- calibration candidate), E02 holdings-FV vs
     total-assets 8.3%->17.2%, F23 computed-vs-reported pct 7.7%->21.3%,
     F27 income-yield vs WAC 3.6%->22.5%.
5. Structural 100%-fail rules (X04/X06, SRC_BDC01, source_recon
   parser-mismatch blockers) fire at 100% whenever they have targets in
   both quarters -- they are queue feeds, not rate signals.

Implication: Q1 is cleaner per fact with an identical failure surface;
remediation should target the conservation pair + A07/E02 cluster (all
consistent with anchor/denominator issues on unremediated Q1 frames), and
E07's near-100% fail rate needs threshold review before it means anything.

