# Template Fix Agent Prompt (v1.1)

## Your Task

Fix a v3.0 template for CIK **{CIK}** that is failing validation. The template exists at `data/raw/filing_templates/{CIK}.json` and has auto-detected table selections for most filings, but needs targeted fixes to pass validation.

**You must fix ALL issues or justify them as unfixable. Do not stop at the first fix -- iterate until validation passes.**

## Quick Start

```bash
# 1. Run validation to see current state
python scripts/learn_template.py --validate {CIK}

# 2. Read fail_reasons and diagnose

# 3. Fix the template JSON (targeted changes only)

# 4. Re-validate (REQUIRED -- iterate until PASS or justified FAIL)
python scripts/learn_template.py --validate {CIK}
```

## Critical Rules

- Do NOT modify pipeline source code (`pipeline/html_extract.py`, `pipeline/validate_html_template.py`, `scripts/learn_template.py`)
- Do NOT download files manually -- HTML filings are cached at `data/raw/filings/bdc_html/{CIK}/`
- Do NOT rewrite the template from scratch -- make targeted fixes
- Do NOT delete filings from the template -- fix or revert to `"tables": []`
- **MUST** re-validate after every change. Iterate until PASS.

---

## Failure Types and Fixes

### 1. count_instability (QoQ position count jumps >50%)

**Common causes:**
- 10-K or 10-Q filings include BOTH current and comparative period SOI tables without `table_periods` (doubles position count)
- Auto-filled filings selected wrong tables (different number of positions than adjacent quarters)
- Format change between filing eras (different column layouts extract different row counts)

**Fix priority:** Add `table_periods` first (fixes both count and self-ref simultaneously). If count jumps remain after period tagging, they're structural (format boundary effect) -- justify with `--accept`.

### 2. self_ref_high (ratio > 1.15x) or self_ref_fail

**Cause:** Comparative period tables are included without `table_periods`, doubling the FV sum vs the subtotal. OR subtotals are not being detected properly, causing the self-referential check to use wrong denominators.

**Fix:** Add `table_periods` to split current vs prior period tables. See "Adding table_periods" section. For subtotal detection issues, see "Subtotal Detection" section.

### 3. fv_fill_low (< 30%)

**Cause:** The `fair_value` column mapping points to the wrong grid position for some filings. Often happens when auto-filled filings have a different column layout than the filings the template was originally designed for.

**Fix:** Either:
- Add per-filing `columns` overrides for the affected accessions
- If the format is completely different and not worth fixing, revert to `"tables": []`
- If >50% of filings have this issue, the global `columns` mapping is wrong

### 4. unit_mismatch

**Cause:** Some filings use a different dollar_unit than the template's global setting.

**Fix:** Add per-filing `"dollar_unit"` overrides.

### 5. agg_fail (companyfacts ratio outside 0.7-1.4x)

**Cause:** Dollar unit mismatch, wrong table selection, or comparative period double-counting.

**Fix:** Usually resolves when other issues (table_periods, dollar_unit) are fixed.

### 6. low_coverage (< 50% of filings extract data)

**Cause:** Many filings have `"tables": []` or table selections that produce no holdings.

**Fix:** Run `--inspect` on empty filings to find correct SOI tables.

---

## Adding table_periods (Most Important Fix)

This is the single most common fix needed. Many filings (both 10-K AND 10-Q) include comparative period tables. Missing `table_periods` causes **both** `count_instability` and `self_ref_high` simultaneously.

### Why this matters

Without `table_periods`, ALL extracted rows get tagged with `report_date`. If a 10-K contains both 2023 and 2022 schedule-of-investments tables, you get 2x the positions (count jump) and 2x the FV (ratio ~2.0x). The self-referential check compares the doubled FV sum against the current-period subtotal and fails.

### How to find the period boundary

```bash
# Option 1: Inspect filing tables
python scripts/learn_template.py --inspect {CIK} --filing <ACCESSION>

# Option 2: Read grids directly
# data/raw/filings/bdc_html/{CIK}/<ACCESSION_NODASHES>.grids.json
```

Look for **date text** in the first 1-3 rows of tables within the `tables` range:
- "As of March 31, 2023"
- "Schedule of Investments -- December 31, 2022"
- "September 30, 2022"
- "Consolidated Schedule of Investments (continued) -- June 30, 2021"

Tables before the date change = current period. Tables after = prior period.

**Common patterns for identifying the boundary:**
1. **Large index gap**: A gap of 5+ between consecutive table indices often marks the period boundary
2. **Date text in row 0**: The first row of a continuation table often has the period date
3. **Repeat of header row**: The same column headers repeat at the boundary
4. **Roughly equal table counts**: 10-K typically has ~N tables for current period and ~N for prior period

### How to add table_periods

```json
"0001234567-23-001234": {
  "tables": [10, 11, 12, 15, 16, 17],
  "table_periods": {
    "2023-03-31": [10, 11, 12],
    "2022-12-31": [15, 16, 17]
  }
}
```

**Rules:**
- Every table in `table_periods` must be in `tables`
- Current period date must match the filing's `report_date` (from `data/output/bdc_filings_index.csv`)
- Prior period date is typically 1 year earlier (10-K) or 1 quarter earlier (10-Q)
- If you can't find the boundary, split at the midpoint or largest gap between consecutive table indices
- BOTH 10-K and 10-Q filings may need `table_periods`

### Batch approach for multiple filings

If many filings need table_periods:
1. Read the filings index: `data/output/bdc_filings_index.csv` -- get `form_type` and `report_date` per accession
2. All **10-K filings almost always** need `table_periods`
3. **10-Q filings**: Check a sample -- if the tables list has roughly 2x the expected count, it includes comparatives
4. For each filing, read the grids JSON and scan the first rows of all tables in the `tables` list for date text
5. Group tables by the date they follow

### Programmatic approach for period detection

```python
import json
from pathlib import Path

cik = "{CIK}"
grids_dir = Path(f"data/raw/filings/bdc_html/{cik}")

# For each filing needing table_periods:
acc_nodashes = "<ACCESSION>".replace("-", "")
grids_path = grids_dir / f"{acc_nodashes}.grids.json"
with open(grids_path) as f:
    grids = json.load(f)

grid_by_idx = {t["index"]: t["grid"] for t in grids}
tables = [10, 11, 12, 15, 16, 17]  # from template

for tidx in tables:
    grid = grid_by_idx.get(tidx)
    if not grid:
        continue
    # Check first 3 rows for date text
    for row_i in range(min(3, len(grid))):
        row_text = " ".join(c for c in grid[row_i] if c.strip())
        if any(m in row_text.lower() for m in ["january", "february", "march", "april", "may", "june",
                                                 "july", "august", "september", "october", "november", "december"]):
            print(f"  Table {tidx} row {row_i}: {row_text[:100]}")
```

---

## Subtotal Detection and Self-Referential Check

The self-referential check compares the **sum of position FVs** (excluding subtotals) against the filing's own **"Total Investments at Fair Value" subtotal row**. If the ratio is outside 0.85-1.15x, the filing fails.

### How the engine identifies subtotals

Rows are classified as subtotals if `investment_identifier` matches:
- Starts with "Total" (e.g., "Total Senior Secured Loans", "Total Investments")
- Contains "Grand Total", "Net Assets", "Investments at Fair Value"
- Starts with "Subtotal"

The engine also detects **per-company subtotals**: rows where the name matches another row that has an `investment_type` but this row doesn't (company-level rollup).

### Common subtotal issues

1. **Subtotals not detected**: If a filer uses unusual subtotal text (e.g., "Total fair value" without "investments"), the engine won't filter it out. The subtotal row gets counted as a position, inflating the FV sum.
   - **Fix**: These are typically caught by the engine's `_SUBTOTAL_START_RE` and `_SUBTOTAL_END_RE` patterns. If you find an undetected subtotal pattern, you can add it to the `is_subtotal` field in per-filing overrides.

2. **No subtotal row in HTML**: Some filers don't include a "Total Investments at Fair Value" row. The self-ref check returns "NO_SUBTOTAL" and falls through to the companyfacts check.
   - **Fix**: This is not fixable by template changes. Justify with `--accept` if the companyfacts ratio is reasonable.

3. **Multiple subtotal rows**: Some filers have both category subtotals ("Total Senior Secured") and a grand total ("Total Investments"). The engine picks the **largest FV value** matching grand total patterns.
   - **This usually works correctly** -- no fix needed.

### Diagnosing self-ref failures

When the validation output shows a filing with self-ref ratio significantly different from 1.0:

1. **Ratio ~2.0x**: Almost certainly missing `table_periods` (comparative double-count)
2. **Ratio 1.15-1.5x**: Some continuation tables are being extracted with wrong period, OR a subtotal row is being counted as a position
3. **Ratio 0.5-0.85x**: Missing continuation tables, or the engine is skipping real positions
4. **Ratio 0.0x or "NO_SUBTOTAL"**: No subtotal row found in the filing

---

## Prior Period / Historical Row Handling

BDC filings often include **two sets** of schedule-of-investments tables:

### 10-K Annual Reports
- **Always** have both current year and prior year SOI
- Example: 2023-12-31 10-K includes Dec 2023 SOI tables AND Dec 2022 SOI tables
- Prior period tables are the **same format** as current (same column layout)
- The prior year tables are the complete prior-year SOI, not a summary

### 10-Q Quarterly Reports
- **Often** include current quarter and prior year-end SOI
- Example: 2023-06-30 10-Q includes Jun 2023 SOI AND Dec 2022 SOI
- The auto-detect continuation grouping often merges both periods into one group (identical width/headers)

### How to determine if a filing has comparatives

1. **Check table count**: If the `tables` list has roughly 2x the number of tables you'd expect for one period, it likely includes comparatives
2. **Check the grids**: Look for date text changes within the `tables` range
3. **Check the validation output**: A self-ref ratio ~2.0x is a strong signal

### What `table_periods` does

The extraction engine extracts ALL rows from ALL tables in the `tables` list. With `table_periods`, it tags each row with the correct period date:

```json
"table_periods": {
  "2023-12-31": [10, 11, 12],    // current period -> period = "2023-12-31"
  "2022-12-31": [15, 16, 17]     // prior period -> period = "2022-12-31"
}
```

Downstream processing filters to `period == report_date`, automatically excluding comparative/historical rows from current-period analytics. This means ALL tables stay in the `tables` list -- you don't remove prior-period tables.

---

## Per-Filing Column Overrides

When filings from different eras have different column layouts:

```json
"filings": {
  "0000950170-22-001234": {
    "tables": [2, 4],
    "columns": {
      "investment_identifier": {"col": 0},
      "fair_value": {"col": 6},
      "cost": {"col": 5}
    }
  }
}
```

Column overrides MERGE with the template's global `columns`. Only specify fields that differ.

### Finding correct column indices

```bash
python scripts/learn_template.py --inspect {CIK} --filing <ACCESSION>
```

This shows table headers with grid positions. Match headers to fields:
- "Fair Value" / "Value" -> `fair_value`
- "Cost" / "Amortized Cost" -> `cost`
- "Principal" / "Par" -> `principal_amount`
- "Maturity" -> `maturity_date`
- "Rate" / "Interest Rate" -> `interest_rate`
- "Company" / "Portfolio Company" / "Issuer" -> `investment_identifier`
- "Type" / "Type of Investment" -> `investment_type`

---

## Reverting Broken Filings

If a filing's extraction is fundamentally broken (wrong tables, no useful data) and fixing it is not worth the effort:

```json
"0001234567-23-001234": {
  "tables": []
}
```

This marks the filing as "no SOI tables available" and the validator skips it.

---

## Accepting Structural Failures

Some failures are structural and not fixable by template changes:

```bash
python scripts/learn_template.py --accept {CIK} --justification "Reason"
```

**Valid justifications:**
- "count_instability at format boundary: filings before 2018 have different column layout, extraction quality is good (self_ref 1.0x, FV fill >50%)"
- "no subtotal rows in HTML -- cannot compute self-referential check. companyfacts ratio 0.98x confirms extraction is accurate"
- "10-K full SOI vs 10-Q partial SOI causes structural count difference"

**Invalid justifications (these are fixable):**
- Wrong tables selected
- Missing continuation tables
- Missing table_periods
- Wrong dollar_unit

---

## Workflow Summary

1. `python scripts/learn_template.py --validate {CIK}` -- understand failures
2. Read fail_reasons and per-filing details carefully
3. **First priority**: Add `table_periods` to ALL filings with comparatives (fixes self_ref_high + count_instability)
4. **Second priority**: Fix column mappings for FV fill issues, or revert broken filings to `"tables": []`
5. **Third priority**: Fix dollar_unit, table selection, or other per-filing issues
6. Re-validate. Iterate until PASS or justified.
7. If structural failures remain, use `--accept` with detailed justification
8. Report: CIK, entity name, what was wrong, what you fixed, final status.

## Files Reference

| File | Purpose |
|---|---|
| `scripts/learn_template.py` | Runner: --validate, --inspect, --accept |
| `pipeline/html_extract.py` | v3.0 extraction engine (DO NOT MODIFY) |
| `pipeline/validate_html_template.py` | Validation checks (DO NOT MODIFY) |
| `data/raw/filings/bdc_html/{CIK}/` | Cached HTML filings |
| `data/raw/filings/bdc_html/{CIK}/*.grids.json` | Table grids for inspection |
| `data/raw/filing_templates/{CIK}.json` | Template to edit |
| `data/output/bdc_filings_index.csv` | Filing metadata (form_type, report_date) |
| `data/output/bdc_holdings.csv` | XBRL ground truth for comparison |
