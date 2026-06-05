# Wrapper Profiling (Steps 0-1)

This document covers CIK lookup and identifier profiling for the BDC XBRL wrapper skill.

---

## Step 0: Look Up the CIK in the Reference

If the user did not provide a specific CIK, select the first CIK in the priority queue (in SKILL.md) whose reference entry still has `wrapper_status = "none"`.

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

### 1f. Create a static HTML-section bridge when XBRL dropped section context

If same-accession cached HTML shows position rows under visible instrument section headers but the XBRL `InvestmentIdentifierAxis` keeps only bare issuer names, do not add a broad debt/equity text catch-all. Use a static HTML-section bridge instead.

Bridge files live at `data/overrides/bdc_xbrl_html_section_bridges/{CIK}.json` and conform to `schemas/bdc_xbrl_html_section_bridge/bridge_v1.schema.json`. They are exact-keyed by `cik`, `accession_number`, `report_date`, and lowercased raw identifier, so they apply only to audited same-filing rows.

Use the proposer to draft candidates from cached HTML and source rows:

```bash
python -m pipeline.bdc_xbrl_html_bridge \
  --cik {CIK} \
  --accession {ACCESSION} \
  --report-date {YYYY-MM-DD} \
  --source-rows-csv data/output/bdc_xbrl_wrapper_trial/{CIK}/remaining_blockers.csv \
  --output data/overrides/bdc_xbrl_html_section_bridges/{CIK}.proposed.json
```

Before accepting a bridge record, verify:

- The HTML file is cached locally; do not download SEC HTML for this step unless the user explicitly asks.
- The cited HTML row is a position row, not a subtotal/header/comparative-period row.
- The active section label is an instrument type such as `First Lien Debt`, `Second Lien Debt`, `Preferred Equity`, or `Common Equity`.
- The source row matches the HTML row within the same accession/report date by normalized issuer and fair value, or by at least two economic fields.
- Ambiguous duplicate issuer rows are rejected unless the bridge has separate exact evidence for each row.

The bridge is production-affecting only after an accepted `{CIK}.json` bridge file is committed. Adjacent-period HTML may support a review note, but must not create an accepted bridge record for a different accession.

---

## Reference: Unlisted BDC Universe Lookup

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
