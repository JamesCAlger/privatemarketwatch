# Private Credit Quality & Underwriting Analysis

**Date:** 2026-04-18
**Data:** SEC EDGAR XBRL + N-PORT filings, 2022q1-2025q4 (BDC), 2019q4-2025q4 (N-PORT)
**Coverage:** ~590K positions across 237 CIKs after consumer lending exclusion

## Executive Summary

Analysis of SEC regulatory filings reveals a private credit market exhibiting classic late-cycle dynamics: deteriorating underwriting standards masked by lagging credit indicators. Spreads have compressed 100bps, PIK share of total coupon has grown from 21.7% to 29.1%, and recent vintages show elevated initial impairment -- yet default rates (0.16%) and payment arrears (0.04%) remain near historic lows. This pattern is consistent with the hypothesis that credit quality is declining while observable distress metrics have yet to reflect it.

---

## 1. Spread Compression

**Finding:** Median basis spread has compressed ~100bps over 3 years.

| Period | Median Basis Spread | Decline |
|--------|-------------------|---------|
| 2022q4 | ~6.00% | -- |
| 2023q4 | ~5.50% | -50bps |
| 2024q4 | ~5.25% | -75bps |
| 2025q4 | ~5.00% | -100bps |

**Context:** This compression reflects:
- Massive capital inflow into private credit ($1T to $3T AUM in 5 years)
- Larger, more established borrowers entering the private market
- Convergence with syndicated loan spreads
- Sponsor leverage over lenders in competitive deal processes

**Comparison to public markets:** Public high-yield OAS compressed harder (from ~500bps to ~280bps, or -41%) than private credit (-17%), suggesting private credit has been more disciplined but is following the same trajectory.

## 2. Rate Decomposition

**Finding:** All-in rate decline of ~260bps decomposes into:
- ~100bps from spread compression (lender pricing decisions)
- ~170bps from base rate decline (SOFR from 5.4% to 4.2% post-Fed cuts)

The spread component is the signal for underwriting quality -- base rate changes are macroeconomic and affect all credit equally. The 100bps spread compression represents a meaningful reduction in compensation for credit risk.

## 3. PIK Rate Analysis

**Finding:** PIK (Payment-In-Kind) share of total coupon has grown materially.

| Metric | 2022 | 2025q4 | Change |
|--------|------|--------|--------|
| PIK share of total coupon | 21.7% | 29.1% | +7.4pp |
| Positions with PIK | ~18% | ~24% | +6pp |

**Why this matters:** PIK defers cash interest payments, converting them to additional principal. It is both:
- A **risk indicator** -- distressed borrowers negotiate PIK to preserve cash flow
- An **underwriting trend** -- new deals increasingly include PIK toggles as a feature

Rising PIK prevalence is a classic late-cycle signal. In the 2007-2008 cycle, PIK proliferation preceded defaults by 12-18 months.

**Public market comparison:** 41% of large BSL (broadly syndicated loan) deals now have PIK toggle provisions, suggesting this is a market-wide trend.

## 4. Impairment Analysis (FV/Cost Ratio)

**Finding:** Fair value markdowns are increasing, especially in recent vintages.

| Period | % Positions with FV/Cost < 0.90 |
|--------|-------------------------------|
| 2023q1 | 12.4% |
| 2024q1 | 16.8% |
| 2025q4 | 21.0% |

**Interpretation:** A FV/cost ratio below 0.90 indicates the position has been marked down at least 10% from cost basis. The upward trend shows managers are recognizing credit deterioration through marks, but this is a lagging indicator -- managers have discretion over Level 3 valuations and typically mark gradually.

## 5. Vintage Analysis

**Finding:** Recent cohorts show elevated initial impairment.

| Vintage | Initial Impairment (FV/Cost < 0.90) | Observation |
|---------|-------------------------------------|-------------|
| 2022 | 8-10% | Healthy |
| 2023 | 12-14% | Rising |
| 2024 | 20-22% | Elevated |
| 2025 | 20-22% | Elevated |

2024-2025 vintages are entering the portfolio at nearly double the initial impairment rate of 2022 vintages. This could reflect:
- Weaker underwriting in later deals (aggressive pricing, higher leverage)
- Broader deterioration in borrower quality as cycle matures
- More aggressive deployment (pressure to deploy $3T in committed capital)

## 6. Seniority Hierarchy

**Finding:** Impairment rates follow expected seniority hierarchy.

| Seniority | Impairment Rate (FV/Cost < 0.90) | Expected |
|-----------|----------------------------------|----------|
| First Lien | 8.0% | Lowest |
| Second Lien | 18.6% | Higher |
| Mezzanine | 22.8% | Highest |

This confirms the dataset is internally consistent -- senior secured positions perform better than subordinated, as expected. The absolute levels are elevated across all tiers compared to historical norms.

## 7. N-PORT Credit Flags (Lagging Indicators)

**Finding:** Default and arrears flags remain at historic lows despite leading indicator deterioration.

| Flag | Rate | Interpretation |
|------|------|---------------|
| IS_DEFAULT | 0.16% | Near zero defaults |
| ARE_ANY_INTEREST_PAYMENT_IN_ARREARS | 0.04% | Almost no missed payments |
| IS_ANY_PORTION_INTEREST_PAID_IN_KIND | 3.2% | Low PIK flag (note: this differs from BDC PIK because N-PORT only flags positions currently paying PIK, not those with PIK provisions) |

**The gap between leading and lagging indicators is the key finding.** Spreads are compressing, PIK provisions are increasing, and recent vintages are underperforming -- but actual defaults and payment failures remain minimal. This is exactly the pattern expected in late-cycle credit: risk builds invisibly until a trigger (recession, rate shock, refinancing wall) converts latent stress into realized losses.

## 8. Non-Accrual Status (BDC XBRL)

**Finding:** Limited but directional data from XBRL-tagged non-accrual disclosures.

- 769 data points across ~10-15 CIKs (coverage too sparse for reliable trend)
- 245 percentage-at-fair-value data points
- Range: 0.3% to 13.7% of portfolio at fair value on non-accrual
- Multiple non-standardized concept names (PercentageOfInvestmentsInNonAccrualStatusAtFairValue, InvestmentsOnNonaccrualStatusFairValue, etc.)

**Limitation:** Non-accrual XBRL tagging is not standardized and only a fraction of BDCs tag this concept. Not sufficient for a standalone trend chart but directionally supportive.

---

## Public Market Comparison

### Spread Comparison

| Market | 2022 Spread | 2025 Spread | Compression |
|--------|-------------|-------------|-------------|
| Private Credit (BDC basis_spread) | ~6.00% | ~5.00% | -17% |
| Public HY (ICE BofA OAS) | ~480bps | ~280bps | -41% |
| BSL (LSTA) | ~450bps | ~350bps | -22% |

Private credit has compressed less than public markets, maintaining a ~150-170bps premium. However, the premium has narrowed from its historical average of ~250-300bps.

### Why Private Credit Spreads Were Higher

The private credit spread premium reflects real compensation for:

| Risk Factor | Estimated Premium | Status |
|-------------|------------------|--------|
| Illiquidity | 100-150bps | Compressing (secondary market emerging) |
| Complexity / documentation | 25-50bps | Stable |
| Information asymmetry | 50-75bps | Compressing (market maturation) |
| Concentration risk | 25-50bps | Stable |
| Limited competition (structural) | 100-150bps | Gone (capital inflow eliminated this) |

**Justified premium estimate:** ~200-275bps. Actual premium: ~170bps. The market is pricing through fundamentals.

### Default Rates

| Market | Default Rate | Source |
|--------|-------------|--------|
| Private Credit | 1.8-2.5% | Proskauer Private Credit Default Index |
| BSL (LSTA) | 1.2% | Morningstar LSTA |
| All Corporate (Moody's) | 5.3% | Trailing 12-month issuer-weighted |
| Our Data (N-PORT IS_DEFAULT) | 0.16% | Position-weighted, likely understated |

### Recovery Rates -- THE BIG STORY

| Market | Historical Recovery | Current Recovery | Change |
|--------|-------------------|------------------|--------|
| BSL First Lien | 76% | 39% | -37pp collapse |
| Private Credit First Lien | 65-75% | 65-75% | Stable |

This is arguably the most important finding for the comparison. Public BSL first-lien recoveries have collapsed from 76% to 39% (per Fitch/Moody's data), while private credit recoveries have remained stable at 65-75%. The divergence is driven by:

1. **Covenant erosion in BSL:** 93% of BSL loans are now covenant-lite (vs ~60% for private credit)
2. **Liability management exercises (LME):** Borrowers use aggressive tactics to restructure public loans at steep discounts, bypassing senior lenders
3. **Structural subordination:** Multi-tranche BSL deals create more layers eating into recovery
4. **Private credit covenant retention:** Direct lenders maintain financial covenants, giving them earlier intervention rights

### Underwriting Quality

| Metric | BSL/Public | Private Credit |
|--------|-----------|---------------|
| Covenant-lite share | 93% | ~40% |
| 1st lien leverage | 4.9x | 4.0-4.5x |
| Interest coverage | 2.34x | 2.5-3.0x |
| PIK toggle prevalence | 41% of large deals | 24% of positions |

---

## Thesis Assessment

**User's hypothesis: "Late-cycle, underwriting quality declining, but lagging indicators (FV marks, defaults) still look OK."**

**Verdict: Confirmed with nuance.**

The data supports this thesis across multiple dimensions:

1. **Spread compression** (-100bps) = less compensation for risk
2. **PIK proliferation** (+7.4pp share of coupon) = cash flow stress accumulating
3. **Vintage deterioration** (2024-2025 at 2x impairment vs 2022) = weaker new deals
4. **Recovery stability** (65-75% vs BSL's 39%) = private credit's structural advantage via covenants is holding... for now
5. **Near-zero defaults** (0.16%) = the calm before potential stress

The nuance: private credit IS deteriorating but is deteriorating LESS than public markets. The covenant retention and direct lender control provide structural protection that public BSL has lost. The risk is that the sheer volume of capital deployed ($3T) at compressed spreads overwhelms these structural advantages if a recession hits.

### Key Question for Next 12-18 Months

Will the structural advantages of private credit (covenants, workout control, relationship lending) hold under stress? Or will the 2024-2025 vintage deployed at 5% spreads and rising PIK prove that too much capital was deployed at too thin a margin?

---

## Data Sources & Methodology

- **Position-level data:** SEC EDGAR XBRL filings (BDC 10-K/10-Q) + N-PORT quarterly TSVs
- **Impairment proxy:** FV/cost ratio < 0.90 threshold
- **Spread data:** `basis_spread` field from BDC XBRL (SOFR spread in percentage points)
- **PIK data:** `pik_rate` field from BDC XBRL, N-PORT `IS_ANY_PORTION_INTEREST_PAID_IN_KIND` flag
- **Default data:** N-PORT `IS_DEFAULT` flag
- **Public market benchmarks:** ICE BofA HY OAS, Morningstar LSTA, Proskauer Private Credit Default Index, Cliffwater CDLI, Fitch/Moody's recovery data
- **Coverage:** 237 CIKs with holdings, ~590K positions after consumer lending exclusion
- **Limitations:** BDC XBRL starts ~2022 (phased-in tagging), N-PORT from 2019q4. Non-accrual data sparse. FV marks are lagging by nature (Level 3 manager discretion).
