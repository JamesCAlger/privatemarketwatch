# Validation Layer Redesign

## Problem Statement

The current validation layer runs 39 rules against the final unified dataset (`private_markets_holdings.csv`, 718K rows), producing 343K row-level entries. Five rules account for ~265K of those entries:

| Rule | Volume | What it documents |
|---|---|---|
| X05 | 62,885 | Floating coupon without basis_spread |
| AGG01 | 60,515 | Suspected aggregate/header row |
| C107 | 57,196 | Negative cost |
| C104 | 42,906 | Zero fair_value |
| C103 | 41,600 | Negative fair_value |

These are **structural characteristics of source data** that the pipeline already handles via compensating logic (Tier 2 rate imputation, cost guards, MIN_FV filters, aggregate filtering). The validation layer re-documents known patterns rather than surfacing unknown issues.

---

## Architectural Recommendations

### 1. Move source characterization upstream; keep only outcome checks on final output

Rules describing "what the source data looks like" belong at the staging boundary — run on `bdc_holdings.csv` and `nport_holdings.csv` before transformation. On the final output, replace them with post-condition checks:

| Instead of | Check this |
|---|---|
| "62K rows lack basis_spread" | "After Tier 2 imputation, how many positions still have no usable rate for income return?" |
| "57K rows have negative cost" | "After cost-gating, did any negative-cost row enter index returns?" |
| "43K rows have zero FV" | "After MIN_FV guard, did any zero-FV position enter position matching?" |
| "60K rows look like aggregates" | "After aggregate filtering, do any CIK-quarters have implausibly few positions relative to total assets?" |

These answer "did anything leak through?" rather than "does the source have known gaps?"

### 2. Add distribution-based anomaly detection instead of static threshold rules

Static thresholds (rate > 25%, FV > $3B) produce stable, predictable volumes every quarter — they never surprise you. A validation layer that never surprises you isn't doing its job.

Add checks that compare this quarter against its own history: position count shifts, FV distribution changes, classification stability, novel pattern emergence.

### 3. Replace row-level WARN entries with aggregate summaries + residual-only detail

Split into two outputs:

**Aggregate quality report** (one row per rule x quarter or rule x CIK x quarter):
```
rule_id | quarter | count | pct_of_total | delta_vs_prior_quarter | status
X05     | 2025q4  | 62885 | 8.8%         | +0.2%                  | STABLE
AGG01   | 2025q4  | 60515 | 8.4%         | -1.1%                  | STABLE
```

**Residual detail layer** (row-level, only for things requiring per-row action):
- Post-condition failures (something leaked through a guard)
- Anomaly detections (distribution shifts, novel patterns)
- FAIL-severity issues

Target: detail CSV drops from 343K rows to ~5-10K, every row actionable.

---

## Signal-to-Noise Calibration via Fail Verification Framework

### Overview

Before promoting any candidate rule to production, use the existing agentic fail verification framework (`pipeline/fail_verification.py`) to measure its true positive rate. This prevents adding rules that produce high-volume noise.

### How the Framework Works

The fail verification harness is a constrained agent-based system for reviewing validation findings:

```
Layer 1: Deterministic Harness
  - Stratified random sampling from rule hits (95% confidence, 10% margin)
  - Evidence bundle generation from cached local artifacts (no network)
  - Verdict JSON schema validation

Layer 2: Evidence Bundles (read-only JSON)
  - Source artifacts (raw XBRL, N-PORT TSV, fund financials)
  - Context (prior quarter positions, nearby positions, filing index)
  - Rule-specific detail (GAV reconciliation, pct sums, etc.)

Layer 3: Agent Verdict (schema-compliant JSON)
  - Epistemic assessment with evidence chain
  - Mechanism documentation (what's actually happening)
  - Anti-sycophancy check (strongest alternative explanation)
```

Each sampled hit receives one of four verdicts:

| Verdict | Meaning |
|---|---|
| CONFIRMED_DATA_ERROR | Rule caught a real problem — output is unsafe |
| CONFIRMED_VALID_EXCEPTION | Condition is real but explainable by source evidence |
| VALIDATOR_FALSE_POSITIVE | Rule or comparison source is wrong |
| INSUFFICIENT_EVIDENCE | Bundle cannot support a defensible conclusion |

### Applying It to Candidate Rules

For each candidate rule in this document:

```
1. Write the rule as a SQL query
2. Run against private_markets_holdings.csv -> N hits
3. Feed hits into build_sample_manifest() -> stratified sample (~95 hits)
4. Feed samples into build_evidence_bundle() -> immutable JSON per hit
5. Agent verifies each hit using structured verdict workflow
6. Aggregate verdicts -> true positive rate
```

### Interpreting Results

| Verdict Distribution | Action |
|---|---|
| >70% CONFIRMED_DATA_ERROR | Promote to FAIL — rule is high-signal |
| >70% combined DATA_ERROR + VALID_EXCEPTION | Promote to WARN — rule catches real patterns worth monitoring |
| >30% VALIDATOR_FALSE_POSITIVE | Rule is too broad — tighten threshold or add guard conditions, re-verify |
| >30% INSUFFICIENT_EVIDENCE | Evidence bundle is inadequate — enrich bundle template, then re-verify |
| <50% DATA_ERROR and no clear refinement path | Retire the candidate — it doesn't carry its weight |

### Evidence Bundle Templates per Rule Category

Each category requires different context in its evidence bundle:

| Category | Bundle contents |
|---|---|
| T (temporal) | Both quarters' positions for the CIK, filing index entries for both quarters, fund_financials for both quarters, raw source rows (XBRL/N-PORT) for both quarters, universe metadata (active/liquidated status) |
| S (strategy) | Fund universe metadata (vehicle_type, strategy description), CIK's full position breakdown by classification, fund_financials (total assets, NAV), top 20 positions by FV with full field detail |
| R (relational) | The flagged row with all fields, its matched pair (if position matching exists), raw source row, adjacent positions from same CIK-quarter, fund_financials for scale context |
| XS (cross-source) | Both source rows (BDC + N-PORT) for the matched position, cross-source dedup report entry, raw source artifacts from both, issuer name variants |
| IDX (index) | Index constituents for both quarters, per-position returns for top/bottom 10, position matching pairs for largest movers, fund-level NAV returns for comparison |
| PC (post-condition) | The downstream artifact row (position_returns or index_returns) showing the leaked item, the guard logic's input data, the pipeline step that should have filtered it |
| F (freshness) | Filing index for the CIK, SEC EDGAR last-filed date, universe metadata (active status), prior quarters' data presence, N-54C/liquidation signals |
| M (matching) | Both positions in the suspect match, their raw source rows, CUSIP/ISIN details, instrument descriptions, FV history across quarters, entity resolution lookup entries |

### Playbook Decision Trees (Examples)

Each rule needs explicit logic the agent follows. Examples for highest-priority rules:

**T01 (Position count stability):**
- Count dropped >50% AND filing index shows a filing exists for this quarter AND raw source has positions -> extraction regression (DATA_ERROR)
- Count dropped >50% AND no filing exists for this quarter -> fund didn't file (VALID_EXCEPTION)
- Count dropped >50% AND fund filed N-54C liquidation -> portfolio wind-down (VALID_EXCEPTION)
- Count dropped >50% AND fund_financials total assets dropped comparably -> real portfolio reduction (VALID_EXCEPTION)
- Count dropped >50% AND raw source shows positions but unified output is missing them -> staging/filter bug (DATA_ERROR)
- Otherwise -> INSUFFICIENT_EVIDENCE

**S01 (Strategy-classification mismatch):**
- Real estate fund has <30% RE classification AND top holdings have "real estate" / "property" / "REIT" in names -> classification keywords missing (DATA_ERROR)
- Real estate fund has <30% RE classification AND top holdings are genuinely non-RE (corporate loans, tech equity) -> fund metadata wrong or fund pivoted strategy (VALID_EXCEPTION)
- Real estate fund has <30% RE classification AND positions lack instrument_description needed for classification -> identifier parsing gap (DATA_ERROR)
- Fund metadata says "real estate" but fund is actually a diversified credit fund that happens to have some RE -> fund metadata too narrow (VALIDATOR_FALSE_POSITIVE)
- Otherwise -> INSUFFICIENT_EVIDENCE

**R07 (FV exceeds fund total assets):**
- Position FV > fund total assets AND raw source confirms the FV value AND fund_financials confirms total assets -> scale/unit mismatch in one source (DATA_ERROR)
- Position FV > fund total assets AND fund_financials is stale (different quarter) -> comparison invalid (VALIDATOR_FALSE_POSITIVE)
- Position FV > fund total assets AND position is from a prior-period comparative row (period < report_date) -> stale row leaked into current-period output (DATA_ERROR)
- Position FV > fund total assets AND fund is a feeder into a master fund (total assets reflects feeder only) -> structural exception (VALID_EXCEPTION)
- Otherwise -> INSUFFICIENT_EVIDENCE

**IDX02 (Return outlier):**
- Index return >15% AND top 5 contributors have FV changes >5x (implausible) -> position-level data error dominating index (DATA_ERROR)
- Index return >15% AND broad market movement confirms (e.g., credit spread tightening quarter) -> real market move (VALID_EXCEPTION)
- Index return >15% AND a single new CIK contributes >50% of the return -> new CIK with bad data (DATA_ERROR)
- Index return >15% AND position matching created duplicate pairs inflating return -> matching bug (DATA_ERROR)
- Otherwise -> INSUFFICIENT_EVIDENCE

### Anti-Reward-Hacking Properties

The framework's design prevents inflated true-positive rates:

1. **Independent reference data** — verdicts cite raw source artifacts the agent cannot edit
2. **Binary evidence gates** — every claim must reference a specific bundle item
3. **Mechanism documentation** — "what's actually happening" must be stated, not just "condition is true"
4. **Schema validation** — verdict JSON is validated against a strict schema before acceptance
5. **Confidence gating** — "high" confidence requires 2+ evidence refs with direct source evidence
6. **INSUFFICIENT_EVIDENCE contract** — must explain why each bundled item was non-determinative

### Calibration Workflow

For the 83 candidate rules in this document, the recommended calibration sequence:

```
Phase A: Implement and run all 83 rules as SQL queries (no verdict yet)
         Output: hit counts per rule, basic population statistics

Phase B: Triage by volume
         - Rules with 0 hits: defer (no signal to verify)
         - Rules with 1-10 hits: exhaustive verification (verify all)
         - Rules with 11-100 hits: standard sampling (95% CI, 10% margin)
         - Rules with >100 hits: stratified sampling by CIK

Phase C: Build evidence bundles (per category template above)

Phase D: Agent verification (batch, ~95 verdicts per rule)

Phase E: Aggregate and decide
         - Promote rules with >70% TP rate
         - Refine rules with 30-70% TP rate (adjust threshold, add guards)
         - Retire rules with <30% TP rate or no refinement path

Phase F: Re-verify refined rules (second pass on adjusted versions)
```

Expected outcome: ~30-40 rules promoted to production (from 83 candidates), each with documented TP rate and known false-positive patterns.

---

## Rule Categories

### Category 1: Temporal Coherence (position-level, QoQ)

Compare a CIK's portfolio in quarter Q against quarter Q-1. Violations suggest extraction failure or pipeline regression, not real portfolio changes.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| T01 | Position count stability | Count changes >50% QoQ without matching event (merger, liquidation N-54C) | Extraction failure or aggregate filter regression |
| T02 | FV mass conservation | Total FV jumps >3x or drops >70% QoQ unless NAV confirms it | Duplicate rows leaked in, or positions dropped |
| T03 | Disappearance without exit | Position present 3+ consecutive quarters, vanishes with no paydown/zero-FV signal | Extraction missed it, not a real exit |
| T04 | Classification shift | >15% of a CIK's positions change `index_classification` between quarters | Upstream reclassification bug, not portfolio rotation |
| T05 | Rate population regression | CIK historically has 80%+ rate fill, drops to 30% in one quarter | XBRL schema change or parser failure |
| T06 | New position without origination signal | Position appears for first time with prior-period cost basis (cost >> 0, no prior quarter presence) | Prior quarter extraction missed it |
| T07 | Maturity cliff | >20% of a CIK's positions mature in same quarter but remain at full FV | Maturity date parsing error or stale data |
| T08 | Issuer name drift | Same position (matched via CUSIP or position_id chain) has issuer_name edit distance >0.3 between quarters | Parser instability or wrong match |
| T09 | Sector composition stability | CIK's GICS sector distribution shifts >25 percentage points QoQ | GICS classification regression or data source change |
| T10 | Average position size shift | Median position FV changes >3x QoQ for same CIK | Unit/scale error in one quarter |

### Category 2: Fund Strategy vs. Holdings Composition

Each fund has a declared strategy. Aggregate composition should be consistent with that strategy.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| S01 | Strategy-classification mismatch | Real estate fund has <30% REAL_ESTATE + REAL_ESTATE_FUND in holdings | Position misclassification or wrong fund metadata |
| S02 | BDC equity overweight | BDC with >40% COMMON_EQUITY by FV (BDCs are credit vehicles by statute) | Identifier parsing error -- equity keywords triggering on debt |
| S03 | Credit fund with majority fund-of-funds | Direct lending BDC has >30% PRIVATE_EQUITY_FUND + PRIVATE_CREDIT_FUND | Aggregate rows leaking through as "fund" positions |
| S04 | Sector concentration implausibility | Fund declares diversified strategy but 80%+ of positions in single GICS sector | GICS classification error (one keyword too broad) |
| S05 | Vehicle type vs. exposure type | BDC with >20% LIQUID exposure (BDCs hold illiquid assets) | Money market / cash positions misweighted or misclassified |
| S06 | Interval fund with majority direct lending | Interval fund declared as equity/multi-asset has >70% DIRECT_LENDING | Classification or fund metadata error |
| S07 | Fund size vs. position count | Fund with >$5B total assets but <50 positions | Aggregate rows counted as positions |
| S08 | Fund size vs. position count (inverse) | Fund with <$100M total assets but >500 positions | Consumer lending leak or duplicate extraction |
| S09 | Tender offer fund with majority public securities | Tender offer fund has >50% positions with CUSIP matching public indices | Shouldn't be in private markets index |
| S10 | Income fund without income-bearing positions | Fund described as income/yield-focused has <50% positions with any rate data | Rate extraction failure for this CIK |

### Category 3: Cross-Field Relational Integrity

Within a single row, certain field combinations are impossible or highly suspect.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| R01 | Maturity before origination | `maturity_date < report_date - 5 years` for current-period position with non-zero FV | Date parsing error (year truncation, MM/DD swap) |
| R02 | Rate changes for fixed coupon | `coupon_type = Fixed` but `interest_rate` differs between quarters for matched position | Coupon type wrong or position match wrong |
| R03 | Cost/FV ratio extreme for performing loan | Non-impaired first lien with cost/FV > 2 | Cost or FV in wrong units (thousands vs actual) |
| R04 | Principal on equity | `index_classification = COMMON_EQUITY` but `principal_amount` populated | Misclassified debt, or principal contains shares |
| R05 | Spread without floating type | `basis_spread > 0` but `coupon_type != Floating` | Coupon type inference missed the spread evidence |
| R06 | Zero rate for credit position | `index_classification = DIRECT_LENDING` with zero interest_rate AND zero basis_spread AND zero pik_rate | Rate extraction failure (not just missing -- explicitly zero) |
| R07 | FV exceeds fund total assets | Single position FV > fund's reported total assets from fund_financials | Scale error or wrong CIK association |
| R08 | Negative shares for long position | `shares_held < 0` for non-short position (no short signal in instrument description) | Sign error in extraction |
| R09 | Maturity in distant future | `maturity_date > report_date + 30 years` for a loan (not equity) | Date parsing error (century wrong) |
| R10 | PIK rate > total rate | `pik_rate > interest_rate` when both populated | PIK field contains total rate, not PIK component |
| R11 | Pct of net assets > position weight | Single position shows `pct_of_net_assets > 25%` but fund has >100 positions | Pct field contains category-level percentage, not position-level |
| R12 | Cost = FV exactly for >10 positions | Same CIK-quarter has >10 positions where cost == FV to the penny | Mark-to-market not applied (stale/placeholder valuations) |
| R13 | Duplicate CUSIP within CIK-quarter | Same CUSIP appears >3 times in a single CIK-quarter | Dedup failure or legitimate multi-tranche (review) |
| R14 | Interest rate > 50% | Rate > 50% for a non-distressed position | Rate in wrong units (bps vs percentage) |
| R15 | Principal = 0 for debt | `index_classification = DIRECT_LENDING` and `principal_amount = 0` (not NULL -- explicitly zero) | Principal extraction error |

### Category 4: Cross-Source Agreement

Where two sources cover the same fund or overlapping positions, they should agree within tolerance.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| XS01 | FV divergence | Same CIK-quarter from BDC + N-PORT, total FV differs >20% | One source stale, or dedup failed |
| XS02 | Position count divergence | Same CIK-quarter from both sources, counts differ >30% | One source includes aggregates the other doesn't |
| XS03 | Classification disagreement | Same position matched cross-source, different `index_classification` | Classification logic is source-dependent (bug) |
| XS04 | Rate disagreement | Same position matched cross-source, interest_rate differs >200bps | One source reporting all-in, other reporting spread |
| XS05 | Issuer name disagreement | Same position (CUSIP match), issuer names have Jaro-Winkler < 0.7 | One source has stale/wrong name |
| XS06 | Maturity disagreement | Same position cross-source, maturity dates differ >90 days | Date parsing error in one source |

### Category 5: Index-Level Sanity

After position-level checks, validate the aggregate index output.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| IDX01 | Constituent count stability | Count drops >20% QoQ for any index | Extraction or matching regression |
| IDX02 | Return outlier | Quarterly return outside [-15%, +15%] for direct lending index | Large positions with bad FV dominating |
| IDX03 | Concentration spike | Top 10 constituents suddenly >25% of index weight | Dedup failure creating mega-positions |
| IDX04 | Income return sign | Negative income return for direct lending index | Fee uplift or rate imputation producing nonsense |
| IDX05 | Index coverage gap | Any quarter has <80% of prior quarter's total FV represented | Position matching dropout |
| IDX06 | Vehicle type dominance shift | Single vehicle type goes from <50% to >80% of index weight in one quarter | New CIK with bad data dominating |
| IDX07 | Return dispersion | Cross-sectional standard deviation of position returns >100% | A few positions with extreme returns (data errors) |
| IDX08 | Zero-return positions | >30% of index constituents have exactly 0% total return | FV not updating (stale marks) |
| IDX09 | Negative weight | Any position enters index with negative weight | Negative FV leaked into weighting |
| IDX10 | Index total return vs. fund-level NAV return | Index total return diverges >500bps from weighted average fund NAV return (from fund_financials) | Systematic bias in position-level return calculation |

### Category 6: Post-Condition Checks (Pipeline Logic Verification)

Verify that the pipeline's compensating logic actually worked -- these replace the current source-characterization WARNs.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| PC01 | Imputation coverage | After Tier 2 rate imputation, >5% of DIRECT_LENDING positions still have no usable rate | Imputation cascade insufficient |
| PC02 | Cost guard effectiveness | Any negative-cost position entered `position_returns.csv` | Cost guard has a gap |
| PC03 | MIN_FV guard effectiveness | Any position with begin_fv < $100K entered index returns | Guard not applied correctly |
| PC04 | Aggregate filter leakage (outcome) | CIK-quarter has <10 positions but >$1B total FV (implausible concentration) | Aggregates counted as positions |
| PC05 | Cross-source dedup effectiveness | Same issuer+FV appears in final output from both sources | Dedup missed a pair |
| PC06 | Affiliation dedup effectiveness | Same position appears 2+ times within CIK-quarter with same FV (dimension path dup) | Dimension-path dedup missed a case |
| PC07 | Pct correction effectiveness | Any CIK-quarter still sums to >250% after pct_of_net_assets correction | Correction logic didn't fire or fund_financials missing |
| PC08 | Schema enforcement pass-through | Any row in final output violates UNIFIED_COLUMNS type contracts | _enforce_schema has a gap |
| PC09 | Position matching orphans | >20% of positions with 2+ quarters of history have no match pair | Matching cascade dropping too many |
| PC10 | Fee uplift sanity | Any CIK's fee uplift >500bps (implausible) | Residual calculation error |
| PC11 | NPORT exclusion effectiveness | Any NPORT_EXCLUDE_CIKS row present in final output | Exclusion filter has a gap |
| PC12 | Consumer lending exclusion | Any CONSUMER_LENDING_EXCLUDE_CIKS position in frontend JSON | Frontend filter has a gap |

### Category 7: Data Completeness and Freshness

Track whether the pipeline is receiving and processing expected data volumes.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| F01 | Missing quarter | Expected quarter (based on calendar) has no data for a CIK that filed in prior quarters | Filing not downloaded or not parsed |
| F02 | Stale filing | CIK's most recent data is >2 quarters old but CIK is still active (no N-54C liquidation) | Pipeline missed recent filings |
| F03 | Source coverage drop | Total CIK count in unified output drops vs prior run | Universe discovery regression |
| F04 | N-PORT quarterly gap | N-PORT CIK present in Q-1 and Q+1 but absent in Q | TSV download missed a quarter |
| F05 | BDC filing gap | BDC CIK with 10-K but missing surrounding 10-Qs | Filing index incomplete |
| F06 | Fund financials coverage | CIK in unified holdings but missing from fund_financials.csv | Companyfacts/N-CEN extraction missed it |
| F07 | GICS coverage | >10% of DIRECT_LENDING positions have no GICS sector | GICS classification not running or failing |
| F08 | Entity resolution coverage | >5% of positions have no entity_id | Entity resolution regression |
| F09 | HTML template coverage | BDC CIK has pre-XBRL filings but no template (and not in exclusion list) | Template creation needed |
| F10 | New CIK without validation | CIK appears for first time in unified output without any manual spot-check | New filer needs review |

### Category 8: Identifier and Matching Quality

Validate that position identifiers are being parsed and matched correctly.

| ID | Rule | Logic | Signal |
|---|---|---|---|
| M01 | CUSIP collision | Same CUSIP mapped to positions with Jaro-Winkler issuer_name similarity < 0.5 | CUSIP reuse or extraction error |
| M02 | Match pair FV divergence | Matched position pair has begin_fv/end_fv ratio > 10 or < 0.1 (excluding known exits) | Wrong match -- different positions paired |
| M03 | 1:many match over cap | Position matched to >3 others in adjacent quarter | Matching cascade too permissive for this name |
| M04 | Identifier parse failure rate | >20% of a CIK's positions have issuer_name == raw investment_identifier (no parsing happened) | Parser doesn't handle this CIK's format |
| M05 | Entity resolution fragmentation | Same issuer (by CUSIP) has >3 distinct entity_ids | Entity resolution not merging correctly |
| M06 | Instrument description empty | >50% of a CIK's DIRECT_LENDING positions have no instrument_description | Identifier parsing not splitting name from instrument type |
| M07 | CUSIP coverage drop | CIK historically has >60% CUSIP fill, drops to <20% | Source format changed or extraction regression |
| M08 | Position ID chain break | Position_id chain has gap (present in Q1, Q3 but not Q2 despite same CUSIP active) | Matching missed the Q2 link |
| M09 | Duplicate entity_id within CIK-quarter for different issuers | Two positions with different issuer names resolve to same entity_id | Entity resolution too aggressive |
| M10 | Name normalization collision | Two clearly different companies normalize to same string | Normalization too aggressive (stripping meaningful tokens) |

---

## Implementation Notes

All rules above are implementable as DuckDB SQL queries against already-loaded data. No new infrastructure required -- they join existing tables (`private_markets_holdings`, `fund_financials`, `combined_universe`, `position_matches`, `position_returns`, `index_returns`).

### Output Structure

```
data/output/
  validation_aggregate.csv      # One row per (rule_id, quarter) -- trend tracking
  validation_detail.csv         # Row-level findings, only actionable items
  validation_postconditions.csv # PC01-PC12 pass/fail per run
```

### Priority Order for Implementation

**Highest leverage (implement first):**
1. T01, T02 -- temporal coherence catches extraction regressions immediately
2. S01, S02, S03 -- strategy vs. composition catches systematic misclassification
3. PC01-PC06 -- post-condition checks replace the current 265K noisy WARNs
4. IDX01, IDX02, IDX04 -- index-level sanity is the final quality gate

**Second tier:**
5. R03, R07, R11, R14 -- scale/unit errors that silently corrupt returns
6. M01, M02, M04 -- matching quality directly affects index accuracy
7. F01, F02, F03 -- freshness ensures no silent data loss

**Third tier (completeness):**
8. Remaining temporal rules (T03-T10)
9. Remaining relational rules (R01-R15)
10. Cross-source and identifier quality (XS01-XS06, M05-M10)

---

## Calibration-First Implementation Sequence

### Phase A: Implement All 83 Rules as SQL (No Verdicts)

Write each rule as a DuckDB query. Output: hit counts per rule and basic population statistics. This tells you which rules have signal to verify and which have zero hits (defer).

### Phase B: Triage by Volume

| Hit count | Approach |
|---|---|
| 0 hits | Defer — no signal to verify; rule may become relevant as data grows |
| 1-10 hits | Exhaustive verification (verify all hits) |
| 11-100 hits | Standard sampling (95% CI, 10% margin of error) |
| >100 hits | Stratified sampling by CIK (prevent single-CIK dominance) |

### Phase C: Build Evidence Bundles

Use category-specific bundle templates (see "Evidence Bundle Templates per Rule Category" above). Each bundle is an immutable JSON containing all context the agent needs to reach a verdict without network access.

### Phase D: Agent Verification

Batch verification using the existing harness workflow. Each sampled hit receives a structured verdict with mechanism documentation, evidence citations, and anti-sycophancy check.

### Phase E: Aggregate and Decide

| TP Rate | Action |
|---|---|
| >70% DATA_ERROR | Promote to FAIL severity |
| >70% combined DATA_ERROR + VALID_EXCEPTION | Promote to WARN severity |
| 30-70% mixed | Refine rule (adjust threshold, add guard conditions) |
| <30% DATA_ERROR | Retire candidate or restructure fundamentally |

### Phase F: Re-verify Refined Rules

Rules that were refined in Phase E get a second verification pass with the adjusted logic. Only rules that pass both rounds get promoted.

### Expected Outcome

~30-40 rules promoted to production from 83 candidates, each with:
- Documented true positive rate
- Known false positive patterns (documented as VALID_EXCEPTION playbook entries)
- Evidence bundle template locked in
- Playbook decision tree for ongoing verification

---

## Summary Statistics

| Category | Rules | What it catches |
|---|---|---|
| T: Temporal Coherence | 10 | QoQ regressions, extraction failures, stale data |
| S: Strategy vs. Composition | 10 | Systematic misclassification, fund metadata errors |
| R: Cross-Field Relational | 15 | Unit errors, impossible field combinations, parsing bugs |
| XS: Cross-Source Agreement | 6 | Dedup failures, source staleness, parser inconsistency |
| IDX: Index-Level Sanity | 10 | Return errors, concentration bugs, weighting issues |
| PC: Post-Condition Checks | 12 | Guards that didn't fire, logic gaps, filter leakage |
| F: Completeness/Freshness | 10 | Missing data, coverage drops, stale filings |
| M: Identifier/Matching | 10 | Wrong matches, CUSIP collisions, entity resolution errors |
| **Total** | **83** | |
