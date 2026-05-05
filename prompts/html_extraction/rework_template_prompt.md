# Template Rework Prompt for Claude Code Instances (v3.0)

## Your Task

Fix an existing v3.0 JSON template for a specific BDC CIK that failed validation. The template already exists at `data/raw/filing_templates/<CIK>.json` and handles most filings, but has specific issues causing extraction failures.

**Do NOT start from scratch.** The existing template already handles most filings correctly. Your job is to diagnose what's broken, fix the specific issues, and get the template to pass validation.

## Quick Start

```bash
# 1. Diagnose: understand what's broken
python scripts/learn_template.py --validate <CIK>

# 2. Examine problematic filings in the HTML cache

# 3. Fix the template JSON

# 4. Re-validate (REQUIRED -- must pass before declaring done)
python scripts/learn_template.py --validate <CIK>

# 5. Process XBRL-era filings (REQUIRED)
python -m pipeline.main --holdings --ciks <CIK>
```

## Critical Rules

- Do NOT modify pipeline source code (`pipeline/html_extract.py`, `pipeline/validate_html_template.py`)
- Do NOT run `python -m pipeline.main` with flags other than `--holdings --ciks <CIK>` (for XBRL)
- Do NOT download files manually -- HTML filings are cached at `data/raw/filings/bdc_html/<CIK>/`
- Do NOT rewrite the template from scratch -- make targeted fixes
- After fixing successfully (validation passes), also run XBRL extraction, then stop and report what you did

---

## Engine Behavior

The v3.0 engine is a dumb table reader. It does NOT parse text:

- **Dollar fields** (`fair_value`, `cost`, `principal_amount`): Extracts the number, multiplies by `dollar_unit`.
- **Rate fields** (`interest_rate`, `basis_spread`, `pik_rate`): Extracts the **first number** from the cell. "10.50% (SOFR + 5.25%)" yields `interest_rate=10.5`. It does NOT extract SOFR or 5.25 into separate fields.
- **Text fields** (`investment_identifier`, `investment_type`, `industry`, `reference_rate_type`): Stores raw text as-is.
- **Date fields** (`maturity_date`): Normalizes to YYYY-MM-DD.

If the filer embeds reference rates, spreads, or PIK in a combined rate cell, the engine stores the raw text in `raw_interest_rate` but only extracts the first number as `interest_rate`. Dedicated columns are needed for separate `reference_rate_type`, `basis_spread`, and `pik_rate` values.

---

## Step 1: Diagnose from Validation Output

Run the full validation:

```bash
python scripts/learn_template.py --validate <CIK>
```

This shows per-filing extraction stats and aggregate validation checks. The output now includes structured **fail_reasons** and **warn_reasons** at the bottom -- start diagnosis there:

- `count_instability` -- wrong tables for some filings, missing continuation tables, or 10-K comparative double-count
- `unit_mismatch` -- dollar_unit is wrong
- `self_ref_high` -- comparative period double-count, add table_periods to BOTH 10-K and 10-Q filings
- `self_ref_low` -- missing continuation tables
- `fv_fill_low` -- fair_value column mapping is broken
- `low_coverage` -- table selection fails for many filings
- `agg_fail` -- dollar_unit or table selection is off
- `name_fill_low` (warn) -- investment_identifier column mapping may be wrong
- `fv_per_position_low/high` (warn) -- dollar_unit hint

**IMPORTANT: `self_ref_high` and `count_instability` often share the same root cause.** 10-K filings (and some 10-Q filings) include both current-period and prior-period SOI tables. Without `table_periods`, all rows get tagged as the current period, doubling the FV and inflating the count. Adding `table_periods` fixes both issues simultaneously. Check EVERY filing in the template -- not just 10-K filings.

Also check the detailed metrics:

- **Holdings count**: Should be reasonable (not 0, not 10,000+)
- **FV sum**: Should match expected range
- **Self-referential ratio**: Position FV sum vs HTML's own subtotal (0.85-1.15x = good)
- **Carry rate**: Name consistency across quarters (>75% median = good)
- **Position count stability**: No >50% QoQ jumps
- **FV fill rate**: Median should be >60%
- **Extraction coverage**: Should be >75%

## Step 2: Identify the Failure Type

### Issue A: Extracting too much FV

**Root causes:**
1. **Comparative period tables missing `table_periods`.** For **both 10-K and 10-Q filings**, current and prior-period SOI tables may be listed in `tables`. They must be tagged with `table_periods` so each group gets the correct period date. Without `table_periods`, all rows get `report_date` as their period, doubling the FV. **10-Q comparatives are especially common** -- auto-detect merges them into the same continuation group because they have identical width and headers, adjacent to current-period tables.
2. **Wrong table selected.** A summary or FV-hierarchy table is listed instead of the schedule of investments.
3. **Dollar unit too low.** Template says `"dollar_unit": 1` but filer reports in thousands.

**Fix:** Add `table_periods` to the filing entry to map table groups to their period dates. To find the period boundary, inspect the `.grids.json` file for date text (e.g., "As of March 31, 2023", "Schedule of Investments", "December 31, 2022") in row 0 of tables within the `tables` range. The boundary is where the date changes. You can also run:
```bash
python scripts/learn_template.py --inspect <CIK> --filing <ACCESSION>
```

**How to add `table_periods`:**
1. Look at the `tables` list for the filing
2. Find which tables belong to the current period and which to the prior period
3. Add `table_periods` mapping each date to its table indices
4. The `tables` list must include ALL tables (both periods)

```json
"0001234567-23-001234": {
  "tables": [10, 11, 12, 15, 16, 17],
  "table_periods": {
    "2023-03-31": [10, 11, 12],
    "2022-12-31": [15, 16, 17]
  }
}
```

### Issue B: Extracting too little FV

**Root causes:**
1. **Missing continuation tables.** Multi-page schedules need ALL table indices listed.
2. **Wrong table selected.** Engine reads a small summary table instead of the full schedule.
3. **Dollar unit too high.** Template says `"dollar_unit": 1000` but filer uses actual dollars.

**Fix:** Add missing table indices to `default.tables` or add filing-specific overrides in `filings`.

### Issue C: Low carry rate (< 75%)

**Root causes:**
1. **Format change between filings.** Some filings have different column layouts, extracting names from the wrong column.
2. **Wrong column mapping for specific filings.** Add per-filing column overrides.
3. **Debt and equity sub-tables share the same width but have different column layouts.** The `columns_by_width` entry maps `interest_rate` to the column that is `shares` in equity tables, producing bad rate values that garble matching.

**Fix:** For cause 1-2, add a `filings` entry with corrected `columns` for the affected accessions. For cause 3, add `"header"` to the colliding fields: `"interest_rate": {"col": 6, "header": "interest rate"}`, `"shares_held": {"col": 6, "header": "shares|units"}`. The engine will only extract `interest_rate` when the header says "Interest Rate" and only extract `shares_held` when the header says "Shares".

### Issue D: Wrong columns / garbled data

**Root causes:**
1. **Column index off by one.** Grid positions miscounted (remember: colspan creates extra empty cells).
2. **Header row wrong.** Template says `header_row: 0` but the real header is row 1.
3. **Debt and equity sub-tables share the same width but have different column layouts.** Positional mapping reads the wrong data for one table type.

**Fix:** For cause 1-2, re-examine the HTML, count grid positions carefully, update `columns` mapping. For cause 3, add `"header"` to the colliding fields so the engine only extracts a field when its header is present in the table.

### Issue E: Wrong `"header"` patterns

Templates come pre-populated with `"header"` patterns on column specs. These enable semantic column resolution per-table. If a `"header"` pattern matches non-SOI content, the engine may extract from the wrong column or skip a field unexpectedly.

**Symptoms:**
- A field that should be populated is NULL across all filings (header pattern doesn't match any SOI table header)
- A field has garbled data (header pattern matched the wrong column in a non-SOI table)
- Extraction works for some filings but not others (header pattern matches in some table layouts but not others)

**Fix:** Compare the `"header"` pattern against the actual SOI table headers (use `--inspect <CIK> --all-widths`). Remove `"header"` if the pattern is wrong (field falls back to positional `"col"`). Update the pattern if the SOI header uses different text.

## Step 3: Examine Problematic Filings

```python
from pipeline.html_extract import extract_filing, load_template, _extract_tables
from pathlib import Path
import json

cik = "<CIK>"
template = load_template(cik)

html_dir = Path("data/raw/filings/bdc_html") / cik
html_file = html_dir / "<accession_nodashes>.html"
html = open(html_file, encoding="utf-8", errors="replace").read()

# 1. See all tables in the filing
tables = _extract_tables(html)
for i, t in enumerate(tables):
    header = t[0] if t else []
    non_empty = [c for c in header if c.strip()]
    print(f"Table {i}: {len(t)} rows, {len(header)} cols, headers: {non_empty[:6]}")

# 2. Run extraction
filing_meta = {
    "cik": cik,
    "entity_name": template.get("entity_name", ""),
    "accession_number": "<accession>",
    "form_type": "10-K",
    "filing_date": "2024-01-01",
    "report_date": "<report_date>",
}
holdings, stats = extract_filing(html, filing_meta, template)
print(f"Extracted: {len(holdings)} holdings")
fv_sum = sum(h['fair_value'] for h in holdings if h.get('fair_value'))
print(f"FV sum: ${fv_sum:,.0f}")

# 3. Spot-check
for h in holdings[:5]:
    print(f"  {h.get('investment_identifier', '?')[:40]:40s}  FV={h.get('fair_value', '?'):>12}")
```

## Step 4: Fix the Template

Based on your diagnosis, make **targeted changes** to `data/raw/filing_templates/<CIK>.json`:

| Problem | Fix |
|---------|-----|
| Wrong tables | Update `default.tables` list |
| Wrong columns | Update `columns` mapping with correct `col` values |
| Dollar unit wrong | Update `dollar_unit` (1, 1000, or 1000000) |
| Header row wrong | Update `default.header_row` |
| Format changed in specific filing | Add entry in `filings` with overrides |
| Column changed in specific filing | Add `columns` override in that filing's `filings` entry |
| `"header"` pattern matches wrong column | Remove `"header"` from that field (falls back to positional `"col"`) |
| `"header"` pattern missing, field skipped | Add `"header"` with the correct pattern from actual SOI headers |

### Example: Per-filing override

```json
{
  "filings": {
    "0000950170-22-001234": {
      "tables": [2, 4],
      "header_row": 1,
      "columns": {"fair_value": {"col": 6}},
      "dollar_unit": 1000
    }
  }
}
```

## Step 5: Validate (REQUIRED)

```bash
python scripts/learn_template.py --validate <CIK>
```

**The template is NOT done until validation passes.** If it still fails, iterate: diagnose remaining failures, fix, re-validate.

## Step 6: Accept structural failures (if applicable)

If remaining failures are structural (not fixable by template changes), accept with justification:

```bash
python scripts/learn_template.py --accept <CIK> --justification "Reason why this FAIL is acceptable"
```

Valid reasons include: 10-K vs 10-Q count mismatch (structural), no subtotal rows in HTML, companyfacts unavailable. Invalid reasons: wrong tables, missing continuations, broken column mappings (these are fixable).

## Done

Once `--validate` passes (or `--accept` is used for structural failures), the template is complete. Stop and report which CIK you fixed, what was wrong, and what you changed.

## Files Reference

| File | Purpose |
|---|---|
| `scripts/learn_template.py` | Runner: --validate, --prepare, --list |
| `pipeline/html_extract.py` | v3.0 extraction engine (DO NOT MODIFY) |
| `pipeline/validate_html_template.py` | Validation checks (DO NOT MODIFY) |
| `data/raw/filings/bdc_html/<CIK>/` | Cached HTML filings |
| `data/raw/filing_templates/<CIK>.json` | Template to fix |
| `data/output/bdc_holdings.csv` | XBRL ground truth |
| `data/output/bdc_filings_index.csv` | Filing metadata index |
