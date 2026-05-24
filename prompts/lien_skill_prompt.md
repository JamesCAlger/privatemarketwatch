# Lien Position Classification Skill

## Task

Classify the lien position of private credit (direct lending) investments into one of three tiers:

| Value | Description |
|---|---|
| `First Lien` | Senior secured, first priority claim. Includes unitranche, super senior, last out, first out. |
| `Second Lien` | Junior secured, second priority claim. Includes junior lien, junior secured. |
| `Unsecured` | No collateral claim. Includes subordinated debt, mezzanine. |

## Input

Each batch CSV (`data/output/lien_skill_batches/batch_NNN.csv`) contains:

| Column | Description |
|---|---|
| `pattern_norm` | Normalized instrument pattern (cache key) |
| `sample_issuer_name` | Example issuer name from holdings data |
| `sample_instrument_description` | Example instrument description |
| `sample_bdc_investment_identifier` | Example BDC investment identifier (often contains full metadata) |
| `total_fv` | Total fair value across all positions matching this pattern |
| `n_positions` | Number of position rows |
| `n_funds` | Number of distinct funds holding this pattern |

## Process

1. Read the batch CSV
2. For each row, examine `sample_issuer_name`, `sample_instrument_description`, and `sample_bdc_investment_identifier`
3. Classify as `First Lien`, `Second Lien`, or `Unsecured`
4. If the position type cannot be determined, skip it (do not guess)

## Output

Write results to the lien cache (`data/output/lien_cache.csv`) with columns:

| Column | Value |
|---|---|
| `pattern_norm` | From input |
| `lien_position` | `First Lien`, `Second Lien`, or `Unsecured` |
| `confidence` | `high`, `medium`, or `low` |
| `source` | `cc_skill` |
| `timestamp` | ISO 8601 |

## Examples

| Instrument text | Classification | Rationale |
|---|---|---|
| "Senior Secured First Lien Term Loan" | First Lien | Explicit first lien keyword |
| "Second Lien Term Loan" | Second Lien | Explicit second lien keyword |
| "Senior Secured Second Lien Term Loan" | Second Lien | Second lien takes priority over senior secured |
| "Mezzanine Loan" | Unsecured | Mezzanine = unsecured |
| "Subordinated Note" | Unsecured | Subordinated = unsecured |
| "Unitranche Term Loan" | First Lien | Unitranche is first lien |
| "Revolving Credit Facility" | First Lien | Revolvers are typically first lien senior secured |
| "Delayed Draw Term Loan" | ? | No lien keyword -- inspect BDC identifier for context |

## Validation

After processing, run:
```
python scripts/lien_merge_results.py --validate
python scripts/lien_merge_results.py --stats
```

To apply results:
```
python scripts/lien_merge_results.py --validate --apply
```
