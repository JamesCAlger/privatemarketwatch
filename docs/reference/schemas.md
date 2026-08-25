# Schemas & Validation Details

Extracted from AGENTS.md for reference. See AGENTS.md for operational guardrails and contracts.

## BDC Holdings Schema (`bdc_holdings.csv`)

| Column | Type | Description |
|---|---|---|
| `cik` | str | SEC CIK |
| `entity_name` | str | BDC name |
| `accession_number` | str | SEC filing accession number |
| `form_type` | str | 10-K, 10-Q, etc. |
| `filing_date` | str | Date filed with SEC |
| `report_date` | str | Period of report |
| `period` | str | XBRL context instant date |
| `investment_identifier` | str | Typed dimension value (investee name + metadata) |
| `fair_value` | float | Fair value |
| `cost` | float | Cost basis |
| `principal_amount` | float | Principal/par amount |
| `interest_rate` | float | Stated interest rate |
| `basis_spread` | float | Spread over reference rate |
| `reference_rate_type` | str | SOFR, PRIME, etc. |
| `maturity_date` | str | Maturity date |
| `shares_held` | float | Number of shares |
| `pct_of_net_assets` | float | % of net assets |
| `unrealized_gain_loss` | float | Unrealized appreciation/depreciation |
| `pik_rate` | float | PIK interest rate |
| `industry` | str | Industry axis (rarely populated; usually in identifier) |
| `investment_type` | str | Investment type axis (rarely populated) |
| `affiliation` | str | Issuer affiliation (rarely populated) |
| `dimensions_raw` | str | Full XBRL dimension string for audit |
| `src_context_id` | str | XBRL contextRef of the winning dedup row (2026-08-22). With `accession_number`, locates the fact context in the cached filing. Primary-of-N when `dedupe_context_count` > 1; `''` for rows built before the anchor migration or merged from a legacy CSV. |

## Row Identity (`row_id` / `row_id_basis`, unified holdings)

`private_markets_holdings.csv` appends two columns AFTER `UNIFIED_COLUMNS`
(they are not in the constant by design; `_assign_row_ids` is the final build
step and re-runs after `assign_position_ids` re-saves):

- `row_id` = `ROW-` + first 16 hex chars of md5 over the row's source anchor:
  `source|accession_number|src_context_id` for BDC rows,
  `source|accession_number|nport_holding_id` for N-PORT rows.
  The anchor names the filing fact context, so the id survives rebuilds,
  staging reorders, promoted corrections, and parser fixes. It is an
  **as-filed claim**: an amendment (new accession) is a new id by design.
- `row_id_basis` = `src_anchor` when the anchor exists, else `natural_key` --
  the legacy fallback hash over `position_id_registry.compute_natural_keys`
  (content-sensitive: a corrected principal changes a fallback row's id).
- `row_id` is a within-build row name, not a cross-quarter identity --
  `position_id` owns that layer and is unchanged.
- Migration tooling: `scripts/restamp_row_selectors.py` maps legacy
  natural-key ids cited in correction-leaf `row_selector`s to anchor ids.
- Source-reconciliation published ids (2026-08-22): detail artifacts carry
  `source_row_id` = `src:{accession_number}:{context_id}` (stable grounding
  anchor; `#k` suffix on within-frame duplicate contexts, `src-ord:{n}`
  fallback when a part is missing) and `output_row_id` = the unified
  `row_id` when available. The positional ordinals remain internal to the
  reconciliation SQL only. Correction-leaf `positions[].source_row_id`
  citations copy the published anchor verbatim; the value gate re-verifies
  by string equality + fair_value tolerance against a grounding frame that
  is now independently re-derivable from the source-facts cache.

### row_id collision-suffix rule (2026-08-24)

When two rows share the same source anchor
(`source|accession_number|src_context_id` for BDC, or the N-PORT equivalent),
`_assign_row_ids` appends `|dup<k>` to the key before hashing, where k is the
0-based content rank within the collision group. The rank is determined by sorting
on `(fair_value, cost, principal_amount, shares_held, bdc_investment_identifier)`
with nulls-last (stable mergesort). Rank-0 rows keep the bare key unchanged.
Current live artifact has 0 collision groups (780,726 rows, 0 duplicate row_ids),
so no live ids carry suffixes. The suffix is an internal disambiguation device
inside the hash pre-image; only the final `ROW-<hex16>` string is surfaced in
the artifact.

### Build determinism invariant (2026-08-24)

As of the 2026-08-24 tiebreak-hardening migration, `private_markets_holdings.csv`
is content-deterministic: two consecutive `--unified` builds from the same cached
inputs produce byte-identical artifacts (780,726 rows, DuckDB EXCEPT both
directions = 0).

**Standing acceptance test (twin-build gate):** run `--unified` twice, then:

```sql
SELECT COUNT(*) FROM build1 EXCEPT SELECT COUNT(*) FROM build2;  -- must be 0
SELECT COUNT(*) FROM build2 EXCEPT SELECT COUNT(*) FROM build1;  -- must be 0
```

The gate is strictly binary -- any non-zero EXCEPT count is a regression. No
accepted-flip residuals are permitted going forward. The three prior accepted-residual
events (anchor migration 8 flips, provenance step-1 13 CIK-quarters, steps-2-4 17-20
flips) were one-time events resolved by the 2026-08-24 tiebreak migration; they are
documented in the changelog as the "final flip event." Exception: N-PORT blank-holding-id
payload ties (sites S4, S5, S20 in tiebreak_site_inventory.md) remain physical-order and
are deterministic only via stable cached-TSV read order, not content-anchored keys; these
are scheduled as a small re-gated follow-up.

## Position-Level PIK Status

PIK outputs intentionally separate strict current-payment/accrual evidence from schedule-rate proxy metrics:

- `position_pik_status.csv` is one row per holding-quarter. `pik_current_status` is `paying`, `not_paying`, or `unknown` based on N-PORT paid-in-kind flags or BDC position-level PIK income/accrual/capitalization facts. BDC fund-level PIK income does not mark individual positions as paying.
- `pik_terms_flag` and `pik_terms_rate` come from disclosed schedule PIK terms (`pik_rate > 0`). These are useful for research comparability but are not proof of current-period PIK income.
- `pik_schedule_proxy_summary.csv` is the S&P-style public-filing proxy. The headline comparable denominator is BDC direct-lending fair value. Latest rebuild: 2025-12-31 BDC direct lending has 3,939 PIK-terms rows out of 50,200, with PIK-terms FV of $57.27B on $512.58B total FV (11.17%).
- `pik_schedule_proxy_transitions.csv` reports `pik_terms_started`, meaning the same `position_id` moved from no PIK terms to PIK terms. This is a "PIK terms started proxy," not confirmed bad PIK. Confirmed bad PIK needs amendment/origination evidence showing cash-pay terms changed due to borrower stress.

## Unified Holdings -- Validation

`data/output/private_markets_holdings.csv` (718,089 rows). Run via `python -m pipeline.main --unified --validate`.

**Status:** V1-V7 all implemented.
- **V1 (UNCLASSIFIED reduction):** Implemented. 2.5% UNCLASSIFIED (down from 16.3%). BDC financial field fallback, N-PORT issuer defaulting, named co-invest reclassification, expanded fund keyword lists.
- **V2 (Spot-check accuracy):** Manual validation against top BDCs and interval/tender funds HTML/PDF filings.
- **V3 (Aggregate filtering):** Manual pattern discovery and filter expansion.
- **V4 (Cross-source dedup):** Implemented. Jaro-Winkler name matching + FV proximity. BDC source preferred. Output: `holdings_cross_source.csv`.
- **V5 (Coverage):** Implemented. Total assets ratio validation (0.8-1.2x expected). Output: `holdings_coverage.csv`, `holdings_total_assets.csv`.
- **V6 (2-axis classification):** Implemented. Two new columns: `exposure_type` (DIRECT/FUND/LIQUID) and `asset_class` (PRIVATE_CREDIT/PRIVATE_EQUITY/REAL_ESTATE/STRUCTURED_CREDIT/HEDGE_FUND/CASH/OTHER). Expanded `index_classification` with 5 new values (REAL_ESTATE_FUND, DIRECT_REAL_ESTATE, STRUCTURED_CREDIT, HEDGE_FUND, CASH). Uses `nport_asset_cat` (EC/EP/RE/DBT/LON) to refine HEDGE_FUND catch-all. Cross-reference validation (10 rules, runs with `--validate`) + one-time LLM audit (GPT-4o-mini). Output: `classification_validation.csv`, `classification_llm_audit.csv`. NUSS issuer_type is now name-gated (only GOVERNMENT when name has govt keyword; eliminates A1/E1 disagreements). L.P. suffix requires fund co-keyword to trigger FUND reclassification (prevents SPV misclassification). Known residual: 231 E2 disagreements (issuer_category=FUND but exposure_type!=FUND) from three causes: (1) 86 money market fund positions (Goldman Sachs Financial Square, Vanguard Federal Money Market, etc.) that have issuer_category=FUND but exposure_type=LIQUID+asset_class=CASH -- correctly classified for index purposes; (2) 43 BDC aggregate headers ("Investments in Non-Controlled, Non-Affiliated Portfolio Companies") that leaked through aggregate filtering and carry issuer_category=FUND from the affiliation dimension; (3) 90 misc positions where issuer_category=FUND comes from N-PORT PF/RF tagging but the position is a direct lending/equity position in an operating company (e.g., "AffiniPay Intermediate Holdings, LLC" tagged PF by filer).
- **V7 (Affiliation-axis dedup + pct correction):** Implemented. Fixes FV inflation from affiliation-axis duplication (12 CIKs) via 3 mechanisms: affiliation prefix/suffix stripping from `_raw_id`, expanded `_BAD_ISSUER_NAMES_EXACT`, and ROW_NUMBER dedup over (cik, report_date, issuer_name, FV). Corrects `pct_of_net_assets` for multi-dimension-path BDCs (263 CIK-quarters, 116K rows) by recalculating with consolidated `net_assets` from `fund_financials.csv`. Dimension-path duplicates resolved by `no_dim_dupes` CTE (case/punctuation-normalized key excluding cost) + majority casing vote in `_prepare_bdc` + N-PORT cross-quarter dedup via `nport_deduped` CTE. Cost proxy made deterministic with per-tranche partition key (instrument_description + cusip) and fair_value tiebreaker. Tier A within-filing position matching case-folded to recover 2,386 cross-period pairs that previously fell to lower-confidence tiers.

All validation functions use DuckDB SQL (no pandas .iterrows/.apply).

## Provenance Passthrough Columns (step 1, 2026-08-23)

Six new columns appended to `UNIFIED_COLUMNS` after `src_context_id`.
Populated by a single `--unified` rebuild; no re-extraction required.
Upgrade path: these flat-tag columns fold into `src_facts` (per-field
JSON with instance-raw values) when the extractor migration ships.

### Dedup carry-throughs (from `bdc_holdings.csv`)

| Column | Type | Description |
|---|---|---|
| `src_context_count` | str | Number of XBRL contexts deduplicated into this row (`dedupe_context_count` passed through from bdc_holdings). Empty for N-PORT and for BDC rows built before the dedup audit. |
| `src_conflict_fields` | str | Comma-joined field names where deduplicated contexts disagreed on value (`dedupe_conflict_fields` pass-through). Empty when all contexts agreed or only one context existed. |

### Pipeline transform events (`src_transforms`)

Flat `;`-joined ordered list of `field:code` events recording which
pipeline heuristic fired on which field. One entry per branch that fired;
silent when the field passed through unchanged. Event/value CASE
conditions are colocated in `staging_bdc.py` Phase C and in the
`unified_pik_fixed`, `with_cost`, and `with_shares_fix` CTEs.

**Event vocabulary v1** (fires in this field order where applicable):

| Event code | Field | Condition | Effect |
|---|---|---|---|
| `interest_rate:neg_null` | `interest_rate` | raw < 0 | set to NULL |
| `interest_rate:rate_x100` | `interest_rate` | raw <= 0.50 | multiply by 100 |
| `interest_rate:rate_div100` | `interest_rate` | raw >= 50 | divide by 100 |
| `basis_spread:neg_null` | `basis_spread` | raw < 0 | set to NULL |
| `basis_spread:rate_x100` | `basis_spread` | raw <= 0.50 | multiply by 100 |
| `basis_spread:rate_div100` | `basis_spread` | raw >= 50 | divide by 100 |
| `pik_rate:neg_null` | `pik_rate` | raw < 0 | set to NULL |
| `pik_rate:rate_x100` | `pik_rate` | raw <= 0.50 | multiply by 100 |
| `pik_rate:rate_div100` | `pik_rate` | raw >= 50 | divide by 100 |
| `pct_of_net_assets:rate_x100` | `pct_of_net_assets` | raw <= 0.50 | multiply by 100 |
| `pct_of_net_assets:rate_div100` | `pct_of_net_assets` | raw > 50 (strict) | divide by 100 |
| `pik_rate:pik_boundary_div100` | `pik_rate` | pik >= 20 AND pik > interest_rate | divide by 100 (bps->pct fix, appended by `unified_pik_fixed` CTE) |
| `cost:cost_proxy_fv` | `cost` | cost NULL/zero but FV proxy available | cost filled from FV proxy (appended by `with_cost` CTE) |
| `shares_held:pow10_shares` | `shares_held` | shares >30x deviation from issuer median | pow-10 outlier corrected (appended by `with_shares_fix` CTE) |

Note: `pct_of_net_assets` uses a strict `> 50` threshold for the div/100
branch (not `>= 50`); all rate fields use `>= 50`. This asymmetry is
enforced by boundary tests in `tests/test_unified_holdings.py`.

### Class-C pathway enums

| Column | Type | Values | Description |
|---|---|---|---|
| `cost_source` | str | `''` or `'derived_proxy'` | `'derived_proxy'` when `with_cost` CTE filled a NULL/zero cost from the cross-quarter FV proxy. Extends the existing `*_source` enum pattern used by `interest_rate_source`, `basis_spread_source`, etc. |
| `shares_held_source` | str | `''` or `'derived_proxy'` | `'derived_proxy'` when `with_shares_fix` CTE applied a pow-10 correction to an outlier shares value. |

Rows where `cost_source='derived_proxy'` or `shares_held_source='derived_proxy'`
should be excluded from verified-FV numerators that require independently
confirmed position economics (per scoping doc accounting rule).

### Bridge overlay coordinate refs (`src_field_overrides`)

| Column | Type | Grammar | Description |
|---|---|---|---|
| `src_field_overrides` | str | `;`-joined `field=bridge:<sha8>:t<T>:r<R>` | Written by `apply_html_section_bridge_field_overlays` for each field overridden by the HTML-section bridge. `<sha8>` = first 8 chars of the HTML file's sha256; `<T>` = table index; `<R>` = row index within the bridge table. Empty when no bridge overlay applied to this row. |

Example: `maturity_date=bridge:a1b2c3d4:t2:r15` means `maturity_date`
was sourced from the HTML bridge file whose sha256 starts `a1b2c3d4`,
table 2, row 15.

### Coverage stats (2026-08-23 rebuild, 780,726 rows)

Measured from `private_markets_holdings.parquet` via `scratch/2026-08-23_prov_step1/coverage_stats.py`.

| Metric | Count |
|---|---|
| interest_rate:rate_x100 events | 357,833 |
| interest_rate:rate_div100 events | 0 |
| interest_rate:neg_null events | 8 |
| basis_spread:rate_x100 events | 395,670 |
| basis_spread:rate_div100 events | 1 |
| basis_spread:neg_null events | 75 |
| pik_rate:rate_x100 events | 45,940 |
| pik_rate:rate_div100 events | 0 |
| pik_rate:neg_null events | 24 |
| pct_of_net_assets:rate_x100 events | 299,629 |
| pct_of_net_assets:rate_div100 events | 0 |
| pik_rate:pik_boundary_div100 events | 14 |
| cost:cost_proxy_fv events | 252,559 |
| shares_held:pow10_shares events | 2,847 |
| Total rows with any src_transforms event | 730,363 (93.6%) |
| cost_source='derived_proxy' | 252,559 |
| shares_held_source='derived_proxy' | 2,847 (historical baseline ~1,902 pre-rebuild) |
| src_context_count > 1 | 103,365 |
| src_conflict_fields non-empty | 8 |
| src_field_overrides non-empty | 0 (bridge overlay had no matches in this cohort) |

### Known limitations

- **Values populated on rebuild only.** All six provenance columns are empty strings in cached
  `bdc_holdings.csv` rows generated before this migration. They are populated correctly on any
  full `--unified` rebuild from cached extraction data; partial rebuilds or legacy CSV imports
  may leave the columns empty.
- **Ordinal tie-break residual.** The 2026-08-23 rebuild produced four `src_anchor` row_id flips
  at CIK 0000081955 / 2025-12-31 (and cost/shares deltas at ~13 CIK-quarters across 7 CIKs:
  0001321741, 0001414932, 0001578348, 0000081955, 0001655050, 0001496099 et al.) due to DuckDB
  physical row-order perturbation hitting pre-existing order-sensitive tie-breaks in dedup/pick
  layers. All deltas are ACCEPTED as the same residual class as the 8 ordinal flips in the
  2026-08-22 anchor-row_id migration. Future hardening: deterministic ORDER BY in tie-break
  windows (not done in step 1).

---

## Provenance Steps 2-4: src_facts, Re-verifier, Ledger (2026-08-23)

### Eight new columns in `private_markets_holdings.csv` / `.parquet`

Added by the steps-2-4 migration (commits 5b6a4fe..e079407).
All 8 columns are appended after the step-1 provenance columns and before the terminal
`row_id` / `row_id_basis` pair.

| Column | Type | Description |
|---|---|---|
| `src_facts` | str | Per-field JSON blob recording the declared raw XBRL value and extractor-side events for each checkable field. Grammar: see below. Empty string for N-PORT rows, non-cohort BDC rows, and any row whose accession was not in the step-2 re-extraction cohort run. |
| `src_filled_fields` | str | Comma-joined field names that were blank in the winning dedup row but filled from a secondary context during dedup. Records which field values came from a non-primary context. Empty when no fill occurred. Written by the BDC extractor dedup step (`dedupe_filled_fields` passthrough). |
| `corrected_fields` | str | Semicolon-joined field names that were overridden after extraction. The special marker `_row:added` appears when the entire row was added by a correction (not extracted from the filing). Writers: B2 stage-2 leaves (`apply_corrections`), promoted rules (`agent_promoted`), manual row corrections, Agent A spread corrections (`apply_spread_corrections` in `staging_bdc.py`). The iXBRL overlay (`apply_html_section_bridge_field_overlays`) is BLANK-FILL-ONLY by determination and does NOT stamp `corrected_fields`. |
| `fair_value_source` | str | Pathway enum for `fair_value`. Values: `'xbrl_field'` (from XBRL tag), `''` (N-PORT or not re-extracted). |
| `pct_of_net_assets_source` | str | Pathway enum for `pct_of_net_assets`. Values: `'xbrl_field'`, `''`. |
| `pik_rate_source` | str | Pathway enum for `pik_rate`. Values: `'xbrl_field'`, `'identifier_text'` (rate parsed from the investment identifier string), `''`. |
| `principal_amount_source` | str | Pathway enum for `principal_amount`. Values: `'xbrl_field'`, `''`. |
| `bdc_unrealized_gain_loss_source` | str | Pathway enum for `bdc_unrealized_gain_loss`. Reserved; currently always `''` (field not yet in the re-extraction cohort pass). |

### `src_facts` JSON grammar v1

`src_facts` is a JSON object keyed by field name. Each field entry is an object with:

| Key | Present when | Meaning |
|---|---|---|
| `r` | always (for the 4 rate fields: `interest_rate`, `basis_spread`, `pik_rate`, `pct_of_net_assets`) | Declared raw value as extracted from the XBRL instance (before staging transforms). Float or null. For monetary fields (`fair_value`, `cost`, `principal_amount`, `shares_held`) `r` is also written when a concept or transform event was recorded. |
| `c` | when the winning concept is non-exact-canonical OR a transform event fired | Local name of the XBRL concept that won the `_match_concept` lookup. Omitted when the concept exactly matches the canonical name (no disambiguation needed). |
| `x` | when one or more extractor-side scale events fired | JSON array of event codes (strings). Current event vocabulary: `decimals_rescale:10^<k>` (XBRL decimals attribute implied rescale by 10^k); `cik_scale_fix:x1000` (known filer-specific 1000x misscale corrected). |

Empty string (`''`) means no provenance was recorded for this row (N-PORT, non-cohort BDC, or pre-migration row).

Example:
```json
{"fair_value": {"r": 1234567.0, "c": "investmentownedatfairvalue", "x": ["decimals_rescale:10^-3"]},
 "interest_rate": {"r": 0.0875}}
```

### Coverage stats (2026-08-23 step-2 rebuild, 780,726 rows)

Measured from `private_markets_holdings.parquet` via `scratch/2026-08-23_prov_step2/coverage_stats.py`.

| Metric | Count |
|---|---|
| Total rows | 780,726 |
| BDC rows | 560,564 |
| src_facts non-empty (total) | 240,198 |
| src_facts non-empty (BDC only) | 240,198 (cohort latest-period slice of 465,051 bdc-level rows) |
| src_facts with "c": (concept-disambiguated) | 11,435 |
| src_facts with "x": (extractor transform events) | 117 |
| src_filled_fields non-empty | 26,614 |
| corrected_fields non-empty | 273,362 |
| corrected_fields = '_row:added' alone | 262,572 (rows added by corrections, not in the original filing extraction) |

Pathway enum counts:

| Column | Value | Count |
|---|---|---|
| `fair_value_source` | `'xbrl_field'` | 560,406 |
| `fair_value_source` | `''` | 220,320 |
| `pct_of_net_assets_source` | `'xbrl_field'` | 300,027 |
| `pct_of_net_assets_source` | `''` | 480,699 |
| `pik_rate_source` | `'xbrl_field'` | 46,433 |
| `pik_rate_source` | `'identifier_text'` | 1,036 |
| `pik_rate_source` | `''` | 733,257 |
| `principal_amount_source` | `'xbrl_field'` | 459,398 |
| `principal_amount_source` | `''` | 321,328 |
| `bdc_unrealized_gain_loss_source` | `''` | 780,726 (all; field not yet populated) |
| `cost_source` | `'derived_proxy'` | 252,556 |
| `shares_held_source` | `'derived_proxy'` | 2,847 |

Known-empty regions: N-PORT rows (source != 'bdc') have no src_facts, no *_source values.
Non-cohort BDC rows (CIKs outside the 933-filing wrapper cohort) also have empty src_facts.

### Provenance Ledger artifacts (`provenance_ledger.csv`, `provenance_ledger_summary.csv`)

Written by `python -m pipeline.provenance_reverify --cohort [--cheap-only] [--ciks ...] [--out DIR]`.
Config paths: `config.PROVENANCE_LEDGER_FILE`, `config.PROVENANCE_LEDGER_SUMMARY_FILE`.

#### `provenance_ledger.csv` schema (keyed by `row_id`, `field`)

| Column | Type | Description |
|---|---|---|
| `row_id` | str | Unified holdings `row_id` |
| `cik` | str | CIK |
| `accession_number` | str | Filing accession number |
| `report_date` | str | Period of report |
| `src_context_id` | str | XBRL contextRef anchor |
| `src_facts` | str | src_facts JSON for this row (passed through from holdings) |
| `field` | str | Field name being verified |
| `pathway` | str | Pathway enum value for this field (from `*_source` column) |
| `declared_raw` | float or null | `r` value from src_facts for this field |
| `declared_events` | str | `src_transforms` string (staging events declared for this field) |
| `published` | float or null | Published value in unified holdings |
| `expected` | float or null | Expected value computed from declared_raw + all declared multipliers |
| `instance_raw` | float or null | Raw value read directly from the cached iXBRL instance (full tier only; null when not_checked) |
| `cheap_status` | str | Cheap-tier verdict (see enum below) |
| `full_status` | str | Full-tier verdict (see enum below) |
| `reason_code` | str | Deterministic triage code (see reason-code enum below) |
| `holdings_artifact_mtime` | str | ISO-format mtime of the holdings parquet this run was computed against |

#### `provenance_ledger_summary.csv` schema (keyed by `cik`, `report_date`)

| Column | Type | Description |
|---|---|---|
| `cik` | str | CIK |
| `report_date` | str | Period of report |
| `n_fields` | int | Total fair_value field rows for this cik-quarter |
| `n_verified` | int | Count of fair_value rows with reason_code = 'verified' |
| `verified_fv` | float | Sum of `fair_value` (published) over verified rows only |
| `derived_fv` | float | Sum of `fair_value` over derived rows |
| `corrected_fv` | float | Sum of `fair_value` over corrected rows |
| `total_fv` | float | Sum of `fair_value` over all rows for this cik-quarter |
| `verified_fv_share` | float | verified_fv / total_fv |
| (reason_code columns) | int | Wide count columns: one column per reason_code value, counts across ALL fields (not just fair_value) for this cik-quarter |

**Verified-FV accounting rule (scoping doc 2.4, mandatory):** `verified_fv` sums `fair_value`
only over rows whose `fair_value` field's `reason_code` is `'verified'`. `derived` and
`corrected` FV are their own buckets and are NEVER counted in the `verified_fv` numerator.
`verified_fv_share = verified_fv / total_fv`.

#### cheap_status enum (cheap tier)

| Value | Meaning |
|---|---|
| `corrected` | Field listed in `corrected_fields` -- value was overridden post-extraction |
| `derived` | Pathway is `'derived_proxy'` -- cost/shares filled from a heuristic proxy |
| `text_pathway` | Pathway is `'identifier_text'` -- value parsed from the identifier string, not a direct XBRL tag |
| `filled_field` | Field listed in `src_filled_fields` -- filled from a secondary dedup context |
| `merged_conflict` | Field listed in `src_conflict_fields` -- conflicting dedup contexts were merged |
| `no_provenance` | `src_context_id` is empty -- no XBRL anchor available |
| `pass_trivial` | Published is NULL and raw is NULL and no event: field absent from this row (trivially pass for monetary fields; not a declaration failure) |
| `pass` | Computed expected matches published within 1e-6 relative tolerance |
| `fail` | Computed expected does not match published |
| `missing_raw_with_transform` | An event was declared but raw (r) is absent -- incomplete declaration |

#### full_status enum (full tier)

| Value | Meaning |
|---|---|
| `raw_match` | Instance raw read from iXBRL matches declared_raw (or both NULL); declared raw = published after all multipliers |
| `raw_stale` | Instance raw read from iXBRL matches published but differs from declared_raw -- src_facts is stale (re-extraction needed) |
| `published_mismatch` | Instance raw * all multipliers does NOT match published -- regression or extraction bug |
| `anchor_missing` | Context found in the instance but the expected concept element was absent |
| `context_missing` | src_context_id not found in the instance at all |
| `source_unavailable` | Cached iXBRL file not found for this accession |
| `not_checked` | Short-circuited (cheap_status is corrected/derived/text_pathway/filled_field/merged_conflict/no_provenance) or --cheap-only mode |

#### reason_code enum (scoping doc 8.2, deterministic triage)

| reason_code | Derived from | Semantics |
|---|---|---|
| `verified` | full_status = raw_match AND cheap_status NOT in short-circuit set AND cheap_status != fail | Instance raw, declared raw, and published all agree. The strongest provenance signal. |
| `anchor_stale` | full_status = raw_stale | Instance and published agree (correct value), but declared_raw in src_facts is outdated. Re-extraction refreshes it; does NOT indicate a wrong value in production. Distinct from filing_mismatch. |
| `transform_drift` | full_status = raw_match AND cheap_status in (fail, missing_raw_with_transform) | The instance raw matches published but the cheap-tier derivation disagreed -- indicates a staging transform event that is not fully reflected in src_facts. |
| `filing_mismatch` | full_status = published_mismatch | Instance raw * multipliers does not match published. The most actionable finding: either a pipeline regression or an extraction bug. |
| `anchor_missing` | full_status = anchor_missing | Concept element absent from the context. May be a localname mismatch or a context that does not carry this field. |
| `provenance_wrong` | full_status = context_missing | src_context_id does not exist in the instance. Provenance anchor is incorrect. |
| `source_unavailable` | full_status = source_unavailable | Cached filing not present -- filing coverage gap, not a pipeline error. |
| `corrected` | cheap_status = corrected | Value was overridden by a B2/rule/manual correction. Excluded from verified_fv numerator by design. |
| `derived` | cheap_status = derived | Value filled by a heuristic proxy (cost_proxy_fv or shares pow-10 fix). Excluded from verified_fv numerator. |
| `text_pathway` | cheap_status = text_pathway | Value parsed from the identifier string. Not directly iXBRL-verifiable without a grammar-match step. |
| `merged_context_excluded` | cheap_status in (filled_field, merged_conflict) | Field came from a secondary dedup context or a conflicting merge. Provenance is incomplete (only the winning context is anchored). |
| `no_provenance` | cheap_status = no_provenance | Row has no src_context_id anchor -- pre-migration row, N-PORT row, or legacy CSV import. |
| `unchecked_trivial` | all other cases | Field was trivially NULL/absent and not checked by either tier. |

**anchor_stale vs filing_mismatch distinction:** `anchor_stale` means the PUBLISHED value is
correct (instance raw matches it) but the snapshot in src_facts is outdated. A re-extraction
refreshes the declaration without changing the published value. `filing_mismatch` means the
PUBLISHED value differs from the instance -- the pipeline produced a different number than the
filing states, which requires investigation.

Known-empty regions for the ledger: N-PORT rows are excluded from both tiers (cheap tier WHERE
clause filters to `source = 'bdc'`). Non-cohort BDC rows have no src_facts and will fall into
`no_provenance`. The residual `filing_mismatch` / `anchor_stale` population is the primary
product of the re-verifier (it seeds future routing lanes); do not tune the verifier to shrink
it artificially.

### Provenance feed in the shadow validation ledger

The provenance re-verifier is surfaced in the unified shadow ledger via
`scripts/shadow_adapter.py::_provenance_select()`, which aggregates
`provenance_ledger.csv` to one ledger row per `(cik, report_date, reason_code)`.

#### Reason-code to tier/status mapping

| reason_code | tier | status | Queue lane |
|---|---|---|---|
| `filing_mismatch` | tight | fail | blocker |
| `anchor_missing` | tight | fail | blocker |
| `provenance_wrong` | tight | fail | blocker |
| `source_unavailable` | tight | fail | blocker |
| `transform_drift` | tight | fail | blocker |
| `anchor_stale` | weak | warn | review (re-stamp maintenance, not a value error) |
| `no_provenance` | weak | warn | review |
| `text_pathway` | weak | warn | review |
| `merged_context_excluded` | weak | warn | review |
| `verified` | weak | pass | not queued (coverage measurement only) |
| `corrected` | weak | pass | not queued |
| `derived` | weak | pass | not queued |
| `unchecked_trivial` | weak | pass | not queued |

enforcement=advisory for all provenance rows; no gate or acceptance-threshold changes.

#### Dedup audit row (8.1 anti-join)

Before the ledger rows are written, tight-fail rows whose `row_id` matches an
`output_row_id` in `source_reconciliation_detail.csv` (for the same `cik` and
`report_date`, where `blocking_issue` is true) are excluded from the
queue-facing groups and counted in a per-`(cik, report_date)` audit row with
`rule_name = 'provenance_already_queued'`, `tier = 'weak'`, `status = 'pass'`,
`mechanism = 'dedup_source_recon'`. This prevents double-queuing rows already
in the source-reconciliation blocker lane.

The dedup surface is the MATCHED detail file (output_row_id direct identity
join), NOT the source-only file. Source-only rows are unmatched filing facts
whose population is disjoint from the provenance ledger by construction.

#### Evidence-slice contract (Task 2 drill-down)

When a `review_bundle` is assembled for a provenance-engine item, the bundle
includes the evidence rows INLINE inside the bundle JSON as
`evidence_items[?evidence_id=="source_artifact_rows"].data` -- there is no
separate `evidence_slice.csv` file. The rows are keyed by
`(cik, report_date, reason_code)` (matching `rule_name` in the queue item)
and capped at 25 rows per target (the shared `max_rows` default; the
implementation plan said 50 -- the actual default shipped as 25).
Columns retained: `row_id`, `cik`, `report_date`, `reason_code`, `field`,
`declared_raw`, `instance_raw`, `published`, `cheap_status`, `full_status`,
`expected`, `src_context_id`. This slice is the drill-down surface for
B2/B3 workers adjudicating filing_mismatch or anchor_missing packets.

---

## Ledger-Error-Classifier: Verdict Leaf Schema, Re-Derivation Gate, Batch/Manifest Layout

Module: `pipeline/ledger_error_verdict.py`. Builder: `scripts/ledger_error_classifier/build_dispatch.py`.

### Verdict leaf (top-level keys)

| Key | Type | Required | Notes |
|---|---|---|---|
| `review_id` | str | always | Queue review_id (RVQ_BLK_* format) |
| `verdict` | str | always | One of the ADJUDICATIONS enum below |
| `confidence` | float | always | In [0.0, 1.0]; hard error outside range |
| `mechanism` | str | extraction_wrong, parser_drift | Non-empty string describing the defect |
| `culprit_citations` | list | extraction_wrong, parser_drift, filer_error, false_flag | At least 1 entry; each entry: {row_id (str), field (str), declared_raw (float or null), instance_raw (float or null), published (float or null)} |
| `drift_fingerprint` | obj | parser_drift only | {field (str), transform_code (str), affected_row_ids (list, non-empty)} |
| `filer_error_basis` | str | filer_error | Non-empty string explaining why it is a filer error |
| `false_flag_basis` | str | false_flag | Non-empty string explaining why the flag itself is spurious (canary hardening 2026-08-25; false_flag previously required no evidence) |
| `superseding_accession` | str | amended | Non-empty accession number of amending filing |
| `ambiguity_basis` | str | ambiguous | One of: evidence_insufficient, source_unavailable |
| `escalate` | bool | filer_error, ambiguous/source_unavailable | Strongly recommended; omitting produces a validation warning, not a refusal |

### ADJUDICATIONS enum

| Verdict | Meaning |
|---|---|
| `extraction_wrong` | Pipeline extracted the wrong value; citation re-derivable from ledger |
| `parser_drift` | A staging transform was applied incorrectly or inconsistently; drift_fingerprint identifies the future parser-patch-author packet key |
| `filer_error` | The filer reported a wrong value in the filing itself |
| `amended` | A later filing corrects this value; superseding_accession provided |
| `false_flag` | The provenance flag was a false positive; no defect in the pipeline or filer. Requires false_flag_basis + >=1 citation so the spurious-flag claim is itself re-derivable |
| `ambiguous` | Evidence is insufficient or the source filing is unavailable |

### Re-derivation gate contract (`rederive_citations`)

Every `culprit_citations` entry is re-derived from `provenance_ledger.csv` at intake.
A verdict is **REFUSED** if any citation fails any of these checks:

1. The `(row_id, field)` pair exists in the ledger.
2. The pair's `reason_code` is a provenance tight-fail code (PROV_TIGHT_FAIL set).
3. Every cited numeric (`declared_raw`, `instance_raw`, `published`) matches the ledger
   value within relative tolerance 1e-9. `None` in the leaf matches NULL/NaN in the ledger.
4. Duplicate `(row_id, field)` rows in the ledger that DIFFER on any cited numeric produce
   an ambiguous-evidence error (refused). Agreeing duplicates are collapsed to one row.

Verdicts without `culprit_citations` (amended, ambiguous) pass the gate trivially.
The gate is fail-closed: a missing ledger file produces a clear error, never a silent pass.
Packet-scope binding is enforced at batch intake: `validate_dir` reads `cik` and `report_date`
from the worklist and passes them to `rederive_citations` as a `packet`; any citation whose
ledger row belongs to a different `(cik, report_date)` is refused with "citation outside packet
scope" even if all numeric values match. Report dates are normalized to `YYYY-MM-DD` before
comparison (DuckDB type-infers the ledger's `report_date` as TIMESTAMP, which the 2026-08-25
canary showed falsely refusing every citation on a raw string compare).

Provenance reason codes: `pct_sense_check` (added 2026-08-25) is the recompute-vs-disclosure divergence on the derived `pct_of_net_assets` field -- a warn-lane sense-check signal, never packetized as a blocker and never a valid tight-code citation for classifier verdicts. Rounding-consistent pct rows (within +-0.005 pp of the filer's 2-decimal disclosure) verify normally. Divergence profile artifact: `data/output/provenance_pct_sense_check_summary.csv`.

### Escalation sibling convention

When evidence is insufficient or unavailable, the worker writes
`{review_id}.escalation.json` in the verdicts directory instead of a verdict file.
Escalation siblings count as coverage in `validate_dir`.

Shape: `{review_id, ambiguity_basis, escalation_reason (str), confidence (float)}`.

An escalation sibling is not itself gated by `rederive_citations`; it is taken at face
value as a "could not classify" signal.

### Batch and manifest layout

```
data/output/ledger_error_classifier/batch/<batch_id>/
  worklist.csv                   -- selected rows (PROVENANCE_WORKLIST_COLUMNS)
  prompts/<review_id>.md         -- one prompt per selected item
  verdicts/<review_id>.json      -- written by workers (not by the builder)
  manifest.json                  -- latest-wave pointer
  manifest_w<N>.json             -- wave-stamped durable record
```

**`manifest.json` required fields:**

| Field | Value | Notes |
|---|---|---|
| `batch_id` | str | Batch identifier |
| `created_at` | ISO-8601 UTC | Build timestamp |
| `wave` | int | Wave number (starts at 1; increments on rebuild) |
| `worker_python` | str | Python interpreter path |
| `worker_read_dirs` | list[str] | Python import roots + 4 read-only grant dirs |
| `grant_profile` | `read_only_classifier` | No write grants; enforced at dispatch |
| `dispatch_requires` | `admin_shell` | Must not be dispatched from a worker process |
| `n_dispatch` | int | Number of items in this batch |
| `rows` | list[obj] | One entry per item: review_id, cik, report_date, reason_code, prompt_path, bundle_path, verdict_path, lock_key |

`corrections_dir` must NOT appear in the manifest (this lane classifies, it does not author corrections).

**First smoke batch (`lec_smoke_20260825`, 2026-08-25):**
- 10 items, all `reason_code=filing_mismatch`
- All 10 bundles: `evidence_completeness=source_artifact`
- All 10 prompts written; manifest_w1.json committed
- NO dispatch: admin shell required
