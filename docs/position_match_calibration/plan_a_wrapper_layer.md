# Plan A: Wrapper Layer Fixes

Status: Not started
Depends on: Nothing
Blocks: Plan C (re-calibration)

## Motivation

The 2026-06-11 calibration (600 pairs, 4.2% weighted error rate) found that 47 of 112 errors (42%) originate from wrapper/staging extraction problems -- not from the matching algorithm itself. Three CIKs account for all of them:

| CIK | Entity | Errors | Root cause |
|-----|--------|--------|------------|
| 0001950803 | Stepstone Private Credit Fund | 21 | Pipe parser assigns GICS sector label to `issuer_name` instead of company name |
| 0001572694 | Goldman Sachs BDC | ~15 | Structural prefix text (sector + instrument + spread) embedded in `issuer_name` inflates fuzzy similarity |
| 0001851322 | North Haven Private Income Fund | ~9 | Same structural prefix pattern as GSBD |
| 0001920453 | Fidelity Private Credit Fund | 2 | Category subtotal rows ("Debt", "Debt Diversified Financial Services") not dispatched as aggregate |

Additionally, the current wrapper system has no mechanism to detect when a filer changes their identifier format between quarters. The Stepstone format changed from 8 segments to 7 segments after 2023-Q3, silently mis-parsing 94.9% of rows for 10 quarters before calibration caught it.

## Deliverables

### 1. Segment assertions framework

**Schema extension**: Add `segment_assertions` to the wrapper v3 schema alongside the existing `identifier_format.field_order`. Each assertion is a statistical check on segment content distribution per quarter.

```json
"segment_assertions": [
  {
    "segment_index": 3,
    "field_name": "issuer_instrument",
    "expected_pattern": "entity_name_like",
    "min_prevalence": 0.70,
    "description": "Segment 3 should contain multi-word proper nouns (company names), not GICS sector labels"
  },
  {
    "segment_index": 5,
    "field_name": "interest_rate",
    "expected_pattern": "rate_like",
    "min_prevalence": 0.60,
    "description": "Segment 5 should match rate patterns (e.g., SOFR+N%, N.NN%)"
  },
  {
    "segment_count": 7,
    "min_prevalence": 0.80,
    "description": "At least 80% of rows should have 7 pipe-delimited segments"
  }
]
```

These are canaries, not gates. When a quarter's actual distribution drops below the `min_prevalence` threshold, the oracle warns that the wrapper needs review.

**Pattern vocabulary**: A small set of reusable content-type detectors:
- `entity_name_like`: contains legal suffix (LLC, Inc, Corp, LP) OR multi-word capitalized phrase OR known entity from prior quarters
- `rate_like`: matches `\d+\.\d+%` or `SOFR\+\d+` or `L\+\d+` or `\d+\.\d+ *%`
- `date_like`: matches `\d{1,2}/\d{1,2}/\d{2,4}` or `\d{4}-\d{2}-\d{2}` or month-name patterns
- `gics_sector_like`: matches known GICS sub-industry labels (reference list from `data/reference/gics_sub_industries.csv` or hardcoded top-100)
- `instrument_like`: contains "Term Loan", "Revolver", "DDTL", "Senior Secured", "First Lien", etc.

**New I-check: `I08_segment_assertion_drift`**:
- For each wrapped CIK, load the wrapper's `segment_assertions`
- For each quarter, compute actual prevalence of each assertion
- Warn if any assertion drops below its threshold in any quarter
- Report: CIK, quarter, assertion description, expected prevalence, actual prevalence

### 2. CIK wrapper fixes

**Stepstone (0001950803)**: Fix the staging strategy to use `field_order` metadata for segment assignment. When `field_order` declares `["category", "lien_type", "industry", "issuer_instrument", ...]`, the parser should assign segment 4 (not segment 3) as `issuer_name`. Add segment assertions for the 7-segment format. This affects 7,414 of 7,816 rows (94.9%).

**Goldman Sachs BDC (0001572694)**: Add wrapper rules to strip the structural sector/instrument/spread prefix from `issuer_name`. The current format embeds the pattern `"[Sector] [Sub-category] [Company Name] [Instrument] [Spread]"` as a single string. The wrapper's `identifier_parser` or `staging` section should extract just the company name portion.

**North Haven Private Income Fund (0001851322)**: Same structural prefix pattern as GSBD. Apply equivalent prefix-stripping rules.

**Fidelity Private Credit (0001920453)**: Add `"Debt"` and `"Debt Diversified Financial Services"` (and similar generic category labels with no rate/maturity) to the wrapper's `aggregate_markers`. These are category subtotals that should be dispatched as `aggregate`, not `position_leaf`.

### 3. New I-category oracle checks

**I09: GICS issuer name detection**: For each CIK-quarter, compute the percentage of rows where `issuer_name` matches a GICS sub-industry label. Warn if >5% of rows match. This catches the Stepstone pattern generically -- any future CIK that starts using GICS sectors as issuer names will trigger a warning without needing a calibration exercise to discover it.

**I10: Instrument sub-type coverage**: For CIKs with multiple positions per entity, check whether `instrument_description` distinguishes facility types (Revolver vs Term Loan vs DDTL). Warn if >N% of same-entity multi-position groups have identical instrument descriptions. This surfaces a precondition for pattern 4/6 matching errors.

**I11: Position key uniqueness within entity**: Group position keys by entity within a quarter. Warn if multiple positions at the same entity share the same position key (or keys differing only by trailing digit). This predicts pattern 3 (tranche renumbering) vulnerability.

## Verification

- Schema validation passes for updated wrapper JSONs
- `python -m pipeline.oracle_runner --cik 0001950803 --category I` shows I08/I09 passing after fix
- `python -m pipeline.oracle_runner --cik 0001572694 --category I` shows I09 passing after fix
- `python -m pipeline.oracle_runner --cik 0001920453 --category I` shows aggregate dispatch correct
- Trial rebuild for each affected CIK shows correct `issuer_name` extraction
- Existing tests pass (no regressions in unrelated CIKs)
- Spot-check: sample 20 Stepstone rows and confirm company names appear in `issuer_name`

## Files to create/modify

| File | Action |
|------|--------|
| `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json` | Add `segment_assertions` to schema |
| `pipeline/oracle_checks.py` | Add I08, I09, I10, I11 checks |
| `pipeline/bdc_xbrl_wrapper.py` or `pipeline/staging_bdc.py` | Use `field_order` in pipe parser |
| `data/overrides/bdc_xbrl_wrappers/0001950803.json` | Fix staging + add segment assertions |
| `data/overrides/bdc_xbrl_wrappers/0001572694.json` | Add prefix stripping rules |
| `data/overrides/bdc_xbrl_wrappers/0001851322.json` | Add prefix stripping rules |
| `data/overrides/bdc_xbrl_wrappers/0001920453.json` | Add aggregate markers |
| `tests/test_oracle_checks.py` | Tests for I08, I09, I10, I11 |

## Expected impact

- Eliminates 47 of 112 calibration errors (42%)
- E_entity_fingerprint tier error rate: 23.3% -> ~0%
- D_fuzzy tier error rate: 22.5% -> ~10.6%
- Establishes ongoing detection for filer format changes across all wrapped CIKs
