# Wrapper System — Current State & Unification Plan

**Date:** 2026-06-01
**Scope:** Non-listed BDCs only (v1 website pared back to this segment)

---

## 1. Non-Listed BDC Universe

| Metric | Count |
|---|---|
| Active BDCs total | 220 |
| Exchange-listed (have SEC ticker) | 52 |
| Non-listed (no SEC ticker) | 168 |
| Non-listed with extracted XBRL holdings | 121 |
| Non-listed with no holdings data (shells/dormant/pre-XBRL) | 47 |
| Non-listed with >= 4 quarters of data | 107 |
| Non-listed with >= 8 quarters of data | 85 |

The substantive non-listed universe is ~107-121 funds. The top by AUM are institutional private credit vehicles: Blackstone Private Credit (~$67B/qtr), Owl Rock Core Income, HPS Corporate Lending, Apollo Debt Solutions, Ares Strategic Income, Goldman Sachs Private Credit, etc.

The 47 with no data are mostly pre-2010 shells that never rescinded N-54A elections, SBICs filing differently, or very new entities without a first 10-K.

---

## 2. What Exists Today

### 2.1 Oracle / Verification Layer

The verification backbone is the strongest part of the existing infrastructure.

| Component | Module | Status |
|---|---|---|
| FV reconciliation (position sum vs fund-level) | `source_reconciliation.py`, `wrapper_content_signatures.py` | Working. Per-CIK-quarter, 5%/$5M tolerance. |
| QoQ position count band | `validate_holdings.py`, `wrapper_content_signatures.py` | Working. Two implementations with different thresholds. |
| Scale detection | `staging_bdc.py` Phase A, `source_reconciliation.py` | Working but rule-based (median comparison). Not yet anchored to XBRL `decimals` attribute. |
| Subtotal detection by arithmetic | `staging_bdc.py` Phase A | Partial. Only catches exact-sum matches within same-prefix groups. |
| Source-to-output row matching | `source_reconciliation.py` | Deep. 10 tiered match strategies from exact dimension path down to partial name + FV. |
| Rate sanity | `wrapper_content_signatures.py` | Defined in v2 schema, implemented. |

### 2.2 Per-CIK Wrapper Definitions (Two-Tier, Not Unified)

**Tier A — Python `WrapperSpec` objects** in `pipeline/bdc_xbrl_wrapper.py`:

8 CIKs have in-code wrapper specs. Each defines prefix rules (dimension path to instrument family), leaf markers per family, aggregate markers, entity signals. These handle **dispatch** — classifying identifiers into `position_leaf`, `issuer_rollup`, `category_rollup`, `total_rollup`, `aggregate`, `non_private_market`, or `unclassified`.

| CIK | Entity | Prefix Rules | Notes |
|---|---|---|---|
| 0001786108 | Trinity Capital | `Portfolio Company Debt/Warrant/Equity Securities` | Family-specific leaf markers |
| 0001377936 | Saratoga Investment | Affiliation-prefix categories | Pct-prefix parsing, bare category detection |
| 0001920145 | Goldman Sachs Private Credit | `Investment Debt/Equity Investments` | Multiple prefix variants |
| 0001572694 | Goldman Sachs BDC | Same Goldman prefix rules | |
| 0001920453 | Fidelity Private Credit | `Investments Investments` | Extended non-private-market markers |
| 0001508655 | Sixth Street Specialty | `Debt/Equity Investments` | |
| 0001925309 | Sixth Street Lending Partners | Same Sixth Street prefixes | |
| 0001918712 | Ares Strategic Income | Empty prefix rules | Uses default leaf markers only |

**Tier B — JSON v2 definitions** in `data/overrides/bdc_xbrl_wrappers/`:

2 CIKs have JSON wrapper files:

- **Trinity (0001786108):** v1 schema only. Basic required/forbidden markers for leaf vs rollup. Does not include content signatures or invariants.
- **Ares Strategic Income (0001918712):** v2 schema. Comprehensive: archetypes (senior_secured_debt, equity, clo, warrant), field signatures (interest_rate 1-30%, basis_spread 1-15%, fair_value required), invariants (FV reconciliation, QoQ position count, rate sanity), 5 known edge cases.

**The two tiers are not connected.** Tier A handles dispatch (leaf vs rollup classification). Tier B handles content validation (are field values within expected ranges for each archetype). Neither covers both.

### 2.3 Per-CIK Hardcoded Logic in Global Staging Code

`staging_bdc.py` contains per-CIK SQL that should migrate into wrapper definitions:

| CIK | Entity | Logic | Mechanism |
|---|---|---|---|
| 0001377936 | Saratoga | 12 issuer bridge records | Exact raw_id match -> corrected issuer/instrument |
| 0001849894 | MSD Investment | Hierarchy prefix stripping | Regex: `Investments Investments - Non-Control... [Type] [Industry]` |
| 0001633336, 0001954360 | Crescent Capital | Hierarchy extraction | Regex: `Investments [Country] [Type] [Industry] [Issuer] Investment Type [Instrument]` |
| 0001508655, 0001925309, 0001920453 | Sixth Street, Fidelity | Hierarchy leaf guard | No-dash positions with instrument + rate/maturity evidence |
| (pattern-based) | Blue Owl, Goldman, PennantPark | Pct-prefix hierarchy parsing | Multi-segment percentage-of-NAV category prefixes |

### 2.4 Wrapper Oracle / Profiling Harness

`pipeline/bdc_xbrl_wrapper_oracle.py` provides:
- `build_residual_wrapper_queue()` — ranks CIKs by unresolved source-only blockers
- `build_wrapper_profile_for_cik()` — profiles blocker signatures
- `run_wrapper_oracle_trial()` — full trial: source facts, reconciliation, content signatures, baseline comparison
- CLI: `--cik`, `--all-supported`, `--queue-from-residuals`

This is a diagnostic harness, not an agent inductor. It measures how well existing wrappers explain source facts but does not propose or generate new wrapper rules.

### 2.5 Test Coverage

| Test file | Tests | Coverage |
|---|---|---|
| `test_bdc_xbrl_wrapper.py` | 24 | Identifier classification, disposition, position keys |
| `test_bdc_xbrl_wrapper_oracle.py` | 10 | Oracle summary, cleared rollups, mechanism classification |
| **Total** | **34** | |

---

## 3. Ares Strategic Income — QoQ Validation Results

Ares (0001918712) is the only CIK that has been through the full QoQ drift validation. 13 quarters from 2023-03-31 through 2026-03-31.

### 3.1 Content Signatures

**100% pass rate, zero violations across all 13 quarters and 8,894 total rows.**

| Quarter | Total Rows | Classified | Unclassified | Unclassified % | Pass Rate |
|---|---|---|---|---|---|
| 2023-03-31 | 150 | 148 | 2 | 1.3% | 1.0 |
| 2023-06-30 | 200 | 193 | 7 | 3.5% | 1.0 |
| 2023-12-31 | 338 | 322 | 16 | 4.7% | 1.0 |
| 2024-06-30 | 519 | 482 | 37 | 7.1% | 1.0 |
| 2024-12-31 | 795 | 725 | 70 | 8.8% | 1.0 |
| 2025-06-30 | 1,019 | 935 | 84 | 8.2% | 1.0 |
| 2025-12-31 | 1,223 | 1,111 | 112 | 9.2% | 1.0 |
| 2026-03-31 | 1,260 | 1,129 | 131 | 10.4% | 1.0 |

### 3.2 FV Reconciliation

**12 of 12 quarters pass. 11 are exact matches ($0 difference).**

One exception: 2025-03-31 position sum $13.626B vs fund FV $13.655B — $28.7M gap (0.21%). Within tolerance. Likely a filtered position (subtotal, cash, or unfunded commitment) included in fund-level FV but excluded from position-level extraction.

2026-03-31 has no fund financials row available for comparison.

### 3.3 Edge Cases

Four known patterns, all behaving as documented:

| Edge Case | Disposition | Trend |
|---|---|---|
| `pipe_delimited_rows` | warn | First seen 2025-12-31 (1 match), grew to 4 by 2026-03-31 |
| `preferred_equity_with_dividend_rate` | expected | Grows from 1 (2023-06-30) to 14 (2026-03-31), tracking expanding preferred equity book |
| `bare_fund_vehicle` | expected | 2 matches in latest two quarters (ADLP LLC) |
| `debt_with_unit_count` | expected | Stable 1-3 matches per quarter (Steward Partners) |

### 3.4 What Ares Reveals

**Untracked metric: unclassified row coverage regression.** The most important signal in the Ares results is not a failure — it is an absence. The unclassified fraction grew from 1.3% to 10.4% over 13 quarters. These rows bypass all archetype-level content signature checks. They are not flagged as violations, not counted as failures, and not reported as drift. The current system has no mechanism to detect or alert on this coverage erosion.

This is a general gap, not Ares-specific. Any filer whose instrument vocabulary expands beyond the wrapper's keyword set will experience silent coverage regression. The wrapper will report 100% pass rate while checking an increasingly small fraction of rows.

**Required addition to the unified wrapper:** an `unclassified_rate` invariant that flags when the fraction of rows not matching any archetype exceeds a per-CIK threshold (e.g., 5%). This turns a silent gap into a trigger for wrapper repair.

**Pipe delimiter drift is the canonical structural-change signal.** It appeared in 2025-12-31 and is growing. Reconciliation cannot catch it (FV sums are unaffected). The edge case rule flags it as `warn` but does not trigger any action. In the unified system, this should be a trigger for wrapper version update (new `alternate_delimiters` entry or identifier_format change).

**Content signatures are too permissive to stress-test.** Interest rate 1-30%, basis spread 1-15%, fair value "required" — these ranges are broad enough that nothing trips them. This is correct for a first pass (catch gross errors) but insufficient for production validation. Tightening should happen after seeing what breaks across diverse filers, not in isolation on the cleanest filer.

---

## 4. The Unification

### 4.1 What Unification Means

Merge the two-tier wrapper system (Python `WrapperSpec` dispatch + JSON v2 content signatures) and the per-CIK staging SQL into a single per-CIK JSON definition that covers:

1. **Dispatch** — dimension-path routing: which identifiers are leaf positions, rollups, aggregates, non-private-market
2. **Hierarchy extraction** — how to parse issuer/instrument from composite identifiers (prefix stripping, regex extraction, delimiter splitting, bridge overrides)
3. **Content signatures** — per-archetype field-value validation
4. **Invariants** — fund-level reconciliation, QoQ stability, rate sanity, unclassified rate ceiling
5. **Edge cases** — known anomalies with disposition and detection pattern

### 4.2 Verification Strategy

For each of the 8 CIKs with existing Python `WrapperSpec` definitions, the unified wrapper must produce identical dispatch output (wrapper_disposition, wrapper_rule_id, wrapper_family, wrapper_position_key) to the current hardcoded path. Any divergence is a unification bug, not ambiguity.

For the staging SQL per-CIK logic (Saratoga bridges, MSD hierarchy, Crescent extraction, Sixth Street leaf guards), the unified wrapper must produce the same issuer/instrument parsing results as the current SQL. Test by running source reconciliation before and after: matched row count and match tier distribution must not regress.

### 4.3 What the Unified Schema Must Express

Based on the 8 existing `WrapperSpec` CIKs + 6 staging SQL CIK-specific branches, the operators needed are:

| Operator | Driven By | Example |
|---|---|---|
| Prefix-based family dispatch | Trinity, Sixth Street, Goldman | `"Portfolio Company Debt Securities" -> debt` |
| Affiliation-prefix category dispatch | Saratoga | `"Non-Control/Non-Affiliate investments" -> mixed` |
| Leaf marker detection (keyword in identifier) | All 8 CIKs | `"maturity date"`, `"interest rate"`, `"sofr"` in identifier -> leaf |
| Aggregate marker detection | All 8 CIKs | `"total investments"`, `"subtotal"` -> aggregate |
| Entity signal regex (issuer rollup detection) | All 8 CIKs | `\b(Inc|LLC|Corp|LP)\b` in suffix -> issuer rollup |
| Hierarchy prefix stripping (regex) | MSD | Strip `Investments Investments - Non-Control... [Type] [Industry]` |
| Hierarchy extraction (regex groups) | Crescent | Extract issuer + instrument from `Investments [Country] [Type] [Industry] [Issuer] Investment Type [Instrument]` |
| Hierarchy leaf guard (no-dash + evidence) | Sixth Street, Fidelity | Allow no-dash positions when instrument + rate/maturity evidence present |
| Issuer bridge overrides | Saratoga | Exact raw_id match -> corrected issuer + instrument |
| Identifier delimiter + field order | Ares | `", "` delimiter, `[issuer, instrument, ref_rate, rate, maturity]` |
| Archetype classification (keywords) | Ares | `"First lien senior secured loan"` -> senior_secured_debt |
| Field signatures (numeric_range, regex, enum, presence) | Ares | interest_rate 1-30%, basis_spread forbidden for equity |
| FV reconciliation invariant | Ares | Sum position FV vs fund-level FV, 5%/$5M tolerance |
| QoQ position count invariant | Ares | Max 2x increase, min 0.5x decrease |
| Rate sanity invariant | Ares | 1-30% range |
| **Unclassified rate invariant** | **Ares finding** | **Flag when >N% of rows match no archetype** |
| Edge case patterns | Ares | Regex-detected known anomalies with disposition |
| Non-private-market markers | All 8 CIKs | `"money market"`, `"cash"`, `"u.s. treasury"` -> exclude |

### 4.4 What Is NOT Built Yet

- Agent induction loop (cold-start wrapper generation, minimal-delta repair)
- Wrapper versioning with diffable deltas (v1->v2 with human-readable diff history)
- Concept inventory tracking per CIK (flag when XBRL concepts appear/disappear)
- Cross-quarter dimension-path stability checking
- `unparsed_remainder` population (field exists but not populated by most specs)
- Promotion pipeline (CIK-specific rule recurring across filers -> global default)
- Coverage gating (fraction of rows multiply-confirmed before wrapper promoted from provisional)
- Wrappers for 113 of 121 non-listed BDCs with data
