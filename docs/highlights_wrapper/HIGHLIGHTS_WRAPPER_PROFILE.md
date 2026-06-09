# Fund Highlights Wrapper -- Profile Mode

Profile a CIK's fund-level XBRL concepts to identify which concept overrides and share class aliases are needed.

## Step 0: Claim the CIK

```bash
python scripts/fund_highlights_wrapper_worklist.py --next
```

If a specific CIK was given, skip the worklist.

## Step 1: Understand the failure mode

Read the residual profile to understand what's failing:

```bash
python -c "
import pandas as pd
df = pd.read_csv('data/output/fund_highlights_residual_profile.csv', dtype=str)
row = df[df['cik'].str.contains('CIK_HERE')]
print(row.to_string())
"
```

Check the oracle for specific failure reasons:

```bash
python -c "
import pandas as pd
df = pd.read_csv('data/output/bdc_fund_highlights_oracle.csv', dtype=str)
cik_rows = df[df['cik'].str.contains('CIK_HERE')]
fails = cik_rows[cik_rows['oracle_status'] == 'fail']
print(f'Total rows: {len(cik_rows)}, Fails: {len(fails)}')
print(fails[['report_quarter', 'share_class', 'oracle_fail_reasons', 'nav_identity_pct_diff', 'income_identity_pct_diff']].to_string())
"
```

## Step 2: Inspect XBRL concepts

Find a cached XBRL file for this CIK and dump all concepts:

```bash
python -c "
import pandas as pd
from lxml import etree
idx = pd.read_csv('data/output/bdc_filings_index.csv', dtype=str)
cik_files = idx[(idx['cik'].str.contains('CIK_HERE')) & (idx['xbrl_download_status'].isin(['cached','downloaded']))]
path = cik_files.iloc[0]['xbrl_local_path']
tree = etree.parse(path)
root = tree.getroot()
concepts = set()
for elem in root.iter():
    tag = elem.tag
    if isinstance(tag, str) and tag.startswith('{'):
        local = tag.split('}', 1)[1].lower()
        concepts.add(local)
for c in sorted(concepts):
    print(c)
" > data/output/fund_highlights_wrapper_trial/CIK_HERE_concepts.txt
```

## Step 3: Compare concepts against the global map

Check which concepts the global `HIGHLIGHTS_CONCEPT_MAP` matches and which it misses.
Look for custom concepts (containing the CIK namespace prefix like `ck0001280784:`) that encode fund-level data.

Key questions:
- Does the filer use custom concepts for `assets_net`, `total_assets`, or NAV?
- Are there share class members the global `_canonical_share_class` regex chain doesn't recognize?
- Which identity checks fail and what values are involved?

## Step 4: Draft override plan

Document which overrides are needed:
- `concept_overrides`: custom concept -> target field mappings
- `share_class_aliases`: unrecognized member names -> canonical labels
- `oracle_tolerances`: if identity checks fail at 3-5% consistently due to rounding or timing mismatches

Then proceed to create mode: `docs/highlights_wrapper/HIGHLIGHTS_WRAPPER_CREATE.md`
