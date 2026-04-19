# Template Rework Prompt for Claude Code Instances

## Your Task

Fix an existing JSON template for a specific BDC CIK that failed validation. The template already exists at `data/raw/filing_templates/<CIK>.json` and handles most filings, but has specific issues causing it to fail the aggregate FV and/or cross-quarter carry rate checks.

**Do NOT start from scratch.** The existing template already handles most filings correctly. Your job is to diagnose what's broken, fix the specific issues, and get the template to pass validation.

## Quick Start

```bash
# 1. Diagnose: understand what's broken (follow Step 1 below)
python scripts/learn_template.py --validate-only <CIK>

# 2. Examine the problematic filings (follow Steps 2-3 below)

# 3. Fix the template JSON (follow Step 4 below)

# 4. Validate (REQUIRED -- must pass before declaring done)
python scripts/learn_template.py --validate <CIK>
```

## Critical Rules

### Do NOT modify pipeline source code

The extraction engine (`pipeline/html_template.py` and `pipeline/html_holdings.py`) is stable and tested. Do NOT modify these files. Your job is to fix the JSON template configuration only.

### Other rules
- Do NOT run `python -m pipeline.main` -- only use `scripts/learn_template.py`
- Do NOT download files manually -- HTML filings are already cached at `data/raw/filings/bdc_html/<CIK>/`
- Do NOT rewrite the template from scratch -- make targeted fixes to the existing template
- After fixing one template successfully (validation passes), stop and report what you did
- If the template genuinely cannot pass validation with template-only changes, document why in `filer_quirks.other_notes` and report back

---

## Step 1: Diagnose from the Validation Data

First, run the quick validation to see the current state:

```bash
python scripts/learn_template.py --validate-only <CIK>
```

Then load the validation CSV for detailed per-filing data:

```python
import pandas as pd

cik = "<CIK>"
val = pd.read_csv("data/output/html_template_validation.csv", dtype={"cik": str})
cik_data = val[val["cik"] == cik]

# 1. Self-referential subtotal check -- position FV sum vs HTML's own subtotal
sr = cik_data[cik_data["self_ref_status"].isin(["PASS", "FAIL"])]
if len(sr) > 0:
    print(f"Self-ref median ratio: {sr['self_ref_ratio'].median():.2f}x")
    print(f"  (1.0x = perfect, 0.85-1.15 = acceptable)")
    sr_fails = sr[sr["self_ref_status"] == "FAIL"]
    if len(sr_fails) > 0:
        print(f"\nFailing filings ({len(sr_fails)}):")
        for _, r in sr_fails.iterrows():
            print(f"  {r['report_date']} ({r['form_type']}): "
                  f"ratio={r['self_ref_ratio']:.2f}x, variant={r['variant_used']}, "
                  f"positions=${r['self_ref_position_fv']/1e6:.0f}M, "
                  f"subtotal=${r['self_ref_subtotal_fv']/1e6:.0f}M")
else:
    print("No subtotals found in extraction -- self-ref check unavailable")

# 1b. Companyfacts (supplementary, 2021+ only)
agg = cik_data[cik_data["adj_ratio"].notna()]
if len(agg) > 0:
    print(f"\nCompanyfacts adj_ratio (supplementary): {agg['adj_ratio'].median():.2f}x")

# 2. Carry rates -- do position names carry across quarters?
carry = cik_data[cik_data["carry_rate"].notna()]
if len(carry) > 0:
    print(f"\nMedian carry: {carry['carry_rate'].median():.0%}")
    low = carry[carry["carry_rate"] < 0.50]
    if len(low) > 0:
        print(f"\nLow carry transitions ({len(low)}):")
        for _, r in low.iterrows():
            print(f"  {r['report_date']}: carry={r['carry_rate']:.0%}, variant={r['variant_used']}")

# 3. Drift
drifted = cik_data[cik_data["drift_detected"] == True]
if len(drifted) > 0:
    print(f"\nDrift on {len(drifted)} filings:")
    for _, r in drifted.iterrows():
        print(f"  {r['report_date']}: variant={r['variant_used']}")

# 4. Variant distribution -- which variants are used when?
print(f"\nVariant usage:")
print(cik_data.groupby("variant_used").agg(
    count=("report_date", "len"),
    dates=("report_date", lambda x: f"{x.min()} to {x.max()}")
).to_string())
```

## Step 2: Identify the Failure Type

Based on the diagnosis, your template has one or more of these issues:

### Issue A: adj_ratio > 2.5x (extracting too much FV)

**Root causes (in order of likelihood):**

1. **Comparative periods not separated.** Many BDC filings include BOTH current-period and prior-period schedules in a single HTML table. The engine auto-segments when it finds "As of <date>" markers, but many filers have no such markers. If the ratio is consistently ~2x, this is the cause.
   - **Diagnosis:** Check if `html_fv_sum` is roughly 2x `cf_fv` across all filings. If so, comparative periods are being included.
   - **Fix options:** (a) Check the HTML for ANY date-separator pattern the engine might not detect. (b) If no separators exist, a ~2x ratio is structural and may be acceptable -- focus on carry rate instead. (c) If the filer uses non-standard date markers, document in `filer_quirks.other_notes`.

2. **Wrong table selected.** The engine picked a summary table, FV-hierarchy table, or footnotes table instead of the schedule-of-investments.
   - **Diagnosis:** Open a failing filing and check what tables are found. If the wrong table has more data rows, the engine will prefer it.
   - **Fix:** Adjust `header_text` values in column_mapping so drift detection rejects the wrong table. Ensure at least one field (preferably `fair_value`) uses `index` + `header_text` (NOT `grid_index`).

3. **Dollar unit too low.** Template says `dollar_unit: 1` but filer reports in thousands.
   - **Diagnosis:** FV sum is 1000x expected.
   - **Fix:** Set `value_formats.dollar_unit: 1000`.

### Issue B: adj_ratio < 0.5x (extracting too little FV)

**Root causes:**

1. **Missing continuation tables.** Multi-page schedules not merging. The engine groups tables by header similarity, but continuation pages with different/no headers get dropped.
   - **Diagnosis:** Compare extracted position count vs expected from the HTML.
   - **Fix:** Check if continuation tables exist and why they're not merging.

2. **Wrong table selected.** Engine picked a small summary table.
   - **Fix:** Same as Issue A.2 above.

3. **Dollar unit too high.** Template says `dollar_unit: 1000` but filer reports in actual dollars.
   - **Fix:** Set correct `value_formats.dollar_unit`.

4. **Variant mismatch.** Wrong variant selected for some filings, extracting from misaligned columns.
   - **Diagnosis:** Check variant_used column in validation CSV vs expected.
   - **Fix:** Adjust `column_count` in `programmatic_analysis` or add more distinguishing `header_text` values.

### Issue C: Low carry rate (< 75% median or < 50% on specific transitions)

**Root causes:**

1. **Format transition between variants.** Filings before and after a low-carry transition use different variants that extract company names differently (e.g., one includes industry prefix, the other doesn't).
   - **Diagnosis:** Check which variant is used on each side of a low-carry pair. If different variants, the name extraction is inconsistent.
   - **Fix:** Ensure the `company` column mapping in each variant extracts the same content (just the company name, not industry/instrument prefixes).

2. **Missing variant.** Some filings match no variant well and fall through to a poor match, extracting garbage names.
   - **Diagnosis:** Look for filings with very low position counts or 0% FV fill around low-carry dates.
   - **Fix:** Add a new variant for the unmatched format.

3. **Wrong variant boundary.** A variant is being selected for filings outside its intended era.
   - **Diagnosis:** Check variant_used vs expected for filings around low-carry dates.
   - **Fix:** Adjust `column_count` or `header_text` to make variant selection more precise.

### Issue D: Drift detected

1. **Minor header changes** (footnote markers, rewording): Usually benign, engine recovers via fallback. No fix needed.
2. **Column count changed within an era**: Need to split into sub-variants.
3. **Wrong variant selected**: Adjust variant discrimination.

## Step 3: Examine Problematic Filings

For each failing filing from Step 1, examine the HTML:

```python
from pipeline.html_holdings import find_schedule_tables
from pipeline.html_template import extract_filing_with_template, _get_logical_columns
from pathlib import Path
import json

cik = "<CIK>"
with open(f"data/raw/filing_templates/{cik}.json") as f:
    template = json.load(f)

html_dir = Path("data/raw/filings/bdc_html") / cik

# Pick a failing filing -- use the accession number from the validation CSV
# Filings are named by accession: <accession>.html
html_file = html_dir / "<accession>.html"
html = open(html_file, encoding="utf-8", errors="replace").read()

# 1. Check what tables the engine finds
tables = find_schedule_tables(html)
print(f"Tables found: {len(tables)}")
for i, t in enumerate(tables):
    header = t.rows[t.header_row_idx]
    non_empty = [c.strip() for c in header if c.strip()]
    data_rows = len(t.rows) - t.header_row_idx - 1
    print(f"  Table {i}: {len(non_empty)} cols, {data_rows} data rows, "
          f"dollar_unit={t.dollar_unit}")
    print(f"    Headers: {non_empty[:8]}")

# 2. Run extraction and see what comes out
filing_meta = {
    "cik": cik,
    "entity_name": template.get("entity_name", ""),
    "accession_number": html_file.stem,
    "form_type": "10-K",
    "filing_date": "2024-01-01",
    "report_date": "<report_date from validation CSV>",
}
holdings, stats = extract_filing_with_template(html, filing_meta, template)
print(f"\nExtracted: {len(holdings)} holdings")
print(f"Variant: {stats.get('variant_used')}")
print(f"Drift: {stats.get('drift_detected')}")
fv_sum = sum(h['fair_value'] for h in holdings if h.get('fair_value'))
print(f"FV sum: ${fv_sum:,.0f}")

# 3. Spot-check a few holdings
for h in holdings[:5]:
    print(f"  {h.get('issuer_name', '?')[:40]:40s}  "
          f"FV={h.get('fair_value', '?'):>12}  "
          f"Rate={h.get('interest_rate', '?')}")
```

To find the accession number for a specific report_date, use the filing index:

```python
import pandas as pd
idx = pd.read_csv("data/output/bdc_filings_index.csv", dtype={"cik": str})
cik_filings = idx[idx["cik"].str.lstrip("0") == cik]
# Show filings around the problematic date
print(cik_filings[["accession_number", "form_type", "filing_date", "report_date"]].to_string())
```

## Step 4: Fix the Template

Based on your diagnosis, make **targeted changes** to `data/raw/filing_templates/<CIK>.json`:

**Common fixes:**

| Problem | Fix |
|---------|-----|
| Dollar unit wrong | Set `value_formats.dollar_unit` to correct value (1, 1000, or 1000000) |
| Wrong table selected | Add/fix `header_text` on financial fields so drift rejects wrong tables |
| Missing variant for a format era | Add a new variant to the `variants` array |
| Variant selected for wrong filings | Adjust `column_count` in `programmatic_analysis` |
| Subtotals in output | Normal -- subtotals are kept with `is_subtotal` flag for self-referential validation |
| Company name extracted inconsistently | Ensure `company` column mapping is consistent across variants |
| Continuation tables not merging | Check continuation detection settings |

**Important:** When adding variants, use the `format_id` naming convention: `"<year>_<N>col_<distinguishing_feature>"`. Each variant must have `format_id` (NOT `variant_id`).

## Step 5: Validate (REQUIRED -- must pass before you are done)

After fixing, you MUST run the full validation command:

```bash
python scripts/learn_template.py --validate <CIK>
```

This command prints TWO sections of output:

1. **Per-filing extraction stats** (top) -- shows holdings count, FV fill rate, variant used per filing. This is informational only. Do NOT stop here.

2. **VALIDATION (aggregate checks)** (bottom, after a `====` separator) -- this is the actual quality gate. It prints:
   - `Self-Referential Subtotal Check` with median ratio and STATUS: PASS/FAIL
   - `Cross-Quarter Carry Rate` with median carry and STATUS: PASS/FAIL
   - `Position Count Stability` with QoQ jump count and STATUS: PASS/FAIL
   - `Aggregate FV (companyfacts, supplementary)` -- informational only (2021+ coverage)
   - `Overall: PASS/FAIL`

**You MUST scroll to the bottom and check the `Overall:` line.** The template is NOT done until it says `Overall: PASS`. Ignore per-filing FV fill rates -- they can be 95%+ while the aggregate validation still fails.

**These gates must show PASS for Overall: PASS:**

| Gate | Threshold | What It Means |
|------|-----------|---------------|
| Self-ref subtotal ratio | 0.85 - 1.15 | Position FV sum matches HTML's own subtotal row |
| Position count stability | No >50% QoQ jumps | Position count shouldn't change drastically between quarters |

**Informational (not gates):**

| Check | What It Means |
|-------|---------------|
| Carry rate | Name consistency across quarters (noisy -- filers change names) |
| Companyfacts aggregate FV | Supplementary 2021+ cross-check |

If validation still fails, iterate: diagnose the remaining failures from the output, fix, re-validate.

For quick re-checks between iterations (shows ONLY the aggregate validation, no per-filing detail):
```bash
python scripts/learn_template.py --validate-only <CIK>
```

**The template is NOT done until `python scripts/learn_template.py --validate <CIK>` shows `Overall: PASS` in the VALIDATION section at the bottom of the output.** When reporting back, include the full VALIDATION section output (everything after the `====` separator).

---

## What the Extraction Engine Already Handles

These features are built into the engine. You configure them via template JSON fields -- do NOT modify Python code.

| Feature | How to Configure |
|---------|-----------------|
| Dollar-sign split cells | `dollar_sign_split: true` in filer_quirks |
| Combined rate+reference cell | `rate_cell_includes_reference: true` |
| PIK rates | Document in `pik_notation` (auto-detected) |
| Continuation rows | `continuation_detection: "empty_first_cell"` |
| Section header industries | `industry_source: "section_header"` |
| Instrument in company cell | `instrument_in_company_cell: true` |
| Subtotal marking | Automatic (`is_subtotal` flag) -- kept in output, not filtered |
| Raw text preservation | Automatic (`raw_*` fields) -- raw cell text preserved for all parsed fields |
| Multi-page table merging | Automatic |
| Drift/column shift recovery | Automatic |
| Variant selection | Automatic (v2.0) |
| Multi-period segmentation | Automatic (detects "As of <date>" markers) |
| Company-row-no-financials | `company_row_no_financials: true` |
| Narrow row continuation | `narrow_row_continuation: true` + `expected_row_width` |

## Reference Templates

Study these for patterns relevant to your fix:

| Template | Key Feature |
|----------|-------------|
| `1396440.json` (Main Street Capital) | Multi-variant model: 3 format eras |
| `1287750.json` (Ares Capital) | Subtotal filtering, separate rate columns |
| `1476765.json` (Golub Capital) | `grid_index` for headerless columns |
| `1803498.json` (Blackstone PCF) | Combined rate+spread, dual-purpose columns |
| `1287032.json` (Prospect Capital) | Narrow continuation rows, `expected_row_width` |

## Files Reference

| File | Purpose |
|---|---|
| `scripts/learn_template.py` | Runner: --validate, --validate-only, --prepare |
| `pipeline/html_holdings.py` | Engine: find_schedule_tables (DO NOT MODIFY) |
| `pipeline/html_template.py` | Engine: extract_filing_with_template (DO NOT MODIFY) |
| `pipeline/validate_html_template.py` | Validation: aggregate FV + carry rate (DO NOT MODIFY) |
| `data/raw/filings/bdc_html/<CIK>/` | Cached HTML filings |
| `data/raw/filing_templates/<CIK>.json` | Template to fix |
| `data/output/bdc_holdings.csv` | XBRL ground truth |
| `data/output/bdc_filings_index.csv` | Filing metadata index |
| `data/output/html_template_validation.csv` | Validation results (your starting diagnostic data) |
