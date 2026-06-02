---
description: Create or update a BDC XBRL wrapper JSON for a CIK
argument-hint: <CIK> [profile|create|validate|update]
allowed-tools: Bash Read Write Edit Grep Glob
---

# BDC XBRL Wrapper Skill

Build, validate, or update per-CIK wrapper JSON files that control how the pipeline classifies and extracts structured fields from XBRL investment identifiers.

**Usage:** `/wrapper <CIK> [mode]`

Modes: `profile` (default), `create`, `validate`, `update`

---

## Architecture Context

A **wrapper** is a deterministic, versioned configuration mapping one filer's idiosyncratic XBRL identifier layout into clean structured records. The two-speed split is non-negotiable:

- **Hot path (per row):** deterministic, frozen, fully traceable. No LLM.
- **Edge (per new CIK or drift):** agent generates or repairs a wrapper, gated by deterministic verifiers.

Wrappers live at `data/overrides/bdc_xbrl_wrappers/{CIK}.json` and conform to `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.

There is **one wrapper per CIK** (no per-quarter versioning). Format drift across quarters is handled by broadening prefix rules, adding fallback patterns, or adding identifier parser config.

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

The dispatch section controls source reconciliation classification. Every identifier gets classified into a disposition.

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

### 3a. Schema validation

```bash
python -c "
import json
from jsonschema import validate
with open('schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json') as f: schema = json.load(f)
with open('data/overrides/bdc_xbrl_wrappers/{CIK}.json') as f: wrapper = json.load(f)
validate(wrapper, schema)
print('Schema validation passed')
"
```

### 3b. Run wrapper oracle

```bash
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --fresh-bdc-staging
```

Check oracle output for:
- `remaining_blocking_rows`: should decrease vs no-wrapper baseline
- `unclassified_rate`: should be < 5%
- `oracle_status`: target `pass`

### 3c. Run staging extraction check

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

### 3d. Run tests

```bash
pytest tests/test_bdc_xbrl_wrapper.py -v
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

## Reference: Existing Wrappers

| CIK | Entity | Key Features |
|-----|--------|-------------|
| 0001786108 | Trinity Capital | Family-specific leaf markers, 3 archetypes |
| 0001377936 | Saratoga Investment | Pct-prefix parsing, issuer bridges |
| 0001920145 | GS Private Credit | Hierarchical pct identifier_parser, 12+ prefix variants |
| 0001572694 | Goldman Sachs BDC | Same GS prefix rules |
| 0001920453 | Fidelity Private Credit | hierarchy_leaf_guard staging |
| 0001508655 | Sixth Street Specialty | hierarchy_leaf_guard staging |
| 0001633336 | Crescent Capital | hierarchy_extract staging |
| 0001918712 | Ares Strategic Income | Minimal dispatch, 3 archetypes with field signatures |
| 0001849894 | MSD Investment | prefix_strip staging |
| 0001287750 | Gladstone Capital | Basic prefix rules |

Read existing wrappers at `data/overrides/bdc_xbrl_wrappers/*.json` for patterns.

---

## Guardrails

- **Do not add identifiers to aggregate_markers unless verified across all quarters.** A subtotal in one quarter may become a leaf in another.
- **Include truncation variants in prefix_rules.** Filers sometimes have off-by-one prefix truncation in XBRL (e.g. `IInvestment`, `nvestment`).
- **Test both leaf survival and aggregate filtering.** Every wrapper change needs at least one "this real position survives" and one "this subtotal is filtered" test.
- **Do not run SEC downloads.** All raw data is cached. Use `_prepare_bdc()` or `--fresh-bdc-staging` to rebuild from cache.
- **Validate with the oracle before declaring success.** Visual plausibility is not evidence.
