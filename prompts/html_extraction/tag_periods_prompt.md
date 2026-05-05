# Period Tagging & Revalidation Prompt (v1.0)

## Your Task

Add `table_periods` annotations to an existing v3.0 template that already passes basic extraction but fails validation due to comparative period double-counting. This is a **lightweight, focused task** -- you are NOT reworking column mappings, dollar_unit, or table selection. You are ONLY tagging which tables belong to which reporting period.

**Scope:** Add `table_periods` to filings that include both current and prior-period SOI tables, then re-validate.

## Quick Start

```bash
# 1. Run validation to see current state
python scripts/learn_template.py --validate <CIK>

# 2. Check fail_reasons -- this prompt applies when you see:
#    - self_ref_high (Nx): comparative period double-count
#    - count_instability: N QoQ jumps >50%

# 3. For each filing needing table_periods, inspect the tables
python scripts/learn_template.py --inspect <CIK> --filing <ACCESSION>

# 4. Edit the template JSON to add table_periods

# 5. Re-validate (REQUIRED)
python scripts/learn_template.py --validate <CIK>
```

## Critical Rules

- Do NOT modify pipeline source code (`pipeline/html_extract.py`, `pipeline/validate_html_template.py`)
- Do NOT change column mappings, dollar_unit, or table selection -- only add `table_periods`
- Do NOT rewrite the template from scratch
- If the CIK has failures BEYOND period tagging (fv_fill_low, low_coverage, unit_mismatch), stop and report -- this prompt does not cover those issues

---

## What is `table_periods`?

Many BDC filings (both 10-K and 10-Q) include schedule-of-investments tables for **two periods**: the current reporting period and a prior comparative period. Without `table_periods`, the engine tags ALL extracted rows with `report_date`, effectively double-counting the portfolio.

`table_periods` tells the engine which tables belong to which period:

```json
"0001234567-23-001234": {
  "tables": [10, 11, 12, 15, 16, 17],
  "table_periods": {
    "2023-03-31": [10, 11, 12],
    "2022-12-31": [15, 16, 17]
  }
}
```

The engine extracts all rows but tags each with the correct period date. Downstream processing filters to `period == report_date`, excluding comparative rows.

## Step 1: Identify which filings need `table_periods`

Run validation and look at the per-filing output:

```bash
python scripts/learn_template.py --validate <CIK>
```

**Filings that need `table_periods`** typically show:
- Self-referential ratio ~2.0x (position FV is double the subtotal)
- Holdings count ~2x higher than adjacent quarters
- The filing is 10-K (annual, almost always has comparative) or 10-Q (quarterly, sometimes has comparative)

**Also check:** `--validate` output shows `self_ref_high` or `count_instability` in `fail_reasons`. These are the two symptoms of missing `table_periods`.

## Step 2: Find the period boundary in each filing

For each filing that needs tagging:

```bash
python scripts/learn_template.py --inspect <CIK> --filing <ACCESSION>
```

This shows all tables with their first few rows. Look for:

1. **Date headings** in row 0 or row 1 of tables: "As of March 31, 2023", "Schedule of Investments -- December 31, 2022", "September 30, 2022"
2. **The boundary** is where the date changes. Tables before the boundary are the current period; tables after are the prior period.

**Alternative:** Read the `.grids.json` file directly:
```
data/raw/filings/bdc_html/<CIK>/<ACCESSION_NODASHES>.grids.json
```

Search for date text in the first row of tables within the `tables` range.

### Common patterns

- **10-K**: Current year SOI at lower table indices, prior year at higher indices. Clear date headers.
- **10-Q with comparatives**: Auto-detect merges both periods into one continuation group (identical width/headers). The midpoint of the `tables` list is often the boundary.
- **10-Q without comparatives**: Only current period tables. No `table_periods` needed.

## Step 3: Add `table_periods` to the template

Edit `data/raw/filing_templates/<CIK>.json`. For each filing needing period tags:

```json
"filings": {
  "0001234567-23-006789": {
    "tables": [20, 21, 22, 23, 24, 25, 26, 27],
    "table_periods": {
      "2023-06-30": [20, 21, 22, 23],
      "2023-03-31": [24, 25, 26, 27]
    }
  }
}
```

**Rules:**
- Every table index in `table_periods` must also be in `tables`
- Every table in `tables` should appear in exactly one period group
- The current period date should match the filing's `report_date`
- The prior period date should be one quarter (10-Q) or one year (10-K) earlier
- If a filing already has a `tables` override but no `table_periods`, just add `table_periods` alongside it
- If a filing uses `default.tables`, you must add a per-filing override with both `tables` and `table_periods`

## Step 4: Validate (REQUIRED)

```bash
python scripts/learn_template.py --validate <CIK>
```

After adding `table_periods`:
- `self_ref_high` should resolve (ratio drops from ~2.0x to ~1.0x)
- `count_instability` should resolve (QoQ jumps eliminated)
- Overall should flip from FAIL to PASS

**If validation still fails** with period-related issues, you likely:
- Missed a filing that also has comparatives
- Got the period boundary wrong (split tables at the wrong point)
- Assigned wrong dates to the period groups

**If validation fails with NON-period issues** (fv_fill_low, unit_mismatch, low_coverage, agg_fail), stop and report -- those require the full rework prompt (`prompts/html_extraction/rework_template_prompt.md`).

## Step 5: Accept structural failures (if applicable)

If `count_instability` persists because 10-K has genuinely more positions than 10-Q (full SOI vs summary), and all period tagging is correct:

```bash
python scripts/learn_template.py --accept <CIK> --justification "10-K full SOI vs 10-Q summary causes count instability. table_periods correctly tagged for all filings with comparatives."
```

## Done

Once `--validate` passes (or `--accept` for structural issues), stop and report:
- CIK and entity name
- How many filings got `table_periods` added
- Whether it passed or was accepted with justification

## Files Reference

| File | Purpose |
|---|---|
| `scripts/learn_template.py` | Runner: --validate, --inspect, --accept |
| `pipeline/html_extract.py` | v3.0 extraction engine (DO NOT MODIFY) |
| `pipeline/validate_html_template.py` | Validation checks (DO NOT MODIFY) |
| `data/raw/filings/bdc_html/<CIK>/` | Cached HTML filings |
| `data/raw/filings/bdc_html/<CIK>/*.grids.json` | Table grids for inspection |
| `data/raw/filing_templates/<CIK>.json` | Template to edit |
| `data/output/html_template_validation_summary.csv` | Validation results |
