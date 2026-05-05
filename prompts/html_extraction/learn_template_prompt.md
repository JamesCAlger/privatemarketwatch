# Template Validation Prompt for Claude Code Instances (v3.0)

## Your Task

Validate and fix a pre-generated v3.0 JSON template for a specific BDC (Business Development Company) CIK. The auto-detect pipeline has already:

1. Scored every table in every filing for SOI (schedule of investments) likelihood
2. Selected the best tables per filing and grouped continuation tables
3. Auto-mapped columns from header text
4. Detected dollar_unit from companyfacts
5. Written a draft template + a context file with full diagnostic output

**Your job: verify the draft is correct, fix any issues, and get `--validate` to pass.**

## Files You'll Work With

```
data/raw/filing_templates/<CIK>.json            -- Draft template (edit this)
data/raw/filing_templates/<CIK>.auto_detect.txt  -- Diagnostic context (read-only)
data/raw/filings/bdc_html/<CIK>/*.grids.json     -- Table grids (for debugging)
```

## Context File Section Order

The `.auto_detect.txt` file is organized with **summary sections first, per-filing detail last**:

1. **PATTERN SUMMARY** -- structural patterns with filing counts (Step 1)
2. **COLUMN MAPPING** -- field-to-column assignments (Step 2)
3. **COLUMN VERIFICATION** -- parsed sample values per field (Step 2)
4. **DOLLAR UNIT** -- multiplier with rationale (Step 5)
5. **LOW CONFIDENCE** -- flagged filings needing review (Step 6)
6. **DRAFT TEMPLATE SAVED** -- template location and stats
7. **PER-FILING DETAIL** -- BEFORE/HEADER/DATA/AFTER per filing (Step 3, reference only)

Most validation work uses sections 1-6 only. Section 7 is reference material for investigating specific filings flagged in earlier sections.

## Decision Tree Workflow

Work through these steps **in order**. Each step builds on the previous.

### Step 1: Read the PATTERN SUMMARY (top of context file)

Start at the top of the `.auto_detect.txt` file. The PATTERN SUMMARY groups all filings by their structural signature (table indices + widths + headers).

**What you're looking for:**
- A **dominant pattern** covering 60-80% of 10-Q filings (this should match `default.tables`)
- **10-K patterns** with high table indices (200+) -- these are annual filings
- **Outlier patterns** with 1 filing each -- these need per-filing overrides
- **Suspicious patterns**: `[4]` or `[9]` with width 3 (likely picked wrong table -- exhibits list or TOC)

**Action:** Note which patterns look problematic. You'll verify them in Step 2.

### Step 2: Verify COLUMN VERIFICATION and pre-populated headers

This section shows parsed values from sample data rows for each column mapping.

**2a. Check each field against expected values:**

| Field | Good values | Bad values (fix needed) |
|---|---|---|
| `investment_identifier` | "Acme Corp LLC", "Widget Holdings" | "Purchases of investments", "December 31" |
| `fair_value` / `cost` | "$14,268,960", "$7,362,597" | "Communications", "06/21/2017" |
| `interest_rate` | "11.25" -> 11.25, "9.00" -> 9.0 | "15075" (wrong column), "4/15/2011" (date) |
| `maturity_date` | "06/21/2017" -> 2017-06-21 | "$14,268,960" (dollar amount) |
| `industry` | "Communications", "Retail" | "December 31, 2021" (date) |
| `basis_spread` | "L+975" -> 975.0 | "?" is OK (means no spread) |

**If a width override (w=N) shows wrong data:**
- Remove that entry from `columns_by_width` in the template
- Or fix the column positions using `--inspect <CIK> --all-widths`

**2b. Verify pre-populated `"header"` values:**

Templates are auto-populated with `"header"` patterns on each column spec. These enable the engine to resolve column positions semantically per-table. Verify they are correct:

- **Check that each field's `"header"` pattern matches the actual table header text.** Use the HEADER line in per-filing detail or `--inspect` to see actual header cells. For example, if the template has `"interest_rate": {"col": 12, "header": "interest rate|coupon rate|rate"}`, confirm the SOI table header actually says "Interest Rate" (or similar) at or near that column.
- **Check that `investment_identifier` has a `"header"`.** If the SOI table has a header like "Portfolio Company", "Investments", or "Issuer", the header pattern should match it. If the company column has no header text (common in older filings), a positional `"col": 0` without `"header"` is correct.
- **Remove wrong headers.** If a `"header"` pattern matches text in the wrong table type (e.g., "rate" matching a "Rate of Return" column in a performance summary), remove the `"header"` key from that field spec so it falls back to positional.
- **Missing headers are OK for positional-only fields.** Fields that always appear at the same grid position across all table widths don't need `"header"` -- the positional `"col"` is sufficient.

### Step 3: Spot-check TABLE SELECTION for new structural patterns

For each **unique structural pattern** that got full context (BEFORE/HEADER/DATA/AFTER), verify:

**3a. HEADER should contain SOI keywords:**
- Good: "Issuer Name | Maturity | Industry | Current Coupon | ... | Cost | Fair Value"
- Bad: "Total Return | NAV | Distribution" (wrong table -- performance summary)
- Bad: "Assets | Liabilities | Net Assets" (wrong table -- balance sheet)

**3b. DATA rows should show real investment positions:**
- Good: "Acme Corp LLC | 06/21/2017 | Communications | 11.25 | % | L+975"
- Bad: "Net investment income | $ | 1,234,567" (income statement)
- Bad: "First lien | $ | 308,638,805" (asset class summary, not positions)

**3c. BEFORE tables should NOT be SOI:**
- The 2-3 tables preceding the selection should be financial statements (income stmt, cash flow)
- If BEFORE shows "Portfolio Company | Maturity | Fair Value" -- the SOI starts earlier

**3d. AFTER tables should NOT be SOI:**
- The 2 tables following should be footnotes ("(1) The provisions of the 1940 Act...")
- If AFTER shows company names + dollar values -- the SOI continues beyond the selection

**3e. ALSO SCORED HIGH tables:**
- Same headers as selected tables = comparative period (10-K). Should be in `table_periods`
- "Cost | Fair Value | Cost | Fair Value" = asset class summary (exclude)
- "Industry Classification | Date | Date" = industry breakdown (exclude)
- Different asset class headers (equity, warrants) = possibly missed section (include)

### Step 4: Check for comparative period tables (ALL filing types) -- CRITICAL

**Both 10-K and 10-Q filings can include prior-period schedules of investments.** When comparative SOI tables are present, they must be tagged with `table_periods` so the engine assigns each row the correct period date. Without `table_periods`, all rows get `report_date`, doubling the extracted FV. **This is the #1 cause of validation failures** -- it triggers both `self_ref_high` and `count_instability` simultaneously.

**How comparative tables appear:**
- **10-K**: Two separate groups of SOI tables (current year + prior year). Auto-detect may have already split these via `table_periods` (check the context file for `-> table_periods:` lines). If missing, add manually.
- **10-Q**: Prior-period SOI tables are often adjacent to current-period tables with identical structure (same width, same headers). Auto-detect merges them into a single continuation group and does NOT generate `table_periods`. **You must check every 10-Q filing manually.**

**Detection method:**

1. Check the `tables` list size. If a 10-Q has roughly 2x more tables than expected (compared to other quarters or the number of asset-class sub-schedules), comparative tables are likely merged in.

2. Inspect the grids for date text. Use `--inspect <CIK> --filing <ACC>` and look at tables near the midpoint of the `tables` list. Look for rows containing date text like "As of March 31, 2023", "Schedule of Investments", "December 31, 2022" in the first few rows of a table (before or at the header row). A second date header mid-way through the tables list indicates a period boundary.

3. Alternatively, read the `.grids.json` file directly: `data/raw/filings/bdc_html/<CIK>/<ACC_NODASHES>.grids.json`. Search for date text in row 0 of tables within the `tables` range.

**Fix:** Add `table_periods` to the filing's override in `filings`, mapping each period date to its table indices. The `tables` list should include ALL tables (both periods):

```json
"0001234567-23-001234": {
  "tables": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
  "table_periods": {
    "2023-03-31": [10, 11, 12, 13, 14],
    "2022-12-31": [15, 16, 17, 18, 19]
  }
}
```

The engine extracts all rows but tags each with the correct period date. Downstream processing filters to `period == report_date`, excluding comparative rows.

**Verification:** After adding `table_periods`, the self-referential ratio should drop from ~2.0x to ~1.0x for that filing.

### Step 5: Check DOLLAR UNIT

In the summary section of the context file:
```
DOLLAR UNIT: 1 (companyfacts ratio: 4.96x ...)
```

**Interpret the ratio:**

| Ratio | Meaning | Fix |
|---|---|---|
| 0.8-1.2x | Correct | No action |
| ~1000x | dollar_unit should be 1000 | Change in template |
| ~0.001x | dollar_unit should be 1000000 | Change in template |
| ~4-5x | Likely includes comparative periods inflating sum | Check table_periods for ALL filing types (Step 4) |
| N/A | No companyfacts data available | Rely on self-referential check in validation |

### Step 6: Check LOW CONFIDENCE filings

Listed in the summary section of the context file (before the per-filing detail). These filings had low scores or no SOI tables found.

**Common causes:**
- 10-K/A amendments with only exhibits (no financial statements) -- OK to have `"tables": []`
- Filings where the SOI is in a different format -- needs `--inspect` to find correct tables
- Very early filings with unusual HTML structure -- may need per-filing override

### Step 7: Fix the template

Based on your findings, edit `data/raw/filing_templates/<CIK>.json`:

| Problem | Fix |
|---------|-----|
| Wrong default tables | Update `default.tables` |
| Wrong columns | Update `columns` mapping |
| Dollar unit wrong | Update `dollar_unit` |
| Header row wrong | Update `default.header_row` |
| Specific filing has different tables | Add `filings.<accession>.tables` |
| Specific filing has different columns | Add `filings.<accession>.columns` |
| 10-K missing table_periods | Add `filings.<accession>.table_periods` |
| Width override shows bad data | Remove from `columns_by_width` |
| Debt/equity tables share same width, columns collide | Add `"header"` to distinguish fields (e.g., `"interest_rate": {"col": 6, "header": "interest rate"}`) |

### Step 8: Run validation (REQUIRED)

```bash
python scripts/learn_template.py --validate <CIK>
```

**Validation checks (in priority order):**

1. **Position count stability** (GATE): No >50% QoQ jumps. Failure = wrong tables for some filing.
2. **Unit mismatch** (GATE): If companyfacts shows consistent non-unity multiplier, dollar_unit is wrong.
3. **Self-referential subtotal** (GATE): Position FV sum / HTML subtotal row = 0.85-1.15x. Tolerates up to max(1, 10%) failing filings. Failure = missed tables, wrong dollar_unit, or wrong columns.
4. **Companyfacts aggregate** (FALLBACK GATE): HTML FV sum vs SEC balance sheet (0.7-1.4x). Becomes primary gate when self-ref has no data (many NO_SUBTOTAL filings). Catches dollar_unit errors and double-counting.
5. **FV fill rate** (GATE): Median across filings must be >= 30%. Failure = fair_value column mapping is broken.
6. **Extraction coverage** (GATE): >= 50% of filings must extract something. Failure = table selection is wrong for many filings.
7. **Cross-quarter carry rate** (INFORMATIONAL): Median >75% means positions track correctly. Low carry = wrong column mapping causing garbled names.
8. **NO_SUBTOTAL warning**: If most filings lack a subtotal row, self-ref is unreliable. Companyfacts becomes the gate. If both are unavailable, overall = NO_DATA (not PASS).

**Structured fail_reasons:** Validation now prints structured `fail_reasons` and `warn_reasons` after the overall result. Each reason is a short diagnostic string with the specific action needed:
- `count_instability: N QoQ jumps >50%` -- add per-filing table overrides
- `unit_mismatch: dollar_unit likely wrong` -- fix dollar_unit
- `self_ref_high (Nx): likely comparative period double-count -- add table_periods` -- add table_periods
- `self_ref_low (Nx): likely missing continuation tables` -- add table indices
- `fv_fill_low (N%): fair_value column mapping broken` -- fix FV column index
- `low_coverage (N%): M filings extract nothing` -- fix table selection
- `agg_fail: companyfacts ratio Nx outside 0.7-1.4` -- fix dollar_unit or tables
- Warnings: `name_fill_low`, `fv_per_position_low/high` (dollar_unit hint), `negative_fv_high`

Results are persisted to `data/output/html_template_validation_summary.csv` after each run.

### Step 9: Diagnose and fix validation failures

**If position count stability FAILS:**
```
QoQ jumps > 50%: 3
  2016-09-30 -> 2016-12-31: 120 -> 45 (62% change)
```
- Find the filing at the end-date in the context file
- Check if it picked the wrong tables (exhibits list instead of SOI)
- Fix with per-filing `tables` override

**If self-referential ratio FAILS:**
```
ratio=2.05, positions=$600M, subtotal=$293M
```
- ratio > 1.5x: extracting too much (comparative tables counted twice, or including summary tables)
  - Check if ANY filing (10-K or 10-Q) is missing `table_periods` -- see Step 4
  - Check if summary/hierarchy tables are included
- ratio < 0.7x: extracting too little (missing continuation tables)
  - Check AFTER context for SOI data continuing beyond selection
  - Add missing table indices

**If carry rate is low (< 50% for specific pairs):**
- Usually happens at format-change boundaries (e.g., filer switched from w=25 to w=27)
- Check if column mapping extracts names correctly for both widths
- May need per-filing `columns` override for the transitional period

### Step 10: Iterate until validation passes

Re-run `--validate` after each fix. Template is done when overall = PASS.

### Step 11: Accept known-unfixable failures (if applicable)

Some failures are structural and cannot be fixed by template changes:
- **10-K vs 10-Q count instability**: 10-K has full SOI (500+ positions) while 10-Q has a summary (~60). This causes >50% QoQ jumps but extraction is correct for each form type.
- **No subtotal rows**: Filer simply doesn't include "Total Investments" rows. Self-referential check returns NO_SUBTOTAL and companyfacts may not be available either.
- **Dollar unit unverifiable**: companyfacts has no data for this CIK, so unit mismatch detection relies only on self-referential check.

If you've exhausted all template fixes and the remaining failures are structural, use `--accept`:

```bash
python scripts/learn_template.py --accept <CIK> --justification "10-K full SOI vs 10-Q summary causes count instability. FV and carry correct within each form type."
```

This marks the CIK as done with the justification recorded in the validation summary CSV. Only use this after genuinely attempting fixes -- do NOT accept failures caused by wrong table selection, missing continuation tables, or incorrect column mappings.

## Diagnostic Tools

```bash
# Show all distinct SOI table widths with auto-suggested column mappings
python scripts/learn_template.py --inspect <CIK> --all-widths

# List all tables in a specific filing
python scripts/learn_template.py --inspect <CIK> --filing <ACCESSION>

# Inspect a specific table grid
python scripts/learn_template.py --inspect <CIK> --filing <ACCESSION> --table <INDEX> --header-row N

# Read table grids directly (no script needed)
# data/raw/filings/bdc_html/<CIK>/<ACCESSION_NODASHES>.grids.json
```

## v3.0 Template Format Reference

```json
{
  "version": "3.0",
  "cik": "1287750",
  "entity_name": "ARES CAPITAL CORP",
  "dollar_unit": 1000000,
  "columns": {
    "investment_identifier": {"col": 0, "header": "portfolio company|issuer|borrower|investment name|investments"},
    "investment_type": {"col": 2, "header": "type of investment|investment type"},
    "interest_rate": {"col": 3, "header": "interest rate|coupon rate|rate"},
    "reference_rate_type": {"col": 4, "header": "reference rate"},
    "basis_spread": {"col": 5, "header": "spread"},
    "maturity_date": {"col": 7, "header": "maturity"},
    "principal_amount": {"col": 9, "header": "principal|par amount|par value"},
    "cost": {"col": 10, "header": "cost|amortized cost"},
    "fair_value": {"col": 11, "header": "fair value"}
  },
  "default": {
    "tables": [3, 5, 7],
    "header_row": 0
  },
  "columns_by_width": {
    "27": {"fair_value": {"col": 24}}
  },
  "filings": {
    "0000950170-22-001234": {
      "tables": [2, 4],
      "header_row": 1,
      "columns": {"fair_value": {"col": 6}},
      "dollar_unit": 1000,
      "table_periods": {
        "2023-12-31": [2], "2022-12-31": [4]
      }
    }
  }
}
```

### Semantic header matching (`"header"`)

Column specs include a `"header"` key with a case-insensitive substring pattern (pipe-separated for OR). Templates are pre-populated with standard patterns by the auto-detect pipeline:

```json
"interest_rate": {"col": 6, "header": "interest rate|coupon rate|rate"},
"fair_value": {"col": 11, "header": "fair value"},
"shares_held": {"col": 6, "header": "shares|units"}
```

**How it works:** The engine scans each table's header row for a match and uses the discovered column position (overriding `"col"`). If no match is found and the table has other header matches, the field is **skipped** for that table -- preventing cross-type contamination (e.g., reading "Shares" as interest_rate in equity tables).

Continuation tables with no matching headers inherit the previous table's resolved mapping.

Fields without `"header"` always use the positional `"col"` value (backward compatible).

**During validation:** Verify that each pre-populated `"header"` pattern actually matches the SOI table headers for this CIK (see Step 2b). Remove `"header"` from fields where the pattern matches non-SOI content (e.g., "rate" matching "Rate of Return" in a performance table).

### Field types

| Field | Engine behavior |
|---|---|
| `fair_value`, `cost`, `principal_amount` | Extracts number, multiplies by `dollar_unit` |
| `interest_rate`, `basis_spread`, `pik_rate` | Extracts first number from cell |
| `maturity_date` | Normalizes to YYYY-MM-DD |
| `investment_identifier`, `investment_type`, `industry`, `reference_rate_type` | Stores raw text |
| `shares_held`, `pct_of_net_assets` | Extracts number |

### Available column fields

`investment_identifier`, `investment_type`, `industry`, `interest_rate`, `reference_rate_type`, `basis_spread`, `maturity_date`, `principal_amount`, `cost`, `fair_value`, `shares_held`, `pct_of_net_assets`, `pik_rate`

## Critical Rules

- **Do NOT modify pipeline source code.** The engine handles dollar-sign splitting, date conversion, and first-number extraction automatically.
- **Do NOT remove filings from the template because XBRL exists.** Templates must cover ALL filings through Q4 2022, including filings that also have XBRL. The 2022 transitional XBRL is unreliable (many filings have only aggregate category-level tags, not individual positions). HTML extraction is the primary source for this period. Every filing must have working table indices — do not set `"tables": []` for filings that have SOI tables in the HTML.
- **Use `--inspect --all-widths` for column positions.** Do NOT manually count grid positions from raw HTML.
- **Map to the data position, not the header position.** The engine has single-step lookahead for empty cells under headers.
- **`columns_by_width` is keyed by width only.** If the same width appears for both debt and equity tables, choose the more common layout.
- **One template per CIK.** Use `"filings"` for per-accession overrides.
- **Save to** `data/raw/filing_templates/<CIK>.json` where CIK has leading zeros stripped.
- **Never read raw HTML unless absolutely necessary.** The `.grids.json` and `.auto_detect.txt` files contain all information needed.

## Done

Once `--validate` passes, report:
- CIK and entity name
- Filing count
- Any notable issues encountered (format changes, missing filings, unusual structure)
