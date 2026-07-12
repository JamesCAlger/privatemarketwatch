# Position-Level Data Assurance: End-to-End Workflow

Last updated: 2026-06-11

This document describes how raw XBRL tags become production position-level data, what validation exists at each stage, and what failure modes the system does and does not yet catch.

---

## Pipeline Overview

```
SEC EDGAR (XBRL filings)
  │
  │  Stage 1: Discovery & Download
  │  bdc_filings.py
  │  SEC submissions API → filings index → cached XBRL XML
  │
  ▼
Raw XBRL XML (cached on disk)
  │
  │  Stage 2: Fact Extraction
  │  bdc_filings.py (_extract_investment_facts)
  │  XML contexts + facts → one row per investment per period
  │
  ▼
bdc_holdings.csv (~840K rows)
  │
  ├───────────────────────────────────────────────────┐
  │                                                   │
  │  Stage 3: Staging                                 │  Source Reconciliation
  │  staging_bdc.py + bdc_xbrl_wrapper.py             │  source_reconciliation.py
  │  Raw identifier → issuer_name +                   │
  │    instrument_description                         │  Every XBRL fact accounted for:
  │  Wrapper dispatch → leaf / aggregate / non-private │  matched, documented, or blocking
  │  Position key creation                            │
  │                                                   │  Blocking rows = measured extraction gap
  │  Stage 4: Unified Holdings                        │
  │  unified_holdings.py (DuckDB CTEs)                │  Current: 2,255 blocking / 901K total
  │  Deduplicate, classify, normalize, filter         │  (0.25% unreconciled)
  │                                                   │
  ▼                                                   │
private_markets_holdings.csv (~718K rows)             │
  │                                                   │
  │  ◄── blocking rows feed back ─────────────────────┘
  │
  │  Stage 5: Position Matching
  │  position_matching.py
  │  6-tier cascade: A → B1 → B1b → B2 → C → D → E
  │  Output: position_id linking same position across quarters
  │
  ▼
position_matches.csv (~143K match pairs)
  │
  │  Stage 6: Export
  │  export/fund_exports.py + export/index_exports.py
  │  Unified holdings → per-fund JSON, index constituents
  │
  ▼
frontend/public/data/*.json
```

---

## Stage 1: Discovery & Download

**Module:** `pipeline/bdc_filings.py`

**Process:**
1. Query SEC submissions API for all BDC CIKs, retrieving 10-K/10-Q filing metadata
2. Cache filings index to `data/output/bdc_filings_index.csv`
3. For each filing, locate the XBRL instance document (iXBRL variant, direct XML, or index-page fallback)
4. Download and cache to `data/raw/filings/bdc_xbrl/{cik_stripped}/{accession}.xml`

**Guardrails:**
- Rate limiter: 10 requests/second (SEC fair access policy)
- Local cache: once downloaded, never re-downloaded unless explicitly requested
- Idempotent: same filing always produces same cached file

**Failure modes caught:** Network errors, missing XBRL documents, filing index staleness

**Failure modes NOT caught:** SEC serving corrupted or incomplete XML (no checksum verification); filings that exist but are not discoverable via the submissions API (rare)

---

## Stage 2: XBRL Fact Extraction

**Module:** `pipeline/bdc_filings.py` (`_extract_investment_facts`)

**Process:**
1. Parse XML to extract `<context>` definitions — each context carries a period (instant or duration) and optional dimensions (investment identifier axis, affiliation axis, etc.)
2. Extract facts — each XBRL element (e.g., `<arcc:InvestmentOwnedAtFairValue contextRef="c-26">4500000</arcc:InvestmentOwnedAtFairValue>`) is matched to a context
3. Map XBRL concept names to output columns via substring matching (longest-match-first):

| XBRL concept pattern | Output column |
|---|---|
| `investmentownedatfairvalue` | `fair_value` |
| `investmentownedatcost` | `cost` |
| `investmentownedbalanceprincipalamount` | `principal_amount` |
| `investmentinterestratepaidinkind` | `pik_rate` |
| `investmentinterestrate` | `interest_rate` |
| `investmentbasisspread*` | `basis_spread` |
| `investmentmaturitydate` | `maturity_date` |
| `investmentownedpercentofnetassets` | `pct_of_net_assets` |

4. Apply scale normalization: detect mixed-decimals filings (e.g., most facts at `decimals="-3"` but outliers at `decimals="-6"`) and rescale outliers to match dominant scale
5. Apply per-CIK deterministic scale corrections for known filer bugs

**Example — Ares Capital, "2U, Inc." position:**

```xml
<!-- Context defines the investment identifier dimension -->
<context id="c-26">
  <period><instant>2023-06-30</instant></period>
  <segment>
    <xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis">
      <domain>Non-control/Non-affiliate Investments 2U, Inc.,
              First lien senior secured loan Variable Index Spread (L+6.50%)
              Rate Cash 11.32% Maturity 3/12/2028</domain>
    </xbrldi:typedMember>
  </segment>
</context>

<!-- Facts reference the context -->
<arcc:InvestmentOwnedAtFairValue contextRef="c-26">4500000</arcc:InvestmentOwnedAtFairValue>
<arcc:InvestmentInterestRate contextRef="c-26">0.1132</arcc:InvestmentInterestRate>
<arcc:InvestmentOwnedBalancePrincipalAmount contextRef="c-26">4700000</arcc:InvestmentOwnedBalancePrincipalAmount>
```

**Output:** `bdc_holdings.csv` row:
```
investment_identifier: "Non-control/Non-affiliate Investments 2U, Inc., First lien
    senior secured loan Variable Index Spread (L+6.50%) Rate Cash 11.32%
    Rate PIK 0.00% Investment date 3/12/2021 Maturity 3/12/2028"
fair_value:        4,500,000
interest_rate:     0.1132
principal_amount:  4,700,000
```

**Guardrails:**
- Concept map ordering prevents PIK rate from being captured as interest rate
- Mixed-decimals normalization prevents 1000x scale errors
- Per-CIK corrections for documented filer scale bugs

**Failure modes caught:** Concept name collision (longest-match-first), mixed decimal scales, known per-CIK scale anomalies

**Failure modes NOT caught:**
- A filer using a novel XBRL concept name not in the concept map (fact silently dropped)
- A filer switching rate scale (e.g., reporting 5.0% as 0.05 instead of 5.0) without triggering the mixed-decimals heuristic
- Inline XBRL (iXBRL) rendering differences between filers that affect XML structure

---

## Stage 3: Staging (Identifier Parsing)

**Modules:** `pipeline/staging_bdc.py`, `pipeline/bdc_xbrl_wrapper.py`, `pipeline/bdc_identifier.py`

**Process:**
1. **Wrapper dispatch**: Per-CIK JSON config (`data/overrides/bdc_xbrl_wrappers/{cik}.json`) classifies each raw identifier into:
   - `debt_position_leaf` / `equity_position_leaf` — individual position (keep)
   - `debt_total_rollup` / `debt_issuer_rollup` / `aggregate` — subtotal/category (filter)
   - `non_private_market` — cash, money market, Treasury (filter)

2. **Identifier parsing**: The raw `investment_identifier` (a freeform string containing entity name + instrument + rates + dates) is split into structured fields:
   - `issuer_name` — entity name only (e.g., "2U, Inc.")
   - `instrument_description` — deal structure (e.g., "First lien senior secured loan")
   - Parsing method depends on CIK: pipe-delimited (SLR format), comma-delimited, or wrapper-specific regex

3. **Affiliation prefix stripping**: Removes category prefixes ("Non-control/Non-affiliate Investments") that are XBRL axis labels, not part of the entity name

4. **Position key creation**: Synthetic key for cross-quarter matching = normalized `issuer_name + instrument_description`. Weak keys (< 12 chars, generic tokens only) are repaired using raw identifier fallback.

**Example — Ares Capital, "2U, Inc." position:**

```
Raw:  "Non-control/Non-affiliate Investments 2U, Inc., First lien
       senior secured loan Variable Index Spread (L+6.50%)..."

After prefix strip:  "2U, Inc., First lien senior secured loan..."
After parsing:
  issuer_name:            "2U, Inc."
  instrument_description: "First lien senior secured loan"
  position_key:           "2u inc first lien senior secured loan"
  wrapper_disposition:    "debt_position_leaf"
```

**Example — Subtotal row filtered out:**

```
Raw:  "Total Non-control/Non-affiliate Investments"
Dispatch:  matches aggregate_marker "total" → wrapper_disposition = "aggregate"
Result:    filtered out, never reaches unified holdings
```

**Guardrails:**
- Per-CIK wrapper configs handle filer-specific identifier formats
- Aggregate markers prevent subtotal rows from leaking into position data
- Position key repair prevents generic keys from causing false matches downstream

**Failure modes caught:** Known aggregate patterns, known prefix formats, weak position keys

**Failure modes NOT caught:**
- Filer changes identifier format between quarters without updating the wrapper (Stepstone bug: 7,414 rows mis-parsed for 10 quarters). **Plan A segment assertions** address this.
- Filer uses GICS sector labels as issuer_name. **Plan A I09 check** addresses this.
- Novel aggregate naming patterns not in the wrapper's marker list

---

## Source Reconciliation (Parallel Validation Layer)

**Module:** `pipeline/source_reconciliation.py`

This is the primary extraction-quality audit. It runs independently of the production pipeline and compares every raw XBRL fact against unified holdings.

**Process:**
1. Extract all investment-context facts from cached XBRL (the "source side")
2. Load all unified BDC holdings rows (the "output side")
3. Match source to output using a 3-tier cascade:
   - Exact dimension match (CIK + period + context_id + identifier)
   - Staging-normalized identifier match
   - Fair-value + cost numeric identity match (1:1)
4. Classify every source fact into one of:
   - **Matched** — corresponding unified holdings row found
   - **Documented non-blocking** — row intentionally absent (comparative period, duplicate dimension path, aggregate rollup, non-private-market, amended filing superseded)
   - **Blocking** — source fact with position-level evidence (issuer, rate, maturity) that has no corresponding output row

**Current state (as of 2026-06-11):**

| Category | Rows | % of total |
|---|---|---|
| Matched | ~548K | ~60.8% |
| Documented non-blocking | ~351K | ~38.9% |
| Blocking | 2,255 | 0.25% |
| **Total source facts** | **~901K** | **100%** |

**Blocking mechanism breakdown:**

| Mechanism | Rows | FV ($B) |
|---|---|---|
| blocking_source_pct_leaf_parser_mismatch | 1,176 | 14.3 |
| blocking_source_position_like_parser_mismatch | 742 | — |
| blocking_source_short_plain_unresolved | 141 | — |
| blocking_source_unclassifiable_after_review | 134 | — |
| blocking_identifier_parse_artifact | 9 | — |
| Other blocking | 53 | — |

**Integration with wrapper skill:** The wrapper oracle (`bdc_xbrl_wrapper_oracle.py`) runs source reconciliation during trial rebuilds. A wrapper cannot be promoted if it increases blocking rows or blocking FV. This is the promotion gate.

**Guardrails:** Every XBRL fact must be accounted for. The blocking count is the measured gap between what the filer reported and what the pipeline extracted.

**Failure modes caught:** Missing positions (source fact exists, pipeline row doesn't), value mismatches (FV/cost differ materially between source and output)

**Failure modes NOT caught:** Positions present in both source and output but with wrong field values (e.g., interest_rate extracted from wrong XBRL concept). Source reconciliation matches on FV+cost identity, so if FV is correct but rate is wrong, the row is "matched" despite the field error.

---

## Stage 4: Unified Holdings Construction

**Module:** `pipeline/unified_holdings.py` (DuckDB SQL CTEs)

**Process:**
1. Ingest staged BDC holdings + N-PORT holdings
2. **Dimension-path deduplication**: When the same position appears under multiple XBRL contexts (e.g., affiliation axis), keep the highest-scoring row (most non-null fields)
3. **Aggregate leak filtering**: Second pass using keyword patterns + per-CIK reviewed aggregate lists
4. **Classification**:
   - Asset category: `debt`, `equity`, `warrant`, `hybrid`, `other`
   - Issuer category: `operating_company`, `fund`, `spv`, `other`
   - Index classification: `DIRECT_LENDING`, `PRIVATE_EQUITY`, `REAL_ESTATE_FUND`, etc.
   - Asset class: `PRIVATE_CREDIT`, `PRIVATE_EQUITY`, `REAL_ESTATE`, etc.
5. **Normalization**: Canonical issuer name casing (mode frequency), PIK rate boundary fix (bps → %), pct_of_net_assets recalculation from fund financials

**Example — "2U, Inc." after unified construction:**

```
source:                   bdc
cik:                      0001287750
issuer_name:              2U, Inc.
instrument_description:   First lien senior secured loan
fair_value:               4,500,000
interest_rate:            0.1132
principal_amount:         4,700,000
maturity_date:            2028-03-12
index_classification:     DIRECT_LENDING
asset_class:              PRIVATE_CREDIT
position_key:             2u inc first lien senior secured loan
bdc_investment_identifier: <original raw string preserved for audit>
```

**Guardrails:**
- Oracle A checks: arithmetic invariants (sum of FV vs reported totals)
- Oracle B checks: structural integrity (no duplicate dimension paths after dedup)
- Oracle C checks: content expectations (debt has rate, equity has shares)
- Oracle G checks: aggregate leak detection
- Validation rules: 7 categories of position-construction checks

**Failure modes caught:** Subtotal leakage, dimension duplicates, classification errors for known patterns, PIK rate scale errors, pct_of_net_assets inflation

**Failure modes NOT caught:**
- Classification errors for novel instrument types not covered by existing rules
- Issuer category errors where entity signals are ambiguous (e.g., SPV vs operating company)
- Positions where all fields are plausible but the entity name is wrong (Stepstone GICS bug)

---

## Stage 5: Position Matching

**Module:** `pipeline/position_matching.py`

**Process:** Links the same investment position across consecutive reporting periods using a 6-tier cascade. Each tier operates with strict 1:1 row-ID enforcement.

| Tier | Method | Match key | FV ratio guard | Calibrated error rate |
|---|---|---|---|---|
| A | Within-filing comparatives | Same accession + identifier | 1/100 to 100 | 2.5% |
| B1 | Exact CUSIP | CUSIP (excluding placeholders) | 1/50 to 50 | — |
| B1b | Position key | Strong position key (≥12 chars, ≥3 words) | 1/50 to 50 | 2.5% |
| B2 | Exact issuer name | Lowercased issuer_name | 1/50 to 50 | 7.6% |
| C | Regex-normalized name | Stripped punctuation, suffixes, ordinals | 1/50 to 50 | 30.0% |
| D | Jaro-Winkler fuzzy | JW similarity ≥ 0.88, prefix blocking | 1/5 to 5 | 22.5% |
| E | Entity fingerprint | entity_id + classification + principal bucket | 1/5 to 5 | 23.3% |

**Example — "2U, Inc." across quarters:**

```
2022-12-31  "2U, Inc."  FV=$4.8M  ──┐ Tier A (same-accession comparative)
2023-03-31  "2U, Inc."  FV=$4.6M  ──┘──┐ Tier B2 (exact issuer_name)
2023-06-30  "2U, Inc."  FV=$4.5M  ─────┘──┐ Tier B2
2023-09-30  "2U, Inc."  FV=$4.2M  ────────┘

All four rows assigned the same position_id.
```

**Tiebreakers** (when multiple candidates exist at same tier): FV proximity → attribute penalties (lien, classification, coupon mismatch) → maturity proximity

**Guardrails:**
- Per-tier FV ratio guards (reject extreme FV changes)
- 1:1 enforcement (no position matched to multiple rows)
- Oracle J01: position key stability ≥ 70% B1b for wrapped CIKs
- Oracle J03: fuzzy fallback rate ≤ 10%
- Oracle J05: attribute discontinuity flags on lower-tier matches
- Oracle J06: semantic validation of D/E matches
- Calibration framework: 600-pair stratified sample with ground-truth verdicts

**Planned guardrails (Plans A+B):**
- Classification flip veto (100% precision in calibration)
- Maturity mismatch veto for C/D/E (74.6% precision)
- Instrument sub-type continuity gate
- Suffix coexistence check for tranche renumbering
- J07/J08 informational oracle checks

**Failure modes caught (current):** Extreme FV ratio matches, name divergence, classification flips (flagged but not vetoed), maturity mismatches (flagged but not vetoed)

**Failure modes NOT caught (current, addressed by Plan B):**
- Classification flip: flagged but not rejected (6 errors in calibration, 100% were wrong)
- Maturity mismatch in C/D/E: flagged but not rejected (47 errors in calibration)
- Instrument sub-type confusion: revolver matched to term loan (6 errors)
- Tranche renumbering: suffix number changes across quarters (26 errors)
- Refinancing: new facility with same entity name, different terms (8 errors)

**Failure modes NOT caught (current, addressed by Plan A):**
- GICS sector label as issuer_name inflating entity fingerprint matches (21 errors)
- Structural prefix text inflating fuzzy similarity scores (24 errors)
- Category subtotal rows entering position matching (2 errors)

---

## Stage 6: Export to Frontend

**Modules:** `pipeline/export/fund_exports.py`, `pipeline/export/index_exports.py`

**Process:**
1. Read unified holdings + position matches
2. Compute per-fund analytics: portfolio composition, concentration, yield, leverage
3. Compute index-level analytics: constituent returns, sector breakdown, credit quality
4. Serialize to JSON: `frontend/public/data/fund_details/{cik}.json`, `fund_list.json`, `index_returns.json`, etc.

**Guardrails:**
- `scripts/diff_outputs.py --semantic` compares current export against baseline
- Test monkeypatch guard prevents accidental writes during test runs (1,956 tests, zero production files modified)
- Frontend build (`npm run build`) validates TypeScript types against JSON shape

**Failure modes caught:** Schema drift (TypeScript compilation), semantic drift (diff against baseline)

**Failure modes NOT caught:** Correct-shaped but wrong-valued JSON (e.g., yield computed from wrong rate column). The export is a mechanical projection of unified holdings — garbage in, garbage out. All data quality must be established before this stage.

---

## Oracle Check Inventory

10 categories of deterministic post-pipeline checks:

| Category | Purpose | Example checks |
|---|---|---|
| **A: Arithmetic** | Derived identities | A01 subtotal arithmetic, A04 GAV reconciliation, A07 pct sum |
| **B: Structural** | Hierarchy integrity | B01 leaf completeness, B02 unique position keys |
| **C: Content** | Field expectations | C01 debt has rate, C04 equity has shares |
| **D: QoQ Stability** | Temporal drift | D01 count band, D02 FV stability, D06 continuity |
| **E: Cross-Reference** | Fund financials | E02 holdings vs total assets, E04 NAV sanity |
| **F: Data Quality** | Field sanity | F01 rate range, F03 FV sign, F12 rate scale |
| **G: Aggregate Leak** | Subtotal detection | G01 keyword, G02 arithmetic subtotal, G03 headers |
| **H: Source Completeness** | Coverage | H01 fact coverage, H05 source/unified gap |
| **I: Wrapper-Specific** | Extraction quality | I02 leaf marker accuracy, I05 content signatures |
| **J: Position Matching** | Match quality | J01 key stability, J03 fuzzy rate, J05/J06 flags |

---

## Calibration Results (2026-06-11 Baseline)

600-pair stratified sample, all reviewed:

| Metric | Value |
|---|---|
| Weighted error rate | 4.2% (95% CI: 1.2%-7.1%) |
| Correct matches | 488 |
| Wrong entity | 43 |
| Wrong tranche | 42 |
| Ambiguous | 21 |
| Wrong instrument | 6 |

**Error pattern classification (112 errors):**

| Pattern | Errors | Root cause layer |
|---|---|---|
| GICS sector label as issuer_name | 21 | Wrapper (staging parser) |
| Structural prefix inflating fuzzy score | 24 | Wrapper (staging parser) |
| Tranche renumbering / suffix mismatch | 26 | Matching algorithm |
| Multiple tranches, name insufficient | 14 | Matching algorithm |
| Refinancing as continuity | 8 | Matching algorithm |
| Facility type confusion | 6 | Matching algorithm |
| Category subtotals in matching | 2 | Wrapper (aggregate dispatch) |
| Multi-tranche swap | 4 | Matching algorithm |

**Strongest heuristic flags:**

| Flag | Precision | False-negative rate |
|---|---|---|
| flag_classification_flip | 100% (6/6) | Low (catches equity-debt swaps) |
| flag_maturity_mismatch | 74.6% (47/63) | Moderate (misses same-maturity wrong tranches) |
| flag_rate_discontinuity | 66.7% (4/6) | High (most errors don't have rate jumps) |
| flag_fv_ratio_extreme | 62.5% (5/8) | High (most errors have plausible FV ratios) |

---

## Comprehensive Failure Mode Register

### Failure modes with existing detection

| ID | Failure mode | Detection mechanism | Residual risk |
|---|---|---|---|
| F01 | Position missing from holdings | Source reconciliation blocking rows | Low — 2,255 blocking rows actively tracked |
| F02 | Subtotal leaking into holdings | Oracle G01/G02 + wrapper aggregate dispatch | Low — keyword + arithmetic detection |
| F03 | Duplicate dimension paths | Dedup CTE + Oracle B01 | Low — systematic dedup |
| F04 | Wrong classification | Oracle C01/C04 + validation rules | Medium — novel instrument types may be misclassified |
| F05 | Rate scale error (bps vs %) | Oracle F01/F12 + PIK boundary fix | Low — heuristic catches extremes |
| F06 | Mixed-decimals scale error | Extraction normalization | Low — automated detection |
| F07 | pct_of_net_assets inflation | Recalculation from fund financials | Low — independent denominator |
| F08 | Wrong position matched (A/B tiers) | Calibration (2.5% error rate) | Low — high-confidence tiers |
| F09 | Wrong position matched (C/D/E tiers) | Calibration (22-30% error rate) + J05/J06 | High — **Plans A+B target this** |
| F10 | Filer format change | Unparsed remainder spike (indirect) | Medium — **Plan A segment assertions** |

### Failure modes with planned detection (Plans A/B/C)

| ID | Failure mode | Planned detection | Plan |
|---|---|---|---|
| F11 | GICS sector label as issuer_name | I09 oracle check | A |
| F12 | Structural prefix text inflating matches | CIK wrapper prefix stripping | A |
| F13 | Filer format change (segment count/content) | Segment assertions + I08 oracle | A |
| F14 | Classification flip in match | Hard veto in position_matching.py | B |
| F15 | Maturity mismatch in C/D/E match | Hard veto in position_matching.py | B |
| F16 | Instrument sub-type mismatch | Continuity gate in position_matching.py | B |
| F17 | Tranche renumbering causing wrong match | Suffix coexistence check | B |
| F18 | Refinancing treated as continuity | J08 oracle (informational) | B |

### Failure modes with NO current or planned detection

| ID | Failure mode | Why not caught | Potential mitigation |
|---|---|---|---|
| F19 | Novel XBRL concept name not in concept map | Fact silently dropped; source reconciliation catches the missing row but not the cause | Concept coverage audit against XBRL taxonomy |
| F20 | Rate reported at wrong scale without triggering heuristic (e.g., 5.0% as 0.05) | Passes F01 range check if within 0-30 | Cross-check rate against basis_spread + reference rate; flag when rate < spread |
| F21 | Field-level error on a matched row (e.g., correct FV but wrong rate) | Source reconciliation matches on FV identity, not field-by-field | Field-level source reconciliation (compare all numeric fields, not just FV+cost) |
| F22 | New CIK with no wrapper | No segment assertions, no wrapper dispatch | Wrapper worklist auto-detection for new filers; default conservative parsing |
| F23 | Correct-shaped but wrong-valued frontend JSON | Export is mechanical projection; no independent frontend validation | Frontend data quality dashboard comparing key metrics against fund reports |
| F24 | Systematic bias in calibration sample (CIK under-represented) | Stratified by tier, not by CIK | Add CIK stratification layer to calibration sample design |
| F25 | Position matched correctly but to wrong quarter (off-by-one period) | Span guard (2-13 months) catches extreme cases | Stricter period-pair validation; require exact quarter adjacency |
| F26 | Issuer name correct but instrument_description wrong | No field-level instrument validation against source | Parse instrument from raw identifier independently and compare |
| F27 | Cost basis reported inconsistently across quarters for same position | No QoQ cost stability check | Oracle D-category check for cost drift on matched positions |

---

## Data Quality Contracts

### What the system can currently state

1. **Extraction completeness**: For every CIK-quarter, X source facts existed in the XBRL filing, Y were matched to unified holdings, Z were documented non-blocking, and W are blocking residuals. Current blocking rate: 0.25%.

2. **Position matching accuracy**: Based on 600-pair stratified calibration, the weighted error rate is 4.2% (95% CI: 1.2%-7.1%). Error is concentrated in tiers C (30%), D (22.5%), E (23.3%); tiers A/B are ≤2.5%.

3. **Classification coverage**: <2.5% of positions are UNCLASSIFIED after all rules.

4. **Determinism**: Same cached XBRL + same config = same output. No random seeds, all SQL.

5. **Traceability**: Every unified holdings row preserves the original `bdc_investment_identifier` and `accession_number` for audit back to the SEC filing.

### What the system cannot currently state

1. **Field-level accuracy**: No systematic check that `interest_rate` in unified holdings equals the rate in the source filing, position by position. Source reconciliation verifies FV+cost identity but not other fields.

2. **Position matching accuracy after fixes**: The 4.2% error rate is pre-Plan-A/B. Post-fix rate is projected at <2% but unmeasured until Plan C re-calibration.

3. **Completeness for unwrapped CIKs**: CIKs without wrappers use generic parsing only. No segment assertions or CIK-specific validation.

4. **Frontend accuracy**: No independent verification that frontend JSON matches unified holdings for every metric. The export is assumed correct if the underlying CSV is correct.

---

## Appendix: Source Reconciliation Blocking Rows (2,255 rows across 71 funds)

### By Fund (top 25)

| Rank | CIK | Entity | Blocking rows | Quarters affected |
|------|-----|--------|---------------|-------------------|
| 1 | 0001280784 | Hercules Capital | 200 | 13 |
| 2 | 0001278752 | MidCap Financial Investment Corp | 179 | 9 |
| 3 | 0001383414 | PennantPark Investment Corp | 175 | 13 |
| 4 | 0001370755 | BlackRock TCP Capital Corp | 168 | 13 |
| 5 | 0001572694 | Goldman Sachs BDC | 150 | 13 |
| 6 | 0001794776 | Palmer Square Capital BDC | 146 | 6 |
| 7 | 0001633336 | Crescent Capital BDC | 106 | 13 |
| 8 | 0001504619 | PennantPark Floating Rate Capital | 83 | 9 |
| 9 | 0001372807 | BCP Investment Corp | 82 | 11 |
| 10 | 0001865174 | Goldman Sachs Middle Market Lending II | 59 | 10 |
| 11 | 0002006758 | MidCap Apollo Institutional Private Lending | 58 | 5 |
| 12 | 0001646614 | Silver Point Specialty Lending | 51 | 8 |
| 13 | 0001834543 | BlackRock Direct Lending Corp | 50 | 7 |
| 14 | 0001950976 | 26North BDC | 47 | 7 |
| 15 | 0001948368 | Phillip Street BDC | 46 | 10 |
| 16 | 0001743415 | Owl Rock Technology Finance Corp | 40 | 6 |
| 17 | 0001860424 | TCW Direct Lending VIII | 37 | 3 |
| 18 | 0001674760 | Rand Capital Corp | 34 | 13 |
| 19 | 0001825265 | Owl Rock Core Income Corp | 33 | 6 |
| 20 | 0001959568 | Prospect Capital Corp | 33 | 3 |
| 21 | 0001715933 | TCW Direct Lending VII | 30 | 4 |
| 22 | 0001916608 | Ares Private Credit Corp | 24 | 3 |
| 23 | 0001988280 | Bain Capital Specialty Finance II | 24 | 3 |
| 24 | 0001784700 | Prospect Capital Holdings | 21 | 3 |
| 25 | 0001841514 | Prospect Capital Strategic Lending | 20 | 3 |

Top 15 funds account for 1,600 rows (71% of all blockers).

### By Mechanism

| Mechanism | Rows | % | CIKs affected | Description |
|---|---|---|---|---|
| `blocking_source_pct_leaf_parser_mismatch` | 1,185 | 52.5% | 33 | Source row has issuer/rate/maturity leaf evidence + terminal pct_of_net_assets but no matching output row. Parser failed to extract it. |
| `blocking_source_position_like_parser_mismatch` | 742 | 32.9% | 47 | Source row has company/instrument/rate signals indicating a real position but no 1:1 output identity found. |
| `blocking_source_short_plain_unresolved` | 141 | 6.3% | 27 | Short plain-text identifier, indeterminate whether position or category. |
| `blocking_source_unclassifiable_after_review` | 134 | 5.9% | 18 | Ambiguous after deterministic classification; requires manual review. |
| `blocking_source_pct_ambiguous_after_review` | 44 | 2.0% | 7 | Terminal-pct rows ambiguous between position and rollup after review. |
| `blocking_numeric_already_matched_output_alias` | 9 | 0.4% | 1 | Output row matched to a different source fact; this source fact is an alias. Rand Capital only. |

The two parser-mismatch mechanisms account for 85.4% of all blocking rows. These are positions that exist in the raw XBRL filing but that the staging parser did not correctly extract into unified holdings.

### Key Fund-Level Patterns

**Hercules Capital (200 rows):** 180 `pct_leaf_parser_mismatch`, 20 `position_like`. Persistent across all 13 quarters. The pct-leaf mechanism dominates, suggesting the parser handles the identifier structure but misses a subset of rows with terminal percentage fields.

**MidCap Financial (179 rows):** 178 `position_like_parser_mismatch`. Nearly all blockers are position-like rows the parser doesn't recognize. 9 quarters affected.

**PennantPark Investment (175 rows):** 150 `pct_leaf`, 12 `position_like`, 9 `pct_ambiguous`, 4 `unclassifiable`. Mixed mechanisms across all 13 quarters.

**BlackRock TCP Capital (168 rows):** 167 `pct_leaf_parser_mismatch`. Almost exclusively one mechanism, all 13 quarters. Likely a systematic parser gap for this CIK's identifier format.

**Goldman Sachs BDC (150 rows):** 90 `pct_leaf`, 60 `position_like`. This CIK is also one of the 3 CIKs with structural prefix text causing position matching errors (Plan A). The blocking rows and the matching errors likely share a root cause: the embedded sector/instrument prefix confuses both the parser and the matcher.

**Palmer Square Capital BDC (146 rows):** 146 `pct_leaf_parser_mismatch`. Entirely one mechanism, 6 quarters. A newer filer (fewer quarters) with a consistent parser gap.
