---
description: Create or update a BDC XBRL wrapper JSON for a CIK
argument-hint: [CIK|next] [profile|create|validate|update]
allowed-tools: Bash Read Write Edit Grep Glob
---

# BDC XBRL Wrapper Skill

Build, validate, or update per-CIK wrapper JSON files that control how the pipeline classifies and extracts structured fields from XBRL investment identifiers.

**Usage:** `/wrapper [CIK|next] [mode]`

Modes: `profile` (default), `create`, `validate`, `update`

If the user does not specify a CIK, choose the next unprocessed CIK from the default FV priority queue below.

---

## Architecture Context

A **wrapper** is a deterministic, versioned configuration mapping one filer's idiosyncratic XBRL identifier layout into clean structured records. The two-speed split is non-negotiable:

- **Hot path (per row):** deterministic, frozen, fully traceable. No LLM.
- **Edge (per new CIK or drift):** agent generates or repairs a wrapper, gated by deterministic verifiers.

Wrappers live at `data/overrides/bdc_xbrl_wrappers/{CIK}.json` and conform to `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.

There is **one wrapper per CIK** (no per-quarter versioning). Format drift across quarters is handled by broadening prefix rules, adding fallback patterns, or adding identifier parser config.

### Success contract

Schema validation and unit examples are necessary, but not sufficient:

- **Schema validation passes** means the JSON is syntactically valid.
- **Wrapper classifier tests pass** means sampled identifiers classify as intended.
- **Promotion gate passes against final unified holdings** means the wrapper is production-clean.
- **J01 position key stability >= 70% B1b** means the wrapper's position keys are stable across quarters.
- **J03 fuzzy fallback rate <= 10%** means position keys aren't falling through to expensive fuzzy matching.
- **Raw oracle failures remain visible** even when an accepted soft-gate exception changes the effective promotion verdict.
- **Oracle fails** means the wrapper is partial unless residuals are explicitly documented, accepted, and only affect waiveable soft gates.

Do not describe a wrapper as complete because visual samples look plausible. The source-to-final-unified reconciliation and position matching quality checks are the promotion gates.

### Dispatch vs staging vs parser

The wrapper sections affect different parts of the pipeline:

- **`dispatch`** classifies source identifiers for reconciliation diagnostics. A dispatch-only wrapper may reduce ambiguity but may not improve final extraction.
- **`identifier_parser`** drives structured field extraction for identifiers that encode country, industry, issuer, instrument, rate, or maturity.
- **`staging`** handles custom extraction when generic parser logic is not enough.

If identifiers encode structured fields and final extraction depends on them, add `identifier_parser` or `staging` config unless generic staging has already been proven sufficient. Confirm from logs or loader output that the target CIK's parser/staging config is actually loaded; do not assume a similar CIK's parser applies.

---

## Step 0: Look Up the CIK in the Reference

If the user did not provide a specific CIK, select the first CIK in this queue whose reference entry still has `wrapper_status = "none"`. This queue is ordered by latest-quarter fair value needed to push unlisted BDC wrapper coverage toward about 90% FV coverage. Basis: `data/output/private_markets_holdings.csv` latest-quarter BDC FV and `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`, measured 2026-06-04.

| Priority | CIK | Entity |
|---:|---|---|
| 1 | 0001838126 | HPS Corporate Lending Fund |
| 2 | 0001837532 | Apollo Debt Solutions BDC |
| 3 | 0001930087 | Golub Capital Private Credit Fund |
| 4 | 0001872371 | Oaktree Strategic Credit Fund |
| 5 | 0001851322 | North Haven Private Income Fund LLC |
| 6 | 0001742313 | Monroe Capital Income Plus Corp |
| 7 | 0001859919 | Barings Private Credit Corp |
| 8 | 0001869453 | Blue Owl Technology Income Corp. |
| 9 | 0002031750 | Ares Core Infrastructure Fund |
| 10 | 0001913724 | TPG Twin Brook Capital Income Fund |
| 11 | 0001993402 | Antares Strategic Credit Fund |
| 12 | 0001950803 | Stepstone Private Credit Fund LLC |
| 13 | 0001930679 | KKR FS Income Trust |
| 14 | 0001901164 | T. Rowe Price OHA Select Private Credit Fund |
| 15 | 0001825384 | Stone Point Credit Corp |
| 16 | 0001916099 | Diameter Credit Co |
| 17 | 0001702510 | Carlyle Credit Solutions, Inc. |
| 18 | 0001901612 | Golub Capital BDC 4, Inc. |
| 19 | 0001911066 | Nuveen Churchill Private Capital Income Fund |
| 20 | 0001902649 | BlackRock Private Credit Fund |
| 21 | 0002037804 | New Mountain Private Credit Fund |
| 22 | 0001989817 | HPS Corporate Capital Solutions Fund |
| 23 | 0001885968 | T Series BDC LLC |
| 24 | 0001899017 | Bain Capital Private Credit |
| 25 | 0001925531 | New Mountain Guardian IV BDC, L.L.C. |
| 26 | 0002049733 | Blackstone Private Real Estate Credit & Income Fund |
| 27 | 0001634452 | AB Private Credit Investors Corp |
| 28 | 0001975736 | KKR FS Income Trust Select |
| 29 | 0002083477 | APS BDC, LLC |
| 30 | 0001959604 | Jefferies Credit Partners BDC Inc. |
| 31 | 0002012139 | Fortress Private Lending Fund |
| 32 | 0001976336 | Antares Private Credit Fund |
| 33 | 0001899996 | Fidelity Private Credit Co LLC |
| 34 | 0002052152 | Apollo Origination II (Levered) Capital Trust |
| 35 | 0001772704 | Goldman Sachs Private Middle Market Credit II LLC |
| 36 | 0001965934 | Overland Advantage |
| 37 | 0002011498 | AGL Private Credit Income Fund |
| 38 | 0001766037 | NMF SLF I, Inc. |
| 39 | 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. |

Before doing any work, check the unlisted BDC reference to confirm the selected CIK exists and see its current wrapper status:

```python
import json
with open('data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json') as f:
    ref = json.load(f)
match = [e for e in ref['entries'] if e['cik'] == '{CIK_PADDED}']
if match:
    print(json.dumps(match[0], indent=2))
else:
    print('CIK not in unlisted reference -- check if listed or not a BDC')
```

If the CIK is not in the reference, check whether it is a listed BDC (has a ticker in `data/output/bdc_listed_prices.csv`) or not in the BDC universe at all. Listed BDCs can still have wrappers; the reference only tracks unlisted ones.

If `wrapper_status` is `"exists"`, the CIK already has a wrapper. Use `validate` or `update` mode instead of `create`. If `has_holdings_data` is `false`, the CIK has XBRL filing directories but no extracted holdings -- profiling will fail until holdings are extracted.

---

## Step 1: Profile the CIK's Identifiers

Before writing any config, understand the filer's identifier format.

### 1a. Sample raw identifiers

Query cached BDC holdings for this CIK. Use DuckDB or the parquet file:

```python
# Run from repo root with PYTHONPATH set
import duckdb
from pipeline.config import BDC_HOLDINGS_PARQUET_FILE, BDC_HOLDINGS_FILE

path = BDC_HOLDINGS_PARQUET_FILE if BDC_HOLDINGS_PARQUET_FILE.exists() else BDC_HOLDINGS_FILE
con = duckdb.connect()
samples = con.execute(f"""
    SELECT DISTINCT investment_identifier, report_date,
           fair_value, interest_rate, shares_held, maturity_date
    FROM read_parquet('{str(path).replace(chr(92), "/")}')
    WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{CIK_PADDED}'
    ORDER BY report_date DESC, investment_identifier
    LIMIT 100
""").fetchdf()
```

### 1b. Identify the identifier structure

Determine which format pattern applies:

| Pattern | Example | Delimiter |
|---------|---------|-----------|
| **Dash-separated hierarchy** | `Category - Pct% Country - Pct% LienType - Pct% Issuer Industry ... Rate ...` | ` - ` |
| **Pipe-separated fields** | `Issuer \| Industry \| Instrument \| Affiliation` | ` \| ` |
| **No-dash flat string** | `Category Industry Issuer Type Instrument Rate Maturity` | whitespace keywords |
| **Prefix + issuer + instrument** | `Non-Control Debt - Acme Corp - Term Loan` | ` - ` |

For each pattern, note:
- What is the **prefix** (category/affiliation/type)?
- Where is the **issuer name**?
- Where is the **instrument description**?
- Are there embedded fields (country, industry, rate, maturity)?
- What distinguishes **leaf** (position) rows from **aggregate** (subtotal) rows?
- What distinguishes **non-private** (money market, cash) rows?

### 1c. Catalog prefix variants

List all distinct first-segment prefixes across all quarters:

```sql
SELECT DISTINCT
    CASE WHEN contains(investment_identifier, ' - ')
         THEN trim(string_split(investment_identifier, ' - ')[1])
         ELSE LEFT(investment_identifier, 60)
    END AS prefix,
    COUNT(*) AS n
FROM ...
GROUP BY 1
ORDER BY n DESC
```

Note truncation variants (e.g. `Investment Debt Investments`, `IInvestment Debt Investments`, `nvestment Debt Investments`).

### 1d. Identify leaf vs aggregate patterns

Leaf rows have position-level detail: interest rate, maturity date, reference rate, shares.
Aggregate rows are subtotals: category-only text, no economic detail, large FV.

```sql
SELECT investment_identifier,
       interest_rate, maturity_date, shares_held, fair_value,
       CASE WHEN interest_rate IS NOT NULL OR maturity_date IS NOT NULL
            OR shares_held IS NOT NULL THEN 'leaf' ELSE 'maybe_aggregate' END AS guess
FROM ...
```

### 1e. Cross-reference HTML grids (when available)

Check `data/raw/filings/bdc_html/{CIK_UNPADDED}/` for `.grids.json` files. If grids exist for a period adjacent to the XBRL start date (within 1-2 quarters), extract the instrument type column from SOI tables and compare against the wrapper's `fallback_family_patterns`. This catches instrument vocabulary that the XBRL identifiers encode differently or omit entirely.

HTML SOI tables preserve the original column structure (Company / Investment Type / Rate / Maturity / Par / Cost / FV) while XBRL flattens everything into a single `investment_identifier` string. Some instrument types that exist as a distinct column in the HTML table (e.g. "Unsecured notes", "Class A-2 Units", "Partnership Units") may never appear as a keyword in the XBRL identifier.

```python
import json, glob, os

grid_files = sorted(glob.glob(f'data/raw/filings/bdc_html/{CIK_UNPADDED}/*.grids.json'))
if grid_files:
    # Use the most recent grid file
    with open(grid_files[-1]) as f:
        grids = json.load(f)
    # Find SOI tables by consistent column width (48 is common)
    soi_widths = {g['width'] for g in grids if g['width'] >= 20}
    print(f'{len(grid_files)} grid files, SOI widths: {soi_widths}')
    # Extract instrument types from the instrument column
    # Column index varies by filer -- check the filing template or inspect headers
else:
    print('No HTML grids available for this CIK')
```

**When to skip:** If grids are only available for periods 3+ quarters before the XBRL start, instrument vocabulary may have drifted. Also skip if the oracle's `unclassified_rate` is already under 2% -- the oracle surfaces the same gaps more directly.

**When it helps most:** Format transitions (comma to pipe, prefix changes) where the HTML period shows the "before" vocabulary and the XBRL period shows the "after." Also useful when the XBRL identifiers lack instrument type keywords entirely (bare company names) but the HTML SOI tables had them in a separate column.

---

## Step 2: Build the Wrapper JSON

Use the v3 schema. Read the full schema at `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.

### Required sections

```json
{
  "schema_version": "bdc-xbrl-wrapper.v3",
  "cik": "0001XXXXXX",
  "entity_name": "Fund Name",
  "version": 1,
  "source": "bdc_xbrl",
  "dispatch": { ... }
}
```

### dispatch section

The dispatch section controls source reconciliation classification. Identifiers should classify into a disposition when the CIK wrapper explains them. Unclassified rows are a wrapper coverage issue, not a reason to suppress source reconciliation output.

**`rule_prefix`**: Short uppercase label (e.g. `"TRINITY"`, `"GS_PRIVATE_CREDIT"`).

**`prefix_rules`**: Map from identifier prefix text to instrument family. Include all observed prefix variants including truncated forms:

```json
"prefix_rules": {
  "Investment Debt Investments": "debt",
  "IInvestment Debt Investments": "debt",
  "Equity and Other": "equity"
}
```

**`leaf_markers_by_family`**: Per-family lists of lowercase keywords that indicate a leaf (position-level) row. Common markers:

- **debt**: `"interest rate"`, `"maturity"`, `"reference rate"`, `"sofr"`, `"libor"`, `"initial acquisition date"`
- **equity**: `"common stock"`, `"preferred stock"`, `"partnership interest"`, `"common equity"`
- **warrant**: `"warrant"`, `"expiration date"`

**`aggregate_markers`**: Lowercase strings identifying subtotal/total rows (e.g. `"total investments"`, `"total debt investments"`, country-only subtotals).

**`non_private_markers`**: Lowercase strings for cash/money-market positions (e.g. `"money market"`, `"financial square"`, `"u.s. treasury"`).

**`fallback_family_patterns`**: Array of `{regex, family}` for identifiers that don't match any prefix_rules entry.

**`no_prefix_is_aggregate`**: Set `true` if identifiers without a known prefix are subtotals rather than positions.

**`category_marker_re`**: Regex matching category-level identifiers (segment headers that are neither leaf nor aggregate).

**`canonical_strip_re`**: Regex applied to position keys to remove volatile components before cross-quarter matching. This directly affects B1b match quality (J01/J03 scores). Common volatile patterns to strip:
- Embedded percentages that change quarterly: `"\\b\\d+\\.?\\d*\\s*%"` or `" - \\d+\\.\\d+%"`
- Variable allocation percentages in identifier segments
- Trailing dates or quarter labels

Example: GS BDC identifiers contain `" - 7.32%"` that changes every quarter. Adding `"canonical_strip_re": " - \\d+\\.\\d+%"` strips the volatile percentage, making the position key stable for B1b matching.

### archetypes section (optional but recommended)

Define instrument archetypes with detection rules and field-level constraints:

```json
"archetypes": {
  "debt": {
    "description": "All debt instruments",
    "detection_rules": {
      "keywords": ["1st Lien", "Senior Secured", "Term Loan", ...],
      "keyword_mode": "any"
    },
    "field_signatures": {
      "fair_value": {
        "type": "numeric_range",
        "constraint": "required",
        "min": -1000000000,
        "max": 1000000000000
      }
    }
  }
}
```

### invariants section (optional but recommended)

```json
"invariants": {
  "unclassified_rate": { "max_pct": 0.05 }
}
```

### identifier_parser section (when identifiers encode structured fields)

If the identifier embeds country, industry, rates, or other fields in a structured format, add an `identifier_parser` config. Currently supported type: `hierarchical_pct` (dash-separated segments with percentage prefixes).

```json
"identifier_parser": {
  "type": "hierarchical_pct",
  "issuer_boundary_keywords": [
    "Industry", "Interest Rate", "Reference Rate", "Maturity",
    "Floor", "PIK", "Effective Yield", "Initial Acquisition Date"
  ],
  "industry_keyword": "Industry",
  "rate_shorthand": {"S + ": "SOFR", "L + ": "LIBOR", "E + ": "EURIBOR"},
  "country_list": ["United States", "United Kingdom", "Canada", ...]
}
```

The `identifier_parser` drives extraction in `staging_bdc.py`:
- **issuer_name**: from last segment, text before boundary keywords (or trailing industry label for equity)
- **instrument_description**: from `seg[-2]` for 4+ segments, or `seg[1]` minus prefix for 2-3 segments
- **bdc_investment_country**: from `seg[2]` matched against country_list
- **extracted_industry**: after industry_keyword (debt) or trailing industry label match (equity)
- **reference_rate_type**: from rate_shorthand patterns

### staging section (when custom SQL extraction is needed)

For CIKs whose identifiers need special parsing beyond what the generic pipeline handles. Strategies:

- **`issuer_bridge`**: Manual `(raw_id, issuer_name, instrument)` overrides for specific identifiers
- **`prefix_strip`**: Regex to strip hierarchy prefix before standard parsing
- **`hierarchy_extract`**: Regex-based issuer + instrument extraction from category/industry/issuer/type composites
- **`hierarchy_leaf_guard`**: Allow no-dash identifiers when instrument marker + evidence fields present
- **`default`**: No special extraction

---

## Step 3: Validate the Wrapper

Validation has four levels: schema, staging oracle, trial unified rebuild, and production promotion gate.

### 3a. Schema validation

```bash
python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/{CIK}.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json
```

This only proves the JSON conforms to the schema.

### 3b. Run staging-level oracle

Use this during development to test current staging rules against cached raw BDC holdings for the CIK:

```bash
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --compare-baseline --fresh-bdc-staging
```

Check oracle output for:
- `remaining_blocking_rows`
- `remaining_blocking_fair_value`
- `remaining_wrapper_blocking_rows`
- `unclassified_rate` and `unclassified_fv_rate`
- `oracle_status` and `oracle_fail_reasons`

Inspect these artifacts:

- `oracle_summary.csv`
- `remaining_blockers.csv`
- `remaining_blocker_mechanisms.csv`
- `baseline_comparison.csv`

If the run used `--promotion-gate`, also inspect:

- `promotion_comparison.csv`
- `promotion_verdict.json`
- `exception_proposals.json`

`oracle_status` and `oracle_fail_reasons` are the raw deterministic oracle result. `effective_oracle_status`, `waived_oracle_reasons`, and `unwaived_oracle_reasons` are promotion-gate interpretation fields after accepted soft-gate exceptions are applied.

Treat these mechanisms as unresolved unless there is clear evidence and a documented acceptance rationale:

- `wrapper_blockers_remaining`
- `leaf_present_in_raw_missing_from_unified`
- `leaf_output_candidate_unmatched`
- `unclassified_signature`
- `category_rollup_source_child_fv_mismatch`
- material cost/FV or rate outliers

Do not let an agent "override" the oracle by silently changing row classifications. The agent may propose an audited exception only for eligible soft diagnostics, and only as a promotion-gate interpretation. Source reconciliation rows, wrapper classifications, and raw oracle results remain unchanged.

#### Soft-gate exception workflow

When a promotion gate writes `exception_proposals.json`, proposals are inactive templates. They do not apply until an accepted record is added to `data/overrides/bdc_xbrl_oracle_exceptions.json`.

Accepted exception records must match exactly on:

- `cik`
- `report_date`
- `oracle_reason`
- `wrapper_version`

They must also include:

- `status`: `accepted`
- `confidence`: `>= 0.80`
- `reason`
- `evidence`
- `residual_risk`
- `created_by`
- `accepted_by`
- `updated_at`

Only these review-style reasons are waiveable:

- `unclassified_rate_exceeded`
- `unclassified_fv_rate_exceeded`
- `unclassified_rate_qoq_jump`
- `content_signatures_fail`
- `unparsed_remainder_rows`
- `unparsed_remainder_spike`
- `low_position_continuity`
- `rate_outliers_detected`
- `cost_fv_ratio_outliers`
- `concept_drift_detected`
- `fv_magnitude_shift_detected`
- `rate_magnitude_shift_detected`
- `cost_magnitude_shift_detected`
- `spread_magnitude_shift_detected`

These remain non-waiveable:

- source reconciliation blockers
- `wrapper_blockers_remaining`
- `wrapper_no_archetypes`
- blocker row or FV regressions versus baseline
- `remaining_*` blocker mechanisms
- `exclusion_risk_detected`

Use exceptions for "the wrapper is acceptable despite this soft diagnostic" cases, not for fixing extraction. If a parser rule, dispatch pattern, or staging mechanism is wrong, update the wrapper instead of accepting an exception.

### 3c. One-CIK trial unified rebuild (fast inner loop)

Rebuild unified holdings for just the target CIK into a trial directory, then run the oracle against the trial artifact. This takes seconds instead of the 30+ minutes required for a full production rebuild.

```bash
python scripts/rebuild_unified_cik_trial.py --cik {CIK}
```

This reads from the existing production `bdc_holdings.parquet` and `nport_holdings.parquet`, filters to the target CIK, and runs the full unified-holdings pipeline with trial output paths. The wrapper staging logic is applied during the build, so wrapper changes are reflected.

Trial artifacts are written to `data/output/bdc_xbrl_wrapper_trial/{CIK}/unified_trial/` and include:
- `private_markets_holdings.{CIK}.csv` — one-CIK unified holdings
- `universe_orphan_holdings.{CIK}.csv` — orphan rows (if any)
- `trial_vs_production_summary.{CIK}.csv` — row/FV diff vs current production

Then run the oracle against the trial file:

```bash
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --compare-baseline \
    --holdings-file data/output/bdc_xbrl_wrapper_trial/{CIK}/unified_trial/private_markets_holdings.{CIK}.csv
```

This tests the unified-level output (classification, cost proxy, pct correction, etc.) without overwriting production data. Use this as the default iteration gate after schema/tests/staging oracle.

`--holdings-file` is mutually exclusive with `--fresh-bdc-staging`.

### 3c-match. Trial position matching (cross-quarter feedback)

Add `--match` to the trial rebuild to run position matching on the trial output and get immediate cross-quarter matching feedback:

```bash
python scripts/rebuild_unified_cik_trial.py --cik {CIK} --match
```

This produces additional artifacts in the trial directory:
- `position_matches.{CIK}.csv` — matched position pairs for this CIK
- `matching_diagnostic.{CIK}.csv` — D_fuzzy fallback diagnostics showing which position key tokens differ between begin/end sides

The script logs:
- **Match tier distribution** — what percentage of matches use each tier (B1b, B2, C, D_fuzzy, etc.)
- **J01 result** — B1b position key stability rate (target: >= 70%)
- **J03 result** — fuzzy fallback rate (target: <= 10%)
- **Fuzzy diagnostic preview** — first 10 D_fuzzy matches with position key diffs

Use this to iterate on `canonical_strip_re` and `prefix_rules`. If J03 shows high fuzzy fallback, the diagnostic CSV shows exactly which tokens in the position key are volatile across quarters (e.g., embedded percentages changing from `"7 32"` to `"7 09"`). Fix those by adding patterns to `canonical_strip_re` to strip the volatile components.

**Position key quality requirements for B1b matching:**
- Keys must be >= 12 characters with >= 3 tokens
- Keys must contain at least one 4+ letter distinctive token (not just generic words like "term loan senior secured")
- Keys must be unique within each CIK/source/report quarter — repeated keys cannot form B1b edges
- Placeholder keys (`"nc nc"`, `"lass units"`, etc.) are automatically rejected

### 3d. Production promotion gate (full rebuild)

Before labeling a wrapper `production_clean`, run the full production rebuild and oracle:

```bash
python scripts/rebuild_outputs.py --unified
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --promotion-gate
python scripts/diff_outputs.py --semantic
```

Target result:

- raw `oracle_status`: `pass` for all relevant quarters, or raw failures limited to accepted waiveable soft reasons
- `effective_oracle_status`: `pass` for all relevant quarters
- `waived_oracle_reasons`: populated only for accepted soft-gate exceptions with documented evidence
- `unwaived_oracle_reasons`: empty for all relevant quarters
- `remaining_blocking_rows`: `0`, or explicitly accepted residuals
- no increase in blocking rows or blocking FV versus baseline
- documented improvements in `promotion_comparison.csv` and `baseline_comparison.csv` if the wrapper was intended to clear blockers
- `diff_outputs.py --semantic` shows expected deltas only

If this fails, the wrapper is partial. Summarize affected quarters, mechanisms, row counts, FV exposure, waived/unwaived reasons, and whether blockers decreased versus baseline. Do not promote it as production-clean.

`diff_outputs.py --semantic` is only meaningful after canonical production artifacts are rebuilt — do not run it against trial artifacts.

### 3e. Run staging extraction check

```python
# Check field extraction quality after staging
import duckdb, pandas as pd
from pipeline.staging_bdc import _prepare_bdc
from pipeline.config import BDC_HOLDINGS_PARQUET_FILE

path = str(BDC_HOLDINGS_PARQUET_FILE).replace("\\", "/")
con = duckdb.connect()
df = con.execute(f"""
    SELECT * FROM read_parquet('{path}')
    WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{CIK}'
""").fetchdf()
con.close()

result = _prepare_bdc(df)
for col in ['issuer_name', 'instrument_description', 'bdc_investment_country',
            'extracted_industry', 'reference_rate_type']:
    filled = (result[col] != '').sum() if col in result.columns else 0
    print(f'{col}: {filled}/{len(result)} ({100*filled/len(result):.1f}%)')
```

If `identifier_parser` or `staging` config was added, confirm the target CIK appears in the loader output. A dispatch-only wrapper will not show up as a staging config.

### 3f. Run tests

```bash
pytest tests/test_bdc_xbrl_wrapper.py -v
pytest tests/test_unified_cik_trial.py -v
pytest tests/test_position_matching.py -v
pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -v
pytest tests/test_unified_holdings.py -k "not slow" --tb=short -q
```

---

## Step 4: Write Tests

Add tests to `tests/test_bdc_xbrl_wrapper.py` for:
- `classify_identifier()` returns correct dispositions for sample identifiers
- Leaf positions get `{family}_position_leaf` disposition
- Aggregate/subtotal rows get `aggregate` or `{family}_category_rollup`
- Non-private markers catch cash/money-market rows

If `identifier_parser` or `staging` config was added, add extraction tests to `tests/test_unified_holdings.py`:
- Correct `issuer_name`, `instrument_description` for representative identifiers
- Correct `bdc_investment_country`, `extracted_industry` if applicable
- Non-CIK regression: verify other CIKs are unaffected

---

## Step 5: HTML vs XBRL Evidence

Do not conflate cached source availability with validation:

- Cached HTML and `.grids.json` files prove the filing is available locally, not that extraction is valid.
- HTML template validation only applies when the template actually selects tables for those accessions.
- For XBRL-era BDC wrappers, default validation source is cached XBRL source facts reconciled to final `private_markets_holdings.csv`.
- Do not claim HTML validation for XBRL wrapper behavior unless HTML extraction actually covers the same periods and accessions.

For pre-XBRL periods, use the HTML template workflow separately and report its validation status independently from the XBRL wrapper oracle.

---

## Step 6: Partial Wrapper Verdict

If the oracle does not pass, write a concise verdict before stopping or promoting:

- CIK and entity name
- source basis used: cached XBRL source facts, fresh BDC staging, final unified holdings, HTML template validation, or a combination
- relevant quarter range
- source row count, output row count, remaining blocking rows, and remaining blocking FV
- top residual mechanisms and sample identifiers
- baseline comparison: blockers reduced, unchanged, or increased
- explicit status: `production_clean`, `partial_wrapper`, `review_required_with_accepted_soft_exceptions`, or `blocked_no_safe_mechanism`
- any accepted soft-gate exceptions: reason, confidence, evidence, and residual risk

A partial wrapper can still be useful as a diagnostic, but it must not be described as complete.

---

## Reference: Unlisted BDC Universe Lookup

Before profiling or creating a wrapper, consult the pre-built reference list to find the CIK. This avoids re-scanning the universe each time.

**Reference file:** `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`

This JSON file contains all 129 unlisted active BDCs with XBRL filing data, including:
- `cik`, `entity_name`
- `wrapper_status`: `"exists"` or `"none"`
- `wrapper_version`, `wrapper_sections`, `wrapper_staging_strategy` (when wrapper exists)
- `has_holdings_data`, `holdings_rows`, `holdings_quarters`, `holdings_latest`, `holdings_earliest`

### Quick lookup

To find a CIK by entity name or check wrapper status:

```python
import json
with open('data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json') as f:
    ref = json.load(f)
# Search by partial name (case-insensitive)
matches = [e for e in ref['entries'] if 'blackstone' in e['entity_name'].lower()]
# Filter to those without wrappers
no_wrapper = [e for e in ref['entries'] if e['wrapper_status'] == 'none']
# Filter to those with the most holdings data
big = sorted([e for e in ref['entries'] if e.get('has_holdings_data')],
             key=lambda x: x['holdings_rows'], reverse=True)
```

### Maintaining the reference

**When to regenerate:** After adding or removing a wrapper, after a universe rebuild, or when the reference `generated` date is more than 30 days old.

**How to regenerate:**

```bash
python -c "
import pandas as pd, os, duckdb, glob, json, re
from collections import OrderedDict

universe = pd.read_csv('data/output/bdc_universe.csv', dtype=str)
universe['cik_padded'] = universe['cik'].str.zfill(10)
listed = pd.read_csv('data/output/bdc_listed_prices.csv', dtype=str)
listed_ciks = set(listed['cik'].str.zfill(10).unique())
xbrl_ciks = set()
for d in os.listdir('data/raw/filings/bdc_xbrl'):
    if os.path.isdir(os.path.join('data/raw/filings/bdc_xbrl', d)):
        xbrl_ciks.add(d.zfill(10))
wrappers = {}
for f in glob.glob('data/overrides/bdc_xbrl_wrappers/*.json'):
    cik = os.path.basename(f).replace('.json', '')
    with open(f) as fh:
        data = json.load(fh)
    if data.get('schema_version') != 'bdc-xbrl-wrapper.v3': continue
    sections = [s for s in ['dispatch','staging','identifier_parser','archetypes','invariants'] if s in data]
    wrappers[cik] = {'version': data.get('version'), 'sections': sections,
                     'staging_strategy': data.get('staging',{}).get('strategy') if 'staging' in data else None}
con = duckdb.connect()
hdf = con.execute(\"\"\"SELECT LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cp,
    COUNT(*) AS tr, COUNT(DISTINCT report_date) AS nq, MAX(report_date) AS lq, MIN(report_date) AS eq
    FROM read_parquet('data/output/bdc_holdings.parquet') GROUP BY 1\"\"\").fetchdf()
con.close()
hmap = {r['cp']:{'total_rows':int(r['tr']),'n_quarters':int(r['nq']),'latest_quarter':r['lq'],'earliest_quarter':r['eq']} for _,r in hdf.iterrows()}
active = universe[universe['status']=='active']
ul = active[active['cik_padded'].isin(xbrl_ciks) & ~active['cik_padded'].isin(listed_ciks)].sort_values('entity_name')
entries = []
for _,row in ul.iterrows():
    cik = row['cik_padded']
    name = re.sub(r'\s*\(CIK\s+\d+\)','',str(row['entity_name'])).strip()
    e = OrderedDict([('cik',cik),('entity_name',name)])
    if cik in wrappers:
        w = wrappers[cik]; e['wrapper_status']='exists'; e['wrapper_version']=w['version']; e['wrapper_sections']=w['sections']
        if w['staging_strategy']: e['wrapper_staging_strategy']=w['staging_strategy']
    else: e['wrapper_status']='none'
    if cik in hmap:
        h=hmap[cik]; e['has_holdings_data']=True; e['holdings_rows']=h['total_rows']; e['holdings_quarters']=h['n_quarters']
        e['holdings_latest']=h['latest_quarter']; e['holdings_earliest']=h['earliest_quarter']
    else: e['has_holdings_data']=False
    entries.append(e)
from datetime import date
ref = OrderedDict([('description','Unlisted active BDCs with XBRL filing data. Auto-generated reference for the wrapper skill.'),
    ('generated',str(date.today())),('total_count',len(entries)),('with_wrapper',sum(1 for e in entries if e['wrapper_status']=='exists')),
    ('without_wrapper',sum(1 for e in entries if e['wrapper_status']=='none')),
    ('with_holdings_data',sum(1 for e in entries if e.get('has_holdings_data'))),
    ('without_holdings_data',sum(1 for e in entries if not e.get('has_holdings_data'))),('entries',entries)])
with open('data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json','w') as f:
    json.dump(ref,f,indent=2)
print(f'Regenerated: {len(entries)} entries, {ref[\"with_wrapper\"]} with wrappers')
"
```

### Current wrapper inventory

**Unlisted BDCs with wrappers (7):**

| CIK | Entity | Sections | Key Features |
|-----|--------|----------|-------------|
| 0001918712 | Ares Strategic Income | dispatch, archetypes | Minimal dispatch, 3 archetypes |
| 0001954360 | Crescent Private Credit | staging, archetypes | hierarchy_extract staging |
| 0001920453 | Fidelity Private Credit | dispatch, staging, archetypes | hierarchy_leaf_guard staging |
| 0001920145 | GS Private Credit | dispatch, identifier_parser, archetypes | Hierarchical pct parser, 21 prefix variants |
| 0001849894 | MSD Investment | staging, archetypes | prefix_strip staging |
| 0001905824 | PIMCO Capital Solutions | dispatch, staging, archetypes | prefix_strip, 37 aggregate markers |
| 0001925309 | Sixth Street Lending Partners | dispatch, staging, archetypes | hierarchy_leaf_guard staging |

**Listed BDCs with wrappers (6):**

| CIK | Entity | Sections | Key Features |
|-----|--------|----------|-------------|
| 0001287750 | Ares Capital (ARCC) | dispatch, archetypes | Basic aggregate/non-private markers |
| 0001633336 | Crescent Capital (CCAP) | staging, archetypes | hierarchy_extract staging |
| 0001572694 | Goldman Sachs BDC (GSBD) | dispatch, archetypes | 8 prefix rules |
| 0001377936 | Saratoga Investment (SAR) | dispatch, staging, archetypes | issuer_bridge staging, canonical_strip_re |
| 0001508655 | Sixth Street Specialty (TSLX) | dispatch, staging, archetypes | hierarchy_leaf_guard staging |
| 0001786108 | Trinity Capital (TRIN) | dispatch, archetypes | Family-specific leaf markers, v3 |

Read existing wrapper JSONs at `data/overrides/bdc_xbrl_wrappers/*.json` for patterns.

### After creating or updating a wrapper

After successfully creating or modifying a wrapper, update the reference file:

1. Re-run the regeneration script above, OR
2. Manually update the affected entry's `wrapper_status`, `wrapper_version`, and `wrapper_sections` fields in the reference JSON.

---

## Known Pitfalls (Lessons Learned)

These traps have caused agents to waste significant time debugging pipeline interactions instead of improving data quality. Read them before starting.

### Pitfall 1: `_DOUBLE_INVESTMENTS_HIERARCHY_RE` corrupts `_raw_id` for prefix_strip CIKs

**Trigger:** Adding `"Investments Investments"` to `prefix_rules` in a wrapper that also uses `staging.strategy = "prefix_strip"`.

**Mechanism:** Any CIK with `"Investments Investments"` in `prefix_rules` gets added to `_double_investments_cik_norms` in `staging_bdc.py`. This activates a generic regex (`_DOUBLE_INVESTMENTS_HIERARCHY_RE`) in the `strip_affil` CTE that partially strips the identifier — it removes `"Investments Investments - affiliation instrument_keyword "` but only captures single-word instrument keywords like `"first lien"`, NOT compound types like `"First Lien Debt"`. This leaves `"Debt"` at the front of `_raw_id`, which cascades to `bdc_investment_identifier` and corrupts issuer_name extraction.

**Fix (applied 2026-06):** `staging_bdc.py` now excludes prefix_strip CIKs from `_double_investments_cik_norms`. But agents should still verify: after adding a dispatch section to a wrapper, compare trial `bdc_investment_identifier` values against production. If most rows have different identifiers (not just new/lost rows), this trap or something similar is active.

**Verification:** Run `_prepare_bdc(bdc_df=filtered_df)` directly and check that `bdc_investment_identifier` preserves the full raw identifier. Then run `build_unified_holdings()` and check the output — if identifiers are stripped in the unified output but correct in `_prepare_bdc`, the stripping happens post-staging.

### Pitfall 2: `leaf_markers_by_family` must use the family name from `prefix_rules`

**Symptom:** Wrapper classifies everything as `mixed_category_rollup` instead of `mixed_position_leaf`, even though leaf markers exist.

**Cause:** `prefix_rules` maps prefixes to a family name (e.g. `"mixed"`), and `_has_leaf_marker()` looks up `leaf_markers_by_family[family]`. If markers are defined under `"debt"` and `"equity"` but the family is `"mixed"`, the lookup returns nothing.

**Fix:** Always define markers under the exact family name used in `prefix_rules`. If all prefixes map to `"mixed"`, put all markers (debt + equity + warrant) under the `"mixed"` key.

### Pitfall 3: `extra_industry_labels` must cover every industry label the filer uses

**Symptom:** `issuer_name = "Investments Investments"` (the raw prefix leaks through as the issuer name) for a subset of rows.

**Cause:** The `hierarchy_prefix_re` uses `(?:MSD_INDUSTRY_LABELS)` as a placeholder that expands to the union of base `_INDUSTRY_LABELS` (63 labels) + `extra_industry_labels`. If a filer uses an industry label not in either set (e.g. `"Containers, Packaging & Glass"`, `"Automobile"`, `"Services:"` without sub-category), the regex fails to match and the prefix isn't stripped.

**Prevention:** Before writing the wrapper, profile ALL distinct industry labels in the raw data:

```sql
SELECT DISTINCT regexp_extract(
    investment_identifier,
    '(?:First Lien Debt|Second Lien Debt|Subordinated Debt|Common Equity|Preferred Equity|Equity)\s+(.+?)\s+(?:[A-Z][a-z].*(?:LLC|Inc|Corp|Ltd|Co\.|LP|Partners))',
    1
) AS industry_label
FROM ...
WHERE industry_label IS NOT NULL AND industry_label != ''
ORDER BY 1
```

Cross-reference against `pipeline/classification.py:_INDUSTRY_LABELS`. Any label not in the base set must go into `extra_industry_labels`. Watch for:
- Labels with colons and sub-categories (e.g. `"Services: Business"` vs bare `"Services:"`)
- Labels with ampersands vs "and" (e.g. `"Containers, Packaging & Glass"`)
- ALL-CAPS or missing-space variants (e.g. `"SERVICESBusiness"`)

### Pitfall 4: The oracle doesn't catch issuer extraction failures

**Gap:** A row can be present in the unified output (not a blocker) but have `issuer_name = "Investments Investments"` or another garbage value. The oracle checks whether wrapper-classified leaves exist in the output and whether rollup FVs tie, but it does NOT check whether `issuer_name` was correctly extracted.

**Workaround:** After every trial rebuild, check for bad issuer names:

```python
bad = trial_df[trial_df['issuer_name'].str.contains('Investments|Total|Debt Investments', na=False, regex=True)]
print(f'Suspicious issuer_name rows: {len(bad)}')
```

If any are found, the `hierarchy_prefix_re` or industry labels need fixing.

### Pitfall 5: Optimize for data quality, not oracle metrics

**Anti-pattern:** Adding broad archetype keywords (e.g. `"Debt "` with trailing space) to suppress `unclassified_fv_rate` without investigating what the oracle is actually signaling. This masks real bugs.

**Correct approach:** When a metric fails, investigate the ROWS driving the failure before changing the wrapper. Check:
1. Are the failing rows actually in the output? (blocker check)
2. Do they have correct `issuer_name` and `instrument_description`? (extraction check)
3. Are they real positions or misclassified aggregates? (classification check)
4. Did the trial introduce identity changes (different `bdc_investment_identifier`) vs just new/lost rows? (regression check)

### Pitfall 6: Always compare trial vs production at the row level before trusting summary metrics

**Anti-pattern:** Running the trial, seeing "+88 new rows" in the summary, and assuming all 88 are genuine rescues.

**Correct approach:** Compare `bdc_investment_identifier` values between trial and production:

```python
trial_keys = set(zip(trial['report_date'], trial['bdc_investment_identifier']))
prod_keys = set(zip(prod['report_date'], prod['bdc_investment_identifier']))
new_keys = trial_keys - prod_keys
lost_keys = prod_keys - trial_keys
```

If `lost_keys` is large (especially close to the size of `new_keys`), most rows changed identity rather than being genuinely new. This signals an identifier corruption bug, not a wrapper improvement.

### Pitfall 7: Stale trial output

**Symptom:** Oracle or comparison results don't match expectations. Metrics look wrong despite code being correct.

**Cause:** Trial output files persist across runs. If a rebuild fails or runs against old module code, the output file isn't updated but still exists. Subsequent reads of the file return stale data.

**Prevention:** After every trial rebuild, check the file modification timestamp before reading results. If running diagnostics interactively, verify that `_prepare_bdc()` output matches expectations before trusting `build_unified_holdings()` output.

---

## Guardrails

- **Do not add identifiers to aggregate_markers unless verified across all quarters.** A subtotal in one quarter may become a leaf in another.
- **Include truncation variants in prefix_rules.** Filers sometimes have off-by-one prefix truncation in XBRL (e.g. `IInvestment`, `nvestment`).
- **Test both leaf survival and aggregate filtering.** Every wrapper change needs at least one "this real position survives" and one "this subtotal is filtered" test.
- **Do not run SEC downloads.** All raw data is cached. Use `_prepare_bdc()` or `--fresh-bdc-staging` to rebuild from cache.
- **Validate with the final unified oracle before declaring success.** Visual plausibility is not evidence.
- **Do not hide failed oracle status.** Residual blockers are valid outcomes and must be documented.
- **Do not promote dispatch-only wrappers as extraction fixes.** They classify identifiers but may not change final holdings extraction.
- **Run `--match` before declaring a wrapper production-clean.** A wrapper that passes the unified oracle but has >10% D_fuzzy fallback (J03 fail) produces unstable position IDs across quarters, which corrupts index returns.
- **Use `matching_diagnostic.{CIK}.csv` to debug high fuzzy rates.** The `key_diff_summary` column shows exactly which tokens differ between begin and end position keys. If the differing tokens are embedded percentages, dates, or allocation numbers, add a `canonical_strip_re` to remove them.
- **Position keys must be issuer-specific.** Generic keys like `"senior secured first lien term loan"` (all common vocabulary, no issuer name) will be rejected by the B1b strong-key filter. Ensure `prefix_rules` strip enough prefix that the issuer name remains in the position key.
