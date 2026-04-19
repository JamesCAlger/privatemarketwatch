# Template Creation Prompt for Claude Code Instances

## Your Task

Create a JSON template for a specific BDC (Business Development Company) CIK that maps the HTML schedule-of-investments table structure to standardized data fields. The template enables zero-cost programmatic extraction of thousands of pre-XBRL filings.

## Quick Start

```bash
# 1. Claim the next available CIK (downloads ALL filings, scans formats)
python scripts/learn_template.py --next

# 2. Read the format scan output, examine HTML filings, create template
#    (follow steps below)

# 3. Validate your template (REQUIRED -- must pass before declaring done)
python scripts/learn_template.py --validate <CIK>
```

**IMPORTANT: Always use `--next` to get your CIK.** This claims the CIK in a shared file (`data/output/template_claims.json`) so parallel instances don't collide. It downloads ALL pre-XBRL HTML filings and scans every one for column count changes -- you get a complete format history before writing any code. Do NOT pick a CIK manually from `--list` unless explicitly told to.

**How to know which CIKs are done:** `--list` shows completed templates at the bottom and remaining CIKs at the top. A CIK is "done" when `data/raw/filing_templates/<CIK>.json` exists AND validation passes.

## Critical Rules

### Do NOT modify pipeline source code

The extraction engine (`pipeline/html_template.py` and `pipeline/html_holdings.py`) already handles:
- PIK rate parsing (3 formats: pure PIK, partial PIK, PIK-after)
- Dollar-sign cell splitting (`$` in one `<td>`, number in next)
- Colspan expansion and grid alignment
- Continuation table merging (multi-page schedules)
- Drift detection and column shift recovery
- Reference rate + spread parsing (combined or separate columns)
- Section header industry detection
- Subtotal row filtering
- Date format conversion (MM/YYYY, M/D/YYYY, etc.)
- Multi-period segmentation (auto-detects "As of <date>" markers)

**Your job is to write the JSON template only.** The template tells the extraction engine WHERE each field is (column indices) and HOW the filer formats data (dollar unit, rate format, quirks). The engine does the actual parsing.

If you encounter a parsing issue, first check whether it's a template configuration problem (wrong column index, missing quirk flag) before concluding the engine needs a fix. 99% of issues are template configuration. If you genuinely find an engine bug, document it in `filer_quirks.other_notes` and move on -- do NOT modify `pipeline/html_template.py` or `pipeline/html_holdings.py`.

### Other rules
- Do NOT run `python -m pipeline.main` -- only use `scripts/learn_template.py`
- Do NOT download files manually -- `--next` handles all downloads
- After creating and validating one template successfully, stop and report what you did

## Step-by-Step Process

### Step 1: Claim a CIK and Read the Format Scan

Run `python scripts/learn_template.py --next`. This:
- Claims the next unclaimed CIK
- Downloads ALL pre-XBRL HTML filings to `data/raw/filings/bdc_html/<CIK>/`
- Scans every filing's column count and reports format boundaries
- Shows XBRL ground truth availability

Note the CIK number and **read the format scan carefully**. It tells you:

**Single format** (all filings same column count):
```
FORMAT: Single format (7 columns across all 38 filings)
-> Use v1.0 template (single format)
-> Examine earliest + latest filing for the template
```

**Multiple formats** (column count changed over time):
```
FORMAT CHANGES DETECTED: 3 distinct column counts: [6, 7, 12]

Format eras (3 variants):
  2013-03-08 to 2018-05-04: 6 cols (22 filings)  sample: 0001047469-13-002445
  2018-08-03 to 2020-11-06: 7 cols (10 filings)  sample: 0001047469-18-005396
  2021-02-26 to 2022-05-06: 12 cols (6 filings)  sample: 0001558370-21-001943

-> Use v2.0 multi-variant template (3 variants)
-> Examine the 'sample' filing from EACH era
-> See data/raw/filing_templates/1396440.json (Main Street Capital, 3 variants) as a model
```

The format scan does the column-count analysis for you -- you do NOT need to re-scan. Proceed directly to examining the sample filing(s) it identified.

### Step 2: Examine the HTML Filings

For **single-format** CIKs: examine the earliest and latest filing.
For **multi-format** CIKs: examine the **sample filing from each era** listed in the format scan.

For each filing:

1. **Find the schedule-of-investments table** using the programmatic tools:
```python
from pipeline.html_holdings import find_schedule_tables, _build_column_map
html = open(html_file, encoding="utf-8", errors="replace").read()
tables = find_schedule_tables(html)
table = tables[0]  # Primary schedule table
header = table.rows[table.header_row_idx]
```

2. **Examine the header row** -- note which columns contain which fields:
```python
# Show non-empty header cells with their grid indices
for i, cell in enumerate(header):
    if cell.strip():
        print(f"  [{i:2d}] {cell.strip()[:60]}")
```

3. **Check the keyword-based column map** (the automatic fallback):
```python
col_map = _build_column_map(header)
print(f"Auto-detected: {col_map}")
```

4. **Examine a few data rows** to understand the format:
```python
for row in table.rows[table.header_row_idx + 1 : table.header_row_idx + 6]:
    non_empty = [(i, c) for i, c in enumerate(row) if c.strip()]
    for i, c in non_empty:
        print(f"  [{i:2d}] {c.strip()[:60]}")
    print()
```

5. **Note the dollar unit**: `table.dollar_unit` (1, 1000, or 1000000)

6. **Note rate format**: Are rates like "10.5%" (percentage) or "0.105" (decimal)?

7. **Note date format**: "MM/DD/YYYY", "M/D/YY", "YYYY-MM-DD", etc.

8. **Check for embedded data**: Does the rate cell include reference rate? (e.g., "S+5.25% / 10.50%"). Does the company cell include instrument type on a second line?

### Step 3: Load XBRL Ground Truth (if available)

```python
import pandas as pd
bdc = pd.read_csv("data/output/bdc_holdings.csv", dtype={"cik": str})
xbrl = bdc[bdc["cik"].str.lstrip("0") == "<CIK>"]

# Get latest current-period data
latest = xbrl[xbrl["period"] == xbrl["report_date"]]["report_date"].max()
xbrl_latest = xbrl[(xbrl["report_date"] == latest) & (xbrl["period"] == latest)]
print(f"XBRL: {len(xbrl_latest)} holdings, FV=${xbrl_latest['fair_value'].astype(float).sum()/1e6:,.0f}M")

# Sample a few for spot-checking
xbrl_latest[["investment_identifier", "fair_value", "interest_rate", "maturity_date"]].head(10)
```

### Step 4: Create the Template JSON

Save to `data/raw/filing_templates/<CIK>.json`.

**Single format (stable across filings) -- v1.0:**

If the format scan showed a single format, use v1.0:

```json
{
  "schema_version": "1.0",
  "cik": "<CIK>",
  "entity_name": "<Entity Name>",
  "source_filings": ["<accession_1>", "<accession_2>"],
  "created_by": "claude_code",
  "created_at": "<ISO timestamp>",

  "column_mapping": {
    "company":          {"index": <N>, "header_text": "<exact header text>"},
    "instrument_description": {"index": <N or null>, "header_text": "<header or empty>", "source": "<column | company_cell_line_2>"},
    "industry":         {"source": "<section_header | column | none>"},
    "interest_rate":    {"index": <N>, "header_text": "<header>"},
    "reference_rate":   {"index": <N or null>, "header_text": "<header or empty>"},
    "basis_spread":     {"index": <N or null>, "header_text": "<header or empty>"},
    "pik_rate":         {"index": <N or null>, "header_text": "<header or empty>"},
    "maturity_date":    {"index": <N>, "header_text": "<header>"},
    "principal_amount": {"index": <N>, "header_text": "<header>"},
    "cost":             {"index": <N>, "header_text": "<header>"},
    "fair_value":       {"index": <N>, "header_text": "<header>"},
    "shares_held":      {"index": <N or null>, "header_text": "<header or empty>"},
    "pct_of_net_assets": {"index": <N or null>, "header_text": "<header or empty>"}
  },

  "value_formats": { ... },
  "row_conventions": { ... },
  "filer_quirks": { ... },
  "programmatic_analysis": { ... }
}
```

**Multiple formats (changed over time) -- v2.0:**

If the format scan showed multiple eras, use v2.0 with a `variants` array. Each variant is self-contained with its own column_mapping, value_formats, etc. At extraction time, the code tries each variant against the filing's table structure and picks the best match.

**Model template:** Read `data/raw/filing_templates/1396440.json` (Main Street Capital) before creating your v2.0 template. It has 3 variants spanning 2013 (6 cols, embedded rates) to 2022 (12 cols, separate rate columns), showing the correct structure for format evolution. Note how each variant has its own `column_mapping`, `value_formats`, `row_conventions`, `filer_quirks`, and `programmatic_analysis`.

```json
{
  "schema_version": "2.0",
  "cik": "<CIK>",
  "entity_name": "<Entity Name>",
  "source_filings": ["<accession_1>", "<accession_2>"],
  "created_by": "claude_code",
  "created_at": "<ISO timestamp>",

  "variants": [
    {
      "format_id": "<descriptive_id>",
      "description": "<what makes this format distinct>",
      "source_filing": "<accession used for this variant>",

      "column_mapping": {
        "company":          {"index": <N>, "header_text": "<exact header text>"},
        "instrument_description": {"index": <N or null>, "header_text": "<header or empty>", "source": "<column | company_cell_line_2>"},
        "industry":         {"source": "<section_header | column | none>"},
        "interest_rate":    {"index": <N>, "header_text": "<header>"},
        "reference_rate":   {"index": <N or null>, "header_text": "<header or empty>"},
        "basis_spread":     {"index": <N or null>, "header_text": "<header or empty>"},
        "pik_rate":         {"index": <N or null>, "header_text": "<header or empty>"},
        "maturity_date":    {"index": <N>, "header_text": "<header>"},
        "principal_amount": {"index": <N>, "header_text": "<header>"},
        "cost":             {"index": <N>, "header_text": "<header>"},
        "fair_value":       {"index": <N>, "header_text": "<header>"},
        "shares_held":      {"index": <N or null>, "header_text": "<header or empty>"},
        "pct_of_net_assets": {"index": <N or null>, "header_text": "<header or empty>"}
      },

      "value_formats": {
        "dollar_unit": <1 | 1000 | 1000000>,
        "rate_format": "<percentage | decimal>",
        "date_format": "<MM/DD/YYYY | M/D/YYYY | etc>",
        "negative_convention": "<parentheses | minus | both>",
        "dash_means_null": true
      },

      "row_conventions": {
        "continuation_detection": "empty_first_cell",
        "section_header_examples": ["<example section headers>"],
        "industry_source": "<section_header | column | none>"
      },

      "filer_quirks": {
        "multi_line_cells": <true | false>,
        "instrument_in_company_cell": <true | false>,
        "rate_cell_includes_reference": <true | false>,
        "rate_extraction_regex": "<regex pattern or null>",
        "pik_notation": "<description or null>",
        "filter_subtotal_rows": <true | false>,
        "other_notes": "<any filer-specific observations>"
      },

      "programmatic_analysis": {
        "tables_found": <N>,
        "total_data_rows": <N>,
        "column_count": <N>,
        "detected_dollar_unit": <N>,
        "grid_positions": [<list of non-empty column grid indices>]
      }
    },
    { "format_id": "<another_variant>", ... }
  ]
}
```

**When to use v2.0 vs v1.0:**
- Use v2.0 when the format scan shows multiple eras with different column counts.
- Use v1.0 when the format scan shows a single format.
- Order variants with the most common/modern format first (it wins ties).
- Use the `format_id` naming convention: `"<year>_<N>col_<distinguishing_feature>"` (e.g., `"2013_6col_embedded"`, `"2022_12col_split_rate"`).

#### Column Index Convention

**IMPORTANT**: Column indices are **logical** (0-based among non-empty header cells), NOT grid-level. The `grid_positions` array in `programmatic_analysis` maps logical indices to grid indices.

Example: If the grid header is `["", "Company", "", "Rate", "", "FV"]`, the non-empty cells are at grid positions [1, 3, 5], so:
- Logical index 0 = "Company" (grid 1)
- Logical index 1 = "Rate" (grid 3)
- Logical index 2 = "FV" (grid 5)

Use `_get_logical_columns(header)` from `pipeline.html_template` to compute these:

```python
from pipeline.html_template import _get_logical_columns
header = table.rows[table.header_row_idx]
logical_cols = _get_logical_columns(header)
print(f"Grid positions: {logical_cols}")
for i, grid_idx in enumerate(logical_cols):
    print(f"  Logical {i} -> Grid {grid_idx}: '{header[grid_idx].strip()}'")
```

#### Columns Without Headers (`grid_index`)

Some filers (e.g., Golub Capital) place company names at a grid position that has **no header text**. For these columns, use `"grid_index": N` instead of `"index": N` in the column_mapping entry. The `grid_index` specifies a raw grid-level position that is NOT affected by logical-to-grid remapping or drift detection.

Example: If company names appear at grid 3 but grid 3 has no header:
```json
"company": {"grid_index": 3, "header_text": ""}
```

Use `grid_index` ONLY for columns without headers. For columns with headers, always use `index` (logical index). See `data/raw/filing_templates/1476765.json` for a working example.

### Step 5: Test Your Template

Test against ALL filings, not just the ones you examined. The extraction engine should handle every filing with zero drift.

```python
from pipeline.html_template import extract_filing_with_template
from pathlib import Path
import json

# Load your template
with open(f"data/raw/filing_templates/<CIK>.json") as f:
    template = json.load(f)

# Test on ALL HTML filings
html_dir = Path("data/raw/filings/bdc_html") / "<CIK>"
html_files = sorted(html_dir.glob("*.html"))

for html_file in html_files:
    html = open(html_file, encoding="utf-8", errors="replace").read()
    filing_meta = {
        "cik": "<CIK>",
        "entity_name": template.get("entity_name", ""),
        "accession_number": html_file.stem,
        "form_type": "10-K",
        "filing_date": "2024-01-01",
        "report_date": "2023-12-31",
    }
    holdings, stats = extract_filing_with_template(html, filing_meta, template)

    fv_vals = [h["fair_value"] for h in holdings if h.get("fair_value") is not None]
    rate_vals = [h["interest_rate"] for h in holdings if h.get("interest_rate") is not None]

    drift = "DRIFT" if stats["drift_detected"] else "ok"
    variant = stats.get("variant_used", "v1.0")
    print(f"  {html_file.name}: {len(holdings):>4} holdings, "
          f"FV {len(fv_vals)}/{len(holdings)}, "
          f"Rate {len(rate_vals)}/{len(holdings)}, "
          f"drift={drift}, variant={variant}")
```

If any filing shows DRIFT, investigate. Common causes:
- Header text changed due to footnote markers (OK -- drift fallback handles this)
- Column count changed mid-era (you may need to split an era into two variants)
- Filing is an amendment with no schedule table (OK -- will extract 0 holdings)

### Step 6: Validate Against XBRL and Run Validation (REQUIRED)

Run the validation script:
```bash
python scripts/learn_template.py --validate <CIK>
```

This runs two checks:

**Per-filing extraction quality** (top of output):
- FV fill rate: > 95% (must be high -- FV is the critical field)
- Rate fill rate: > 70% (equity positions won't have rates)
- Name fill rate: > 90%
- No drift detected on any filing
- If XBRL ground truth available: FV sum should be in the same ballpark
- For v2.0 templates: verify each variant is selected correctly for its era

**Aggregate validation** (bottom of output -- the hard quality gates):

| Gate | Threshold | What It Means |
|------|-----------|---------------|
| Self-ref subtotal ratio | 0.85 - 1.15 | Position FV sum matches HTML's own subtotal row |
| Median carry rate | >= 0.75 | 75%+ of position names carry forward between quarters |
| No carry < 0.50 | Each pair >= 0.50 | No complete breakdowns between consecutive quarters |
| Position count stability | No >50% QoQ jumps | Position count shouldn't change drastically |
| Companyfacts adj_ratio | 0.8 - 2.5 (informational) | Supplementary check vs SEC balance sheet (2021+ only) |

**The template is NOT done until the aggregate validation passes.** Do not declare success based on per-filing FV fill rates alone -- the aggregate and carry checks catch systemic issues that per-filing stats miss.

**Raw text preservation:** The extraction engine preserves raw cell text in `raw_*` fields (e.g., `raw_interest_rate`, `raw_fair_value`) alongside parsed values. If a rate cell contains "12.96%/0.00%" that `_parse_rate()` cannot handle, the raw text is still preserved for downstream LLM disambiguation. Do NOT add template logic to parse these -- the pipeline handles it.

**Subtotals:** Subtotal rows (e.g., "Total Senior Secured First Lien") are kept in the output with `is_subtotal: true`. They are used for self-referential validation (comparing position FV sum against the HTML's own subtotal). Do NOT try to filter them.

If validation fails, the output tells you which filings are problematic. Fix by adding/adjusting variants for those specific dates, then re-validate.

For quick re-checks after edits:
```bash
python scripts/learn_template.py --validate-only <CIK>
```

## What the Extraction Engine Already Handles

These features are built into `pipeline/html_template.py` and `pipeline/html_holdings.py`. You configure them via template JSON fields -- you do NOT need to modify Python code.

| Feature | How to Configure | Engine Handles |
|---------|-----------------|----------------|
| Dollar-sign split cells | `dollar_sign_split: true` in filer_quirks | Reads "$" td + number td + empty td as one value |
| Combined rate+reference cell | `rate_cell_includes_reference: true` | Parses "S+5.25% / 10.50%" into reference, spread, rate |
| Separate rate columns | Give `reference_rate` and `basis_spread` their own `index` | Reads each column independently |
| PIK rates | Document in `pik_notation` | Auto-detects "X% PIK", "X% (Y% PIK)", "PIK X%" |
| Continuation rows | `continuation_detection: "empty_first_cell"` | Merges multi-line company/instrument text |
| Section header industries | `industry_source: "section_header"` | Detects single-cell rows as industry headers |
| Instrument in company cell | `instrument_in_company_cell: true` | Splits line 2 as instrument_description |
| Company-level subtotals | Automatic `is_subtotal` flag | Marks rows with only cost+FV and no detail fields. NOT filtered -- kept in output for self-referential validation |
| Multi-page tables | Automatic | Groups tables by header similarity, merges |
| Drift/column shifts | Automatic | Detects shifted columns, recovers via fallback |
| Variant selection | Automatic (v2.0) | Tries each variant, picks best by mismatch count + grid overlap |
| Date formats | `date_format` in value_formats | Converts MM/YYYY, M/D/YYYY, M/D/YY, etc. |
| Negative values | `negative_convention` in value_formats | Handles (123), -123, or both |
| Split spread cells | Automatic | Concatenates "SF +" + "5.50 %" across adjacent tds |
| Multi-period segmentation | Automatic | Detects "As of <date>" markers, keeps only report_date segment |
| Company-row-no-financials | `company_row_no_financials: true` | Multi-row positions: name row + detail rows |
| Narrow row continuation | `narrow_row_continuation: true` + `expected_row_width` | Detects continuation by row width |

## Common Pitfalls

### Dollar unit wrong
The auto-detected `dollar_unit` may be wrong. Override in `value_formats.dollar_unit`. Check:
- Look for "(in thousands)" or "(in millions)" near the schedule heading
- Compare extracted FV sum against XBRL ground truth
- If FV sum is ~1000x too large or small, adjust dollar_unit

### All-grid_index layout
When ALL fields use `grid_index` instead of `index`+`header_text`, drift detection returns real=(0,0,0) for every table and the engine picks the first table meeting data_row_count>=15 -- which may be a summary table. **Always include at least one financial field (fair_value is best) with `index`+`header_text`** to drive drift-based table rejection.

### format_id vs variant_id
Templates MUST use `format_id` (not `variant_id`) in each variant dict. Using `variant_id` silently results in stats['variant_id']=None, making debugging difficult.

### Colspan offset issues
SEC HTML sometimes uses `colspan=2` headers but `colspan=1` data cells. The engine handles this with empty-cell look-ahead. If values are consistently shifted by 1 column, adjust logical indices.

### Format changes between filings
The format scan already identified era boundaries. Create one variant per era. Use the sample filing accession from the format scan output as `source_filing` for each variant.

## Reference Templates

Study these before creating yours:

| Template | Schema | Variants | Key Feature |
|----------|--------|----------|-------------|
| `1287750.json` (Ares Capital) | v1.0 | 1 | Separate reference+spread columns, subtotal filtering |
| `1396440.json` (Main Street Capital) | v2.0 | 3 | **Model for multi-variant**: 6->7->12 col evolution, embedded->split rate |
| `1476765.json` (Golub Capital) | v2.0 | 2 | `grid_index` for headerless company column |
| `1803498.json` (Blackstone PCF) | v1.0 | 1 | Combined rate+spread column, dual-purpose par/shares |
| `1287032.json` (Prospect Capital) | v2.0 | 2 | Narrow continuation rows, `expected_row_width` |

For v2.0 templates, **always read `1396440.json` first** -- it is the canonical example of how to structure format variants.

## Files Reference

| File | Purpose |
|---|---|
| `scripts/learn_template.py` | Runner: --next, --list, --prepare, --validate, --validate-only, --progress |
| `pipeline/html_holdings.py` | Engine: find_schedule_tables, _build_column_map (DO NOT MODIFY) |
| `pipeline/html_template.py` | Engine: extract_filing_with_template, _get_logical_columns (DO NOT MODIFY) |
| `pipeline/validate_html_template.py` | Validation: aggregate FV + carry rate checks (DO NOT MODIFY) |
| `data/raw/filings/bdc_html/<CIK>/` | Cached HTML filings (auto-downloaded by --next) |
| `data/raw/filing_templates/<CIK>.json` | Output template files |
| `data/output/bdc_holdings.csv` | XBRL ground truth |
| `data/output/bdc_filings_index.csv` | Filing metadata index |
| `data/output/html_template_validation.csv` | Validation results per-filing per-CIK |
