# GICS Classification + Aggregate Header Flagging Skill

## Purpose

Classify the ~24% of holdings FV ($167B, ~23K entities) currently without GICS sector classification. These unclassified entities are a mix of three populations: real companies (~15-20%), leaked aggregate headers (~30-35%), and JV/subsidiary/co-invest vehicles (~40-50%).

Each CC instance processes a batch of ~100 entities, making one of four verdicts per entity: GICS, AGGREGATE_HEADER, JV_SUBSIDIARY, or UNRESOLVABLE.

## Architecture

```
scripts/gics_worklist.py          Generate ranked batch CSVs
        |
prompts/gics_aggregate_skill_prompt.md   CC skill prompt (per-instance)
        |
    +---+---+
    |       |
company_gics_cache.csv     aggregate_header_flags.csv
(GICS verdicts)            (non-GICS verdicts)
    |       |
    +---+---+
        |
scripts/gics_merge_results.py    Validate, dedup, rebuild
```

## Files

| File | Type | Purpose |
|------|------|---------|
| `scripts/gics_worklist.py` | Script | Generate batch CSVs from unclassified entities |
| `prompts/gics_aggregate_skill_prompt.md` | Prompt | CC skill instructions with four-verdict taxonomy |
| `scripts/gics_merge_results.py` | Script | Post-session validation, dedup, stats, rebuild |
| `pipeline/config.py` | Config | `AGGREGATE_HEADER_FLAGS_FILE`, `GICS_SKILL_BATCHES_DIR`, `GICS_SKILL_CLAIMS_FILE` |
| `pipeline/staging_bdc.py` | Pipeline | CTE to exclude CC-flagged aggregate headers |

## Data Flow

### Inputs
- `data/output/private_markets_holdings.csv` -- unified holdings with empty `gics_sub_industry`
- `data/output/company_gics_cache.csv` -- existing GICS cache (155K entries)
- `data/reference/gics_sub_industries.json` -- 162 valid GICS sub-industry names

### Outputs
- `data/output/gics_skill_batches/batch_NNN.csv` -- worklist batches
- `data/output/gics_skill_claims.json` -- advisory claim tracking
- `data/output/company_gics_cache.csv` -- GICS verdicts appended (source="cc_skill")
- `data/output/aggregate_header_flags.csv` -- non-GICS verdicts (AGGREGATE_HEADER, JV_SUBSIDIARY, UNRESOLVABLE)

## Verdict Taxonomy

| Verdict | Action | Cache File | Pipeline Effect |
|---------|--------|-----------|----------------|
| GICS | Classify | `company_gics_cache.csv` | Auto-applied via `classify_gics(cache_only=True)` |
| AGGREGATE_HEADER | Exclude | `aggregate_header_flags.csv` | Excluded in `staging_bdc.py` CTE (high/medium confidence) |
| JV_SUBSIDIARY | Flag only | `aggregate_header_flags.csv` | No exclusion (informational) |
| UNRESOLVABLE | Flag only | `aggregate_header_flags.csv` | No exclusion (informational) |

## Pipeline Integration

### GICS Cache
GICS verdicts write to the existing `company_gics_cache.csv` with `source="cc_skill"`. On the next `--unified` run, `classify_gics(cache_only=True)` applies them via DuckDB LEFT JOIN on normalized issuer_name.

### Aggregate Header Exclusion
`staging_bdc._prepare_bdc()` loads `aggregate_header_flags.csv` (if it exists) and injects a CTE between `no_bad_issuers` and `no_affil_dupes`:

```sql
no_cc_agg_headers AS (
    SELECT n.* FROM no_bad_issuers n
    LEFT JOIN cc_aggregate_header_flags f
        ON <normalized_issuer_name> = f.name_norm
    WHERE f.name_norm IS NULL
)
```

Name normalization in SQL mirrors `_normalize_company_name()`: lowercase, strip legal suffixes (LLC, Inc, Corp, etc.), collapse whitespace.

When the flags file is empty or missing, the CTE is skipped and `no_affil_dupes` reads directly from `no_bad_issuers` (zero overhead).

## Workflow

```bash
# 1. Generate batches
python scripts/gics_worklist.py --batch-size 100

# 2. CC instances process batches (load skill prompt, claim batch, process)

# 3. Validate and rebuild
python scripts/gics_merge_results.py --validate --apply

# 4. Check results
python scripts/gics_merge_results.py --stats

# 5. Re-export frontend
python -c "from pipeline.export_frontend import export_all; export_all()"
```

## Claim Tracking

`gics_skill_claims.json` is advisory (not locked). Each CC instance writes its batch status after completion. This prevents duplicate work but does not enforce exclusivity.

## Validation

`gics_merge_results.py --validate` checks:
1. All GICS sub-industry names match `gics_sub_industries.json`
2. All verdicts are in {AGGREGATE_HEADER, JV_SUBSIDIARY, UNRESOLVABLE}
3. All confidence values are in {high, medium, low}
4. No empty name_norm values
5. Deduplicates across batches (highest confidence wins)
