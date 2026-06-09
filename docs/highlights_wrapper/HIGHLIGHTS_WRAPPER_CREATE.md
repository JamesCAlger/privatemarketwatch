# Fund Highlights Wrapper -- Create Mode

Author a per-CIK JSON wrapper to fix concept mapping gaps or share class aliases.

## Wrapper location

`data/overrides/fund_highlights_wrappers/{CIK}.json`

## Schema

Version: `fund-highlights-wrapper.v1`
Full schema: `schemas/fund_highlights_wrapper/wrapper_v1.schema.json`

## Required fields

```json
{
  "schema_version": "fund-highlights-wrapper.v1",
  "cik": "0001280784",
  "entity_name": "Hercules Capital, Inc.",
  "version": 1
}
```

## Optional sections

### concept_overrides (array, ordered)

Override the global `HIGHLIGHTS_CONCEPT_MAP` for this CIK. Checked before the global map. First match wins.

```json
"concept_overrides": [
  {
    "xbrl_concept_substring": "customnetassetconcept",
    "target_field": "assets_net",
    "action": "map",
    "evidence": "Filer uses custom concept for net assets"
  }
]
```

Actions:
- `map`: Alias this concept to the target field.
- `suppress`: Ignore this concept entirely (useful when a concept falsely matches a global map entry).
- `prefer`: Override the global map match (same as `map` but semantically marks a priority override).

**Pitfalls:**
- `xbrl_concept_substring` is matched against the lowercase local XBRL name. Use lowercase.
- Order matters: if two substrings both match a concept, the first one wins.
- Substring overlap: `"netasset"` matches both `netassetvalue` and `assetsnet`. Be specific.

### share_class_aliases (object)

Map unrecognized XBRL member names to canonical share class labels.

```json
"share_class_aliases": {
  "InstitutionalSharesMember": "ClassI",
  "AdvisorSharesMember": "ClassA"
}
```

Keys are matched as substrings against the raw XBRL member name. Checked before the global regex chain.

### oracle_tolerances (object)

Relax identity check tolerances for this CIK. Capped at 20%.

```json
"oracle_tolerances": {
  "nav_identity_tol": 0.05,
  "income_identity_tol": 0.08
}
```

Only use when the identity check fails consistently at a low percentage (3-8%) across multiple quarters, indicating a structural rounding or timing mismatch rather than a data error.

### source_preferences (object)

Per-field source preference when cross-source values diverge. Reserved for future use.

### notes (string)

Free-text documentation of why this wrapper exists.

## Authoring checklist

1. Profile the CIK first (see HIGHLIGHTS_WRAPPER_PROFILE.md)
2. Write the JSON with required + needed optional sections
3. Validate: `python scripts/rebuild_highlights_cik_trial.py --cik {CIK}`
4. Compare before/after: also run `--no-wrapper` for baseline
5. Verify identity pass rates improved
6. Proceed to validate mode: `docs/highlights_wrapper/HIGHLIGHTS_WRAPPER_VALIDATE.md`
