# Private Markets Index Family: Methodology

## 1. Overview

### Purpose

The Private Markets Index family provides transparent, rules-based benchmarks for privately originated credit, direct equity co-investments, and private fund vehicles. All four indices are constructed entirely from mandatory regulatory filings with the U.S. Securities and Exchange Commission. No proprietary data, voluntary surveys, or self-reported returns are used.

This data sourcing distinguishes the indices from existing private markets benchmarks. Because the SEC requires registered investment companies to disclose position-level holdings at fair value on a quarterly basis, the indices are free from the selection bias (managers choosing whether to report), survivorship bias (defunct funds dropping from databases), and reporting lag (managers timing NAV disclosures) that characterise voluntary-reporting frameworks such as those maintained by Cambridge Associates, Preqin, and Burgiss.

### Index Family

| Index | Description |
|---|---|
| **Direct Lending** | Individual loan positions---first lien, second lien, unitranche, mezzanine, and other privately originated credit instruments---extended to operating companies. Total return (price + income). |
| **Direct Equity** | Direct equity and preferred equity co-investments in operating companies. Price return only. |
| **Private Credit Fund** | Marked fair value of private credit fund vehicles (senior lending funds, CLO equity, direct lending partnerships) as reported by their holding vehicles. Total return (price + distribution proxy). |
| **Private Equity Fund** | Marked fair value of PE, buyout, growth equity, and venture fund vehicles as reported by their holding vehicles. Total return (price + distribution proxy). |

### Constituent Structure

Each index constituent is an individual position held by a specific vehicle, not an issuer-level aggregate. A single borrower may appear as multiple constituents when different vehicles hold separate tranches---a first lien term loan and a second lien term loan to the same company are two separate index members, each with its own weight, return, and lifecycle. This position-level granularity preserves the economics of seniority, coupon structure, and maturity, and mirrors the constituent structure of public credit indices such as the Morningstar LSTA Leveraged Loan Index, where each loan tranche is a separate member.

---

## 2. Eligible Universe

### Vehicle Types

The index universe comprises three categories of SEC-registered investment vehicles:

**Business Development Companies (BDCs)** are closed-end investment companies that have elected BDC status under Sections 54-65 of the Investment Company Act of 1940. They are the primary source of direct lending and direct equity holdings. The universe includes all entities that have filed an N-54A election notice and have not subsequently withdrawn via N-54C.

**Interval Funds** are registered closed-end funds operating under Rule 23c-3, which requires periodic repurchase offers (typically quarterly) at net asset value in lieu of daily liquidity. Many interval funds allocate to private credit, real estate credit, and multi-strategy private markets.

**Tender Offer Funds** are registered closed-end funds that periodically offer to repurchase shares at net asset value outside the Rule 23c-3 framework. Like interval funds, they access illiquid private market strategies within a 1940 Act structure.

### Universe Construction

The universe is constructed from multiple independent regulatory signals and cross-validated against third-party industry lists.

**BDC discovery** employs three methods: (1) BDC election filings (Form N-54A/N-54C) identifying all entities that have ever elected or withdrawn BDC status; (2) EDGAR filing index scans for periodic reports (10-K, 10-Q) carrying Investment Company Act file numbers with the 814- prefix; and (3) cross-validation against the SEC's structured BDC Data Set.

**Interval and tender offer fund discovery** employs six methods: (1) N-CEN annual census data identifying funds classified as interval funds; (2) N-2 registration statement cover-page analysis for interval fund checkboxes (Rule 23c-3) and tender offer prospectus language; (3) EDGAR full-text search of fund registration documents; (4) N-PORT filing cross-referencing; (5) SEC Investment Company Series and Class data; and (6) cross-validation against independently maintained industry lists (Interval Fund Tracker, Tender Offer Funds database, Sure Dividend BDC list).

### Current Universe

The index universe comprises **587 entities**: 425 BDCs, 125 interval funds, and 37 tender offer funds. Of these, 237 entities have extractable position-level holdings data contributing to index computation. The remainder are pre-operational, recently launched, or file in formats predating XBRL tagging requirements.

Third-party cross-validation achieves 96--97% match rates, with unmatched entities consisting of recently launched or recently liquidated vehicles not yet reflected in independently maintained lists.

---

## 3. Data Sources

### BDC XBRL Filings (Form 10-K / 10-Q)

BDCs file quarterly (10-Q) and annual (10-K) reports that include a Schedule of Investments with position-by-position detail. Since approximately 2022, the SEC has required these schedules to be tagged in XBRL, enabling systematic extraction of structured data for each position.

Each position is identified by a typed dimension value on the `investmentIdentifierAxis` that typically encodes the investee company name, instrument type, industry classification, and other descriptive metadata. Standard XBRL tags provide fair value, cost basis, principal amount, stated interest rate, basis spread over reference rate, reference rate type, maturity date, shares held, percentage of net assets, PIK rate, and unrealized gain or loss.

BDC XBRL filings also contain **comparative-period data**: approximately 91% of filings include the prior period's Schedule of Investments under the same typed dimension values, providing filer-matched position pairs that require no external linking algorithm.

### N-PORT Filings (Form N-PORT)

Registered management investment companies---including interval funds and tender offer funds---file monthly portfolio holdings on Form N-PORT. The SEC publishes pre-extracted quarterly data sets containing every holding with standardised fields: asset category (`assetCat`: loan, equity-common, equity-preferred, debt, etc.), issuer category (`issuerCat`: corporate, private fund, registered fund, etc.), fair value, cost basis, CUSIP, LEI, coupon rate, coupon type, maturity date, and liquidity classification.

N-PORT's structured taxonomy enables direct classification of holdings into index categories without text parsing.

### N-CEN Filings (Form N-CEN)

Form N-CEN is an annual census of all registered investment companies. It provides fund classification (open-end, closed-end, interval, exchange-traded), strategy indicators, adviser details, and structural metadata used for universe identification.

### N-2 Registration Statements (Form N-2)

Form N-2 is the registration statement for closed-end funds and BDCs. Cover-page checkboxes identify interval fund status (Rule 23c-3). Tender offer fund identification requires analysis of prospectus language, as no dedicated checkbox exists for this structure.

---

## 4. Holdings Classification

Every position in the unified dataset is classified along three dimensions---asset category, issuer category, and index classification---which together determine index eligibility.

### Asset Category

| Category | Description |
|---|---|
| LOAN | First lien, second lien, unitranche, mezzanine, revolving credit, delayed draw, and other privately originated loan instruments |
| DEBT | Bonds, notes, CLO debt tranches, and other fixed income securities |
| EQUITY_COMMON | Common stock, warrants, membership interests, and other common equity instruments |
| EQUITY_PREFERRED | Preferred stock and preferred equity interests |
| FUND | Interests in private funds, limited partnership interests, and fund-of-fund positions |
| OTHER | Government securities, derivatives, cash equivalents, and other positions outside the above categories |

**N-PORT classification** uses the filer-reported `assetCat` field. Key mappings: `LON` to LOAN, `EC` to EQUITY_COMMON, `EP` to EQUITY_PREFERRED, `DBT` to DEBT, `ABS-CBDO` (CLO debt tranches) to DEBT. Asset-backed securities (`ABS-O`), mortgage-backed securities (`ABS-MBS`), and other structured products are classified as OTHER and excluded from the private markets indices.

**BDC classification** uses a five-priority cascade: (1) the XBRL investment type axis, when populated; (2) keyword matching against the instrument description for terms such as "first lien", "term loan", "mezzanine", "preferred stock", "common equity", "warrant", and "LP interest"; (3) keyword matching against the full position identifier; (4) financial field heuristics---positions carrying an interest rate, basis spread, or principal amount default to LOAN, while positions with shares held default to EQUITY_COMMON; (5) fallback to OTHER.

### Issuer Category

| Category | Description |
|---|---|
| CORPORATE | Operating companies---borrowers, portfolio companies, and other non-fund issuers |
| FUND | Private funds, registered funds, and limited partnerships operating as pooled investment vehicles |
| GOVERNMENT | Municipal, U.S. Treasury, and other sovereign or agency issuers |

**N-PORT** uses the filer-reported `issuerCat` field. Loan and debt positions reported with an OTHER issuer category are reclassified to CORPORATE. Equity positions in issuers whose names contain BDC or credit fund keywords are reclassified to FUND.

**BDC** positions classified as FUND assets carry FUND issuer category; all others default to CORPORATE.

### Named Co-Investment Reclassification

Approximately 1,000 positions are structured as LP interests or co-investment vehicles but represent direct equity stakes in identifiable operating companies rather than commingled fund interests. These are identified by the combination of co-investment keywords ("co-invest", "co-investment") or LP interest keywords with operating company markers (Inc., LLC, Corp., Holdings, Ltd., GmbH, etc.) in the position name. Such positions are reclassified from FUND to EQUITY_COMMON or EQUITY_PREFERRED with CORPORATE issuer category, routing them to the Direct Equity Index.

### Index Classification

| Index | Asset Categories | Issuer Category |
|---|---|---|
| DIRECT_LENDING | LOAN, DEBT | CORPORATE |
| DIRECT_EQUITY | EQUITY_COMMON, EQUITY_PREFERRED | CORPORATE |
| PRIVATE_CREDIT_FUND | FUND | FUND (credit strategy keywords) |
| PRIVATE_EQUITY_FUND | FUND | FUND (equity strategy keywords) |
| UNCLASSIFIED | OTHER, or combinations not matching above | Any |

**Fund strategy classification** distinguishes credit funds from equity funds using keyword signals in the fund name. Credit signals include "credit", "lending", "loan", "debt", "income", "CLO", "senior", "direct lending", "floating rate", and "yield". Equity signals include "equity", "buyout", "growth", "venture", "private equity", "capital partners", "secondaries", and "infrastructure". When both signal types are triggered, the classification with the greater number of matching signals prevails.

### Aggregate and Subtotal Filtering

BDC XBRL filings embed subtotal and category-header rows alongside individual positions in the Schedule of Investments. The methodology identifies and excludes these non-position rows using four techniques:

1. **Substring pattern matching**: Over 45 known subtotal patterns are excluded, including "Total Investments", "Net Assets", "Total First Lien", "Total Senior Secured", "Total Debt Investments", "Total Bank Debt", and other aggregate labels commonly used by BDC filers.

2. **Exact match exclusion**: Bare section headers such as "Debt Investments", "Equity Securities", "First Lien", and "Collateralized Loan Obligation" that appear without an associated company name are excluded.

3. **Category prefix detection**: Identifiers beginning with known category prefixes followed by a space (e.g., "Debt investments ") are excluded.

4. **Industry label exclusion**: Single-word or multi-word identifiers matching a list of 131 known industry labels (e.g., "Technology", "Healthcare", "Aerospace & Defense") are excluded when they appear without a company name.

---

## 5. Position Matching

Computing position-level returns requires linking the same instrument across consecutive reporting periods. The methodology uses a four-tier matching cascade applied in priority order, with strict one-to-one enforcement at each tier and cascade exclusion to prevent duplicate matching.

### Tier A: Within-Filing Comparatives

BDC XBRL filings contain Schedule of Investments data for both the current reporting date and the prior comparative period, tagged under the same typed dimension value. This provides filer-verified position pairs requiring no external matching.

- **Coverage**: approximately 37% of all matched pairs
- **Span**: 3 months (quarterly filings), 6, 9, or 12 months (annual filings) depending on form type and fiscal year-end
- **Accuracy**: effectively 100%, as the linkage is the filer's own comparative financial reporting
- **Cascade exclusion**: only end-side (current-period) positions are excluded from subsequent tiers; begin-side (prior-period) positions are released to lower tiers to prevent orphaning when the raw identifier format changed between filings

### Tier B: Deterministic Identifier Matching

Positions not matched by Tier A are linked using exact identifiers across consecutive quarterly filings from the same vehicle.

**CUSIP matching (Tier B1)**: N-PORT filings include CUSIP identifiers for approximately 47% of holdings. CUSIPs uniquely identify a specific instrument tranche and provide definitive cross-quarter linkage. High-multiplicity CUSIPs (appearing more than five times per vehicle per quarter) and placeholder values are excluded to prevent false matches. This tier contributes approximately 1.6% of all matched pairs.

**Exact name matching (Tier B2)**: Issuer names are matched exactly (case-insensitive) across consecutive quarters within the same vehicle. N-PORT issuer names carry forward at 98.5% quarter-over-quarter; BDC names carry at approximately 78% after identifier parsing. This workhorse tier contributes approximately 60% of all matched pairs. One-to-one enforcement uses double row-numbering with fair value proximity as the tiebreaker.

### Tier C: Normalised Name Matching

Positions not matched by Tiers A or B undergo aggressive name normalisation: trailing pipe-delimited metadata is stripped, parenthetical expressions are removed, trailing ordinal numbers are dropped, punctuation is cleaned, and whitespace is collapsed. This recovers matches lost to formatting changes between 10-K and 10-Q filings, where the same BDC may switch between pipe-delimited and comma-delimited identifier formats.

This tier contributes approximately 0.5% of all matched pairs.

### Tier D: Fuzzy Matching

Remaining unmatched positions are linked using Jaro-Winkler string similarity with three guards:

- **Prefix blocking**: the first four characters of the normalised issuer name must match before similarity is computed, eliminating the vast majority of false-positive candidates
- **Similarity threshold**: a minimum Jaro-Winkler score of 0.88 is required
- **Fair value guard**: the ratio of beginning-period to ending-period fair value must fall between 0.2x and 5.0x

When multiple candidates exceed the threshold, the highest similarity score is selected, with fair value proximity (log-ratio) as the tiebreaker.

This tier contributes approximately 0.3% of all matched pairs.

### One-to-One Enforcement

At every tier, matched pairs are subjected to strict one-to-one enforcement using double row-numbering: first partitioned by begin-side position (keeping the best match per begin row), then partitioned by end-side position (keeping the best match per end row). Each position may appear on at most one side of one pair. The tiebreaker at each step is fair value proximity, defined as `|ln(FV_begin / FV_end)|`, selecting the candidate with the most similar fair value.

### Position Lifecycle Tracking

After matching, a union-find algorithm assigns stable position identifiers (`position_id`) that track each instrument across its full multi-quarter lifecycle.

1. Each matched pair creates an edge in an undirected graph. Only pairs with spans of four months or fewer are used as edges; longer-span annual pairs are excluded to prevent unreliable transitive connections.
2. A supplementary matching pass runs directly on the unified holdings using exact issuer name matching with uniqueness constraints (the name must appear exactly once per vehicle per quarter) and a 5x fair value ratio guard, recovering positions stranded by the cascade exclusion gap.
3. Connected components in the resulting graph define position chains---the same instrument observed across multiple quarters. Each chain receives a single `position_id`.
4. Holdings not connected to any chain receive unique singleton identifiers.

The current dataset contains approximately 192,000 chained positions (multi-quarter tracks) and 232,000 singletons, for a total of approximately 424,000 unique position identifiers. The maximum observed chain length is 28 consecutive quarterly observations.

### Coverage

The four-tier cascade produces approximately **560,000 matched position pairs** across the full 25-quarter history.

---

## 6. Return Calculation

### Total Return Framework

The indices use a total return framework consistent with all major public credit and fixed income indices:

*Total Return = Capital Return + Income Return*

For direct lending, where coupon income is the dominant return component, omitting income would render the index incomparable to benchmarks such as the Morningstar LSTA Leveraged Loan Index or the ICE BofA US High Yield Index. Returns are computed on **beginning-of-period constituents only**; new positions entering at a quarterly rebalance do not retroactively affect the prior period's return, cleanly separating mark-to-market performance from capital deployment.

### Direct Lending Returns

For each matched position pair in the Direct Lending Index:

**Capital return** measures the change in per-unit price, isolating mark-to-market movement from changes in position size due to additional draws, partial repayments, or scheduled amortisation:

*When principal amount is available in both periods:*

> Per-unit price = Fair Value / Principal Amount
>
> Capital Return = (Price_end - Price_begin) / Price_begin

*When principal amount is unavailable:*

> Capital Return = (FV_end - FV_begin) / FV_begin

Per-unit pricing is critical for accurately measuring amortising loans. Without it, a scheduled principal paydown on a par-priced loan would register as a negative return despite the lender receiving full par value.

**Income return** estimates quarterly coupon accrual based on the position's effective interest rate, outstanding principal, and holding period:

> Income Return = (Principal_begin x Effective Annual Rate x Span_months / 12) / FV_begin

Where `Principal_begin` falls back to `FV_begin` when principal is not reported. Income return is capped at 25% per quarter (approximately 100% annualised) to guard against data errors in the rate field. The effective annual rate is determined by the imputation cascade described below.

### Income Rate Imputation

Interest rate coverage across the direct lending constituent base uses a three-tier imputation cascade:

**Tier 1 --- Direct interest rate** (approximately 72% of constituents). The all-in coupon rate is reported in the filing's XBRL data or N-PORT structured fields and used directly after harmonisation to percentage scale.

**Tier 2 --- Basis spread plus implied reference rate** (approximately 7% of constituents). When only the contractual spread over a floating reference rate is available, the all-in rate is reconstructed by adding the spread to a market-implied reference rate. The implied rate is derived as the median of (all-in rate minus basis spread) observed across all filers reporting both fields in the same quarter. This peer-derived SOFR proxy tracks the Federal Funds effective rate closely: approximately 1.0% in 2021 Q4, 5.4% in 2023 Q3, and 4.2% in 2025 Q3.

**Tier 3 --- Same-filer median rate** (approximately 5% of constituents). For positions with neither a stated rate nor a basis spread, the median all-in rate across all other positions from the same filer in the same quarter is applied. This assumes a BDC's portfolio has relatively homogeneous pricing characteristics, making its own median rate a reasonable proxy for positions missing rate data.

**Missing** (approximately 2% of constituents). No rate is available. These positions receive zero income return but remain in the index with capital return only, marginally understating their total return contribution.

All imputed rates are capped at 50% (annualised) to exclude data-entry errors.

### Direct Equity Returns

For each matched position pair in the Direct Equity Index:

**Capital return** uses per-unit pricing in the following priority:

1. Fair value divided by shares held, when share counts are available in both periods
2. Fair value divided by cost basis, when cost is available in both periods and shares are not---this uses cost as a quantity proxy, isolating price appreciation from capital additions
3. Raw percentage change in fair value as a final fallback

**Income return** is not currently estimated. Dividend data is not systematically tagged in BDC XBRL filings or N-PORT structured data at the position level.

### Private Fund Vehicle Returns

For positions in the Private Credit Fund and Private Equity Fund indices:

**Capital return** is the percentage change in marked fair value.

**Distribution proxy**: when cost basis declines between periods without a commensurate decline in fair value, the cost reduction is treated as a return of capital and added to the return numerator:

> Income Return = max(0, (Cost_begin - Cost_end) / FV_begin)

This captures fund distributions that reduce the investor's cost basis while fair value remains stable or appreciates---a common pattern in private fund accounting where distributions represent realised gains or return of contributed capital. The proxy is floored at zero; cost increases (additional capital calls) do not produce negative income.

### Span Adjustment

Matched pairs may span more than one quarter (6-month or 12-month pairs from annual BDC filings). Multi-quarter returns are converted to quarterly equivalents using geometric de-annualisation:

> Quarterly Return = (1 + Multi-Period Return)^(3 / Span_months) - 1

This adjustment applies to pairs spanning more than four months.

### Outlier Controls

Position-level returns are subject to three guards before entering the index:

| Control | Threshold | Treatment |
|---|---|---|
| **Total return upper bound** | +200% | Position excluded from the quarter (return set to null) |
| **Total return lower bound** | -99% | Capped at -99%; directional signal preserved |
| **Income return upper bound** | +25% per quarter | Income component capped before summing to total return |

The upper bound on total returns prevents data errors, position restructurings, or extreme mark-up events from unduly influencing the fair-value-weighted index. The income cap guards against erroneous rate fields that would produce implausible quarterly income.

---

## 7. Index Construction

### Weighting Schemes

Three weighting schemes are computed for each index:

**Fair-value weighted** (primary): each position's weight equals its beginning-of-quarter fair value divided by total beginning-of-quarter fair value across all index constituents. This is the standard weighting convention for credit indices and reflects the economic exposure of the aggregate portfolio.

**Equal weighted**: each position receives equal weight (1/N) regardless of size. This provides a view of median position-level performance and reveals whether returns are driven by a few large positions or broadly distributed across the constituent base.

**Cost weighted**: each position's weight equals its cost basis divided by total index cost basis. Cost weighting eliminates the circularity of fair-value weighting, where the variable being measured also determines constituent weights, and anchors the return to deployed capital. When cost basis is unavailable for a position, the position is included at equal weight as a fallback.

### Chain-Linking

Quarterly index returns are chain-linked multiplicatively from a base level of 100:

> Index(t) = Index(t-1) x (1 + R(t))

where R(t) is the weighted quarterly total return under the chosen weighting scheme. The implementation uses the log-return formulation for numerical stability:

> Index(t) = 100 x exp( sum of ln(1 + R(s)) for s = 1 to t )

This produces a cumulative index level representing the growth of a notional 100 invested at inception.

### Quarterly Rebalancing

The indices rebalance quarterly, consistent with public credit index conventions:

1. Returns for the quarter are computed using **beginning-of-quarter constituents only**.
2. At quarter-end, the constituent list is refreshed: new positions appearing during the quarter enter the index; positions that have exited (repaid, sold, or written off) are removed.
3. Weights are recalculated based on beginning-of-next-quarter fair values.
4. New entrants and exits do not retroactively affect the prior quarter's return.

### Minimum Constituent Threshold

A quarterly index value is computed only when the number of valid constituents (after outlier exclusion and minimum fair value filtering) reaches or exceeds **10**. Quarters falling below this threshold are omitted from the chain-linked series.

### Minimum Position Size

Positions with a beginning-of-quarter fair value below **$100,000** are excluded from index return computation. This filters micro-positions---residual balances, unfunded commitments marked at nominal value, or de minimis warrant positions---that contribute negligible economic weight but can generate extreme percentage returns.

---

## 8. Data Quality Controls

### Cross-Source Deduplication

BDCs that are also registered investment companies may report positions through both BDC XBRL filings (10-K/10-Q) and N-PORT filings. The methodology identifies duplicate positions using the combination of CIK, report date, issuer name (exact match), and fair value rounded to the nearest $100. When duplicates are detected, the BDC XBRL source is retained, as it provides richer structured data (typed dimension values, comparative periods, investment type axes). This removes approximately 22,000 duplicate rows.

### Rate Harmonisation

Interest rates from BDC XBRL filings are reported in varying conventions: decimal (0.103 for 10.3%), percentage (10.3), or basis points (1030). A three-band normalisation converts all rates to percentage scale:

- Rates <= 0.50 are treated as decimal and multiplied by 100
- Rates > 50 are treated as basis points and divided by 100
- Rates in the 0.50--50 range are treated as already in percentage form

This normalisation is applied to interest rate, basis spread, PIK rate, and percentage of net assets fields across both BDC and N-PORT sources.

### Rate Capping

After harmonisation, interest rates exceeding 50% are set to null. Empirical analysis identified a small number of rows with implausibly high rates, typically resulting from data-entry errors or unit confusion in the original filings.

### Name Normalisation

Issuer names undergo standardisation: double periods collapse to single periods, consecutive whitespace collapses to a single space, and trailing commas and semicolons are stripped (trailing periods are preserved as they typically indicate abbreviations such as "Inc." or "Corp."). This normalisation is applied consistently across both sources before matching, deduplication, and position tracking.

### Cost Basis Imputation

For positions where cost basis is null or zero, the first available non-zero fair value for the same issuer from the same filer across all historical reporting periods is used as a proxy. The imputation window extends in both directions (preceding and following periods) so that positions which begin with zero fair value---such as pre-funding commitments---are not incorrectly assigned a zero cost from their inception period.

---

## 9. Coverage and Limitations

### Temporal Coverage

| Data Source | Earliest Quarter | Notes |
|---|---|---|
| BDC XBRL | ~2022 Q3 | The SEC phased in XBRL tagging for BDC Schedules of Investments. Pre-2022 filings are HTML-only. Some early XBRL filings contain only aggregate totals without individual positions. |
| N-PORT | 2019 Q4 | Form N-PORT filing began in 2019. The SEC publishes pre-extracted quarterly data sets with approximately one quarter of lag. |

The index series spans **25 quarters** from 2019 Q4 through 2025 Q4. The earliest quarters rely primarily on N-PORT data; BDC XBRL coverage expands from 2022 onward.

### Entity Coverage

Of 587 entities in the index universe, **237 (40%)** contribute position-level holdings to the indices. The 350 entities without extractable holdings include:

- Interval and tender offer funds that file N-PORT but hold no private market positions eligible for the indices
- BDCs predating XBRL requirements, filing only aggregate data, or in pre-operational status

### Known Biases and Considerations

**Reporting frequency and price staleness.** BDC filings are quarterly (10-Q) or annual (10-K); N-PORT filings are monthly but the SEC publishes extracted data quarterly. The index is therefore quarterly in frequency. Intra-quarter price movements, including rapid credit deterioration or recovery, are not captured between reporting dates.

**Valuation heterogeneity.** Fair values are reported by each holding vehicle using its own valuation policies, which may differ across filers. BDC fair values are determined by boards of directors, typically with input from independent third-party valuation firms, and are subject to annual audit. N-PORT fair values follow each fund's valuation procedures as described in its prospectus. The index reflects these marks as reported without attempting to re-mark positions to a common valuation standard.

**Survivorship.** The universe is defined by observed filing behaviour. Entities that cease filing (through merger, liquidation, or deregistration) exit the universe naturally; their final-period marks are included through the last reporting date. Positions exiting between quarters (via repayment, sale, or write-off) are not captured until the next filing reflects their absence. This produces a conservative bias: distressed positions that recover before the next filing date are not observed, but positions that are written off appear as losses.

**BDC identifier variability.** BDC XBRL position identifiers follow four format families (pipe-delimited, structured comma, unstructured, and space-separated). The same BDC may change formats between annual and quarterly filings, creating discontinuities in position tracking. The normalised name matching tiers are designed to bridge these transitions. Approximately 19% of all holdings are singletons (positions observed in only one quarter without a forward or backward match), of which roughly half are attributable to structural causes (boundary quarters, zero fair value, or newly originated positions) rather than matching failures.

**Income estimation.** The Direct Lending Index estimates income from stated coupon rates rather than actual cash flows received. PIK accrual, fee income (origination fees, prepayment penalties), and amendment fees are not separately captured. This approach likely understates total economic return for positions with significant non-cash income components.

---

## 10. Index Statistics

*As of 2025 Q4 --- 25 quarters from 2019 Q4*

| Index | FV-Weighted Level | EQ-Weighted Level | Avg Quarterly Constituents | Quarters |
|---|---|---|---|---|
| Direct Lending | 141.4 | --- | 9,177 | 25 |
| Direct Equity | 118.4 | --- | 1,274 | 25 |
| Private Credit Fund | 204.4 | --- | 40 | 21 |
| Private Equity Fund | 190.2 | --- | 129 | 25 |

The Direct Lending Index has delivered approximately 5.8% annualised total return (FV-weighted) over its 25-quarter history, consistent with the yield characteristics of senior secured first lien loans during a period of sharply rising and then gradually declining base rates. The 2019 Q4 inception coincides with the pre-pandemic rate environment; the index captures the COVID-19 drawdown, subsequent recovery, the 2022--2023 rate hiking cycle, and the initial easing in late 2024--2025.

The unified holdings dataset contains approximately **835,000 positions** across 237 reporting entities, sourced 55% from N-PORT filings and 45% from BDC XBRL filings. The position matching cascade produces approximately **560,000 matched pairs**: 37% from within-filing comparatives, 2% from CUSIP matching, 60% from exact name matching, 0.5% from normalised name matching, and 0.3% from fuzzy matching.

---

## 11. Appendix: Key Parameters

| Parameter | Value | Description |
|---|---|---|
| Minimum constituents per quarter | 10 | Quarters with fewer valid positions do not produce an index value |
| Minimum beginning fair value | $100,000 | Positions below this threshold are excluded from return computation |
| Maximum total return | +200% | Position returns above this are excluded as outliers (set to null) |
| Minimum total return | -99% | Position returns below this are capped at this floor |
| Maximum income return | +25% per quarter | Income return component is capped before summing to total return |
| Interest rate cap | 50% | Rates above this threshold (after harmonisation) are set to null |
| Fuzzy match similarity threshold | 0.88 | Minimum Jaro-Winkler score for Tier D matching |
| Fuzzy match FV ratio guard | 5.0x | Maximum ratio of begin/end fair value for fuzzy match candidates |
| Fuzzy match prefix block length | 4 characters | Leading characters that must match before computing similarity |
| CUSIP maximum multiplicity | 5 | CUSIPs appearing more than this per vehicle per quarter are excluded |
| Cross-source dedup FV rounding | $100 | Fair values rounded to nearest $100 for duplicate detection |
| Span adjustment threshold | 4 months | Matched pairs spanning more than this are geometrically adjusted |
| Rebalancing frequency | Quarterly | Constituent list and weights refreshed at start of each quarter |
| Index base level | 100 | Starting value at inception (2019 Q4) |

---

*This document describes the index methodology as currently implemented. The methodology may be updated as additional data sources become available, classification rules are refined, or constituent coverage expands. Material changes will be documented and disclosed with effective dates.*
