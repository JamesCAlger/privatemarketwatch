# Wrapper Creation (Step 2 + Authoring Pitfalls)

This document covers building the wrapper JSON and authoring pitfalls to avoid.

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

**Default field signatures:** The pipeline applies default field signatures when an archetype name matches a known family but the wrapper does not specify all constraints. For example, an archetype named `"equity"` automatically gets `basis_spread: forbidden` unless the wrapper explicitly defines a `basis_spread` signature. See `_DEFAULT_ARCHETYPE_SIGNATURES` in `pipeline/wrapper_content_signatures.py` for the full set of defaults by family name.

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
- **Static HTML-section bridge**: Separate audited bridge file for same-accession HTML section headers that were lost from XBRL typed identifiers
- **`prefix_strip`**: Regex to strip hierarchy prefix before standard parsing
- **`hierarchy_extract`**: Regex-based issuer + instrument extraction from category/industry/issuer/type composites
- **`hierarchy_leaf_guard`**: Allow no-dash identifiers when instrument marker + evidence fields present
- **`default`**: No special extraction

---

## Authoring Pitfalls

These traps have caused agents to waste significant time debugging pipeline interactions instead of improving data quality.

### Pitfall 1: `_DOUBLE_INVESTMENTS_HIERARCHY_RE` corrupts `_raw_id` for prefix_strip CIKs

**Trigger:** Adding `"Investments Investments"` to `prefix_rules` in a wrapper that also uses `staging.strategy = "prefix_strip"`.

**Mechanism:** Any CIK with `"Investments Investments"` in `prefix_rules` gets added to `_double_investments_cik_norms` in `staging_bdc.py`. This activates a generic regex (`_DOUBLE_INVESTMENTS_HIERARCHY_RE`) in the `strip_affil` CTE that partially strips the identifier -- it removes `"Investments Investments - affiliation instrument_keyword "` but only captures single-word instrument keywords like `"first lien"`, NOT compound types like `"First Lien Debt"`. This leaves `"Debt"` at the front of `_raw_id`, which cascades to `bdc_investment_identifier` and corrupts issuer_name extraction.

**Fix (applied 2026-06):** `staging_bdc.py` now excludes prefix_strip CIKs from `_double_investments_cik_norms`. But agents should still verify: after adding a dispatch section to a wrapper, compare trial `bdc_investment_identifier` values against production. If most rows have different identifiers (not just new/lost rows), this trap or something similar is active.

**Verification:** Run `_prepare_bdc(bdc_df=filtered_df)` directly and check that `bdc_investment_identifier` preserves the full raw identifier. Then run `build_unified_holdings()` and check the output -- if identifiers are stripped in the unified output but correct in `_prepare_bdc`, the stripping happens post-staging.

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
