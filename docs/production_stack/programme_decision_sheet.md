# Programme contract decision sheet

Date: 2026-09-09. Status: **all thirteen decisions resolved**. The owner's instruction, "the items with no comments are resolved", accepts the recommended option A for D05, D07-D08 and D11-D13. Earlier commented decisions retain their recorded dispositions. Numerical thresholds remain provisional under the accepted D12 calibration process.

Purpose: consolidate existing contracts and resolve specific gaps before finalizing schema changes and implementation packets. This is not a new definition of what a holding row is. The [accepted outcome framework](programme_acceptance_draft.md) controls scope; the [88-column crosswalk](../reference/unified_holdings_contract_crosswalk.md) supplies the existing F01-F12 findings. The [current-state assessment](current_state_assessment_2026-09-09.md) and [architecture](../reference/current_architecture.md) supply implementation context.

The owner chooses financial meaning, product scope and acceptable uncertainty. The implementation team chooses table layout, SQL structure, identity algorithms and directory names within those decisions. Accepted decisions define the target behavior; they do not establish that current data passes validation. Unselected alternatives remain below only as decision history.

## 1. What we retain without asking again

| Existing or accepted contract | Treatment |
|---|---|
| Unified row means a retained, normalized holding observation selected from filings; distinct instruments and disclosed lots remain separate. | **Retain.** Test enforcement and document exceptions; do not replace with borrower-level rows. |
| Company identity is distinct from source-row identity and within-filer position continuity. Cross-filer instrument matching is excluded. | **Retain and complete.** Stable identities and traceable corrections are accepted requirements, not optional upgrades. |
| Canonical all-in interest-rate target, with PIK separately represented. | **Correct implementation.** Storage and income consumers must migrate atomically; D01 addresses incomplete evidence, not whether to keep a cash-leg canonical rate. |
| Reported, calculated and inferred values must be distinguishable; unknown is legitimate. | **Retain and extend lineage.** No silent proxy substitution or mandatory filling of undisclosed terms. |
| PIK terms, current payment/accrual evidence and distressed amendments are distinct; no detected flag is not confirmed absence. | **Correct enforcement.** Reuse the existing strict-status model; do not ask whether unknown may become false. |
| Relevant cash, JV/subsidiary and look-through records are retained with explicit source/accounting scope. | **Retain and clarify.** D08 concerns additional analytics, not permission to drop records. |
| Public headline FV and its instrument/industry breakdowns sum the same cohort-quarter holdings exactly. | **Correct implementation.** Do not reopen this as a numerical tolerance or change the public population through an exporter. |
| Core history Q1 2023-Q1 2026; Q1 2026 first; optional Q4 2022; lower-priority Q2 2026 test. | **Retain.** D05 concerns historical revisions; D11 concerns unavailable source coverage. |
| dbt migration, reproducible release bundles, protected acceptance assets and restartable work are in scope. | **Retain and implement.** D13 bounds changes to the existing agent subsystem. |
| End-state is a release candidate ready for owner approval. | **Retain.** This sheet neither launches implementation nor authorizes publication. |

## 2. Review map

All choices are resolved. The status column records the accepted scope and any remaining implementation or measurement work. Effort comments are relative, not delivery estimates.

| Decision | Accepted position | Status / remaining work |
|---|---|---|
| D01: incomplete rate evidence | Missing/unsupported rates stay blank. Preserve disclosed rates and evidence-backed arithmetic; do not estimate a missing rate. | **Decided.** No model, peer-median or assumed-benchmark rate filling in the programme's public holdings/analytics. |
| D02: missing cost | First observed FV is an approved proxy when reported cost is missing; preserve actual cost, including zero, and identify the proxy. | **Decided.** Proxy-aware analytics may use it; it is not reported acquisition cost. |
| D03: unresolved currency/FX | Assume USD unless source evidence indicates otherwise. Explicit USD and assumed USD remain distinguishable; non-USD principal requires appropriate FX. | **Decided.** Default assumptions do not count as verified source currency; known non-USD with missing FX does not revert to USD. |
| D04: percentage defaults | Retain the existing % Portfolio display, keeping reported and calculated %NAV semantically separate. | **Closed; existing default retained.** Owner had no further comment after the denominator explanation. |
| D05: historical revisions | Publish latest-best history with versioned releases and traceable revisions. | **Decided: A.** An as-known-at-cutoff historical product is outside this programme. |
| D06: partial maturity | Use month-end for a disclosed month/year unless an exact date or applicable source-specific convention supplies a different date. Keep missing dates blank and preserve precision. | **Decided.** Month-end already matches the inspected staging and HTML bridge behavior. |
| D07: company versus group | Resolve the disclosed borrower/company conservatively; store evidenced group relationships separately. | **Decided: A.** Corporate-group concentration is not a required release capability. |
| D08: look-through analytics | Retain linked records and validate their separate accounting populations. | **Decided: A.** Ownership-adjusted look-through analytics are not required. |
| D09: GICS publication depth | Sector is the required classification level, matching the main website views. Deeper levels are optional when available and supported. | **Decided.** No mandatory sub-industry assignment or deeper-level coverage gate. Unknown sector remains explicit and counted in coverage. |
| D10: citation format | Prioritize exact HTML/inline-XBRL source highlights. PDF highlights/renditions are lower priority and may be deferred. | **Decided on priority; Arelle identified by owner.** Evaluate Arelle and its iXBRL Viewer; adoption/integration design remains open. |
| D11: historical source gaps | Measure XBRL coverage and document eligible missing observations, using cached facts and existing recovery paths. | **Decided: A.** No additional HTML recovery campaign; coverage gaps remain measured against the final gate. |
| D12: hard targets | Complete definitions and baseline measurement, then approve the final gate before remediation. | **Decided: A.** The calibration process is approved; proposed numerical targets remain provisional. |
| D13: agent-system changes | Preserve proposal/verification/promotion roles; change interfaces, persistence and defects needed for this programme. | **Decided: A.** Required integration/control fixes are in scope; a broader workflow redesign is excluded. |

The [target contract](programme_target_contract.md), [field disposition map](../reference/programme_field_disposition.csv) and [measurement register](programme_measurement_register.md) extend the existing crosswalk. Subsequent preparation supplied technical conventions, a measured starting point and numerical working targets accepted on 10 September. No further choice among D01-D13 is pending. Later owner direction requires automated source verification without a mandatory human-labelled gold set. [Current specification status](programme_spec_status.md) records that correction, the withdrawn readiness claim and unfinished implementation.

## 3. Financial decisions

### D01. What should we do when the reported rate cannot be confidently interpreted?

**Basis:** F01; B1, B2, B5, D1-D2. The all-in target is settled. Existing parsing/convention evidence identifies cash-only, all-in and uncertain regimes, but not consistently across every observation.

**Owner decision:** "if there is no rate evidence, leave the field blank - do not infer it."

Retain the reported rate and its meaning; calculate cash/PIK/all-in components only when the evidence supports the arithmetic. Keep an absent or ambiguous all-in rate unknown. Weighted all-in coupon analytics use eligible observations and disclose covered FV. The estimated-rate alternative is excluded from this programme's public holdings/analytics. Missing rates must not be silently filled inside an income calculation either; retain an explicit unavailable status instead of assuming a zero coupon.

**Current implementation to address:** [index_returns.py](../../pipeline/index_returns.py) derives an implied benchmark from other positions and uses a same-filer median when a position lacks a rate/spread. These do not fill the canonical holdings field, but are downstream rate estimates. Any public consumer must respect the no-inference decision; retaining a legacy research calculation does not make it eligible for publication. This inspection did not measure which current public payloads depend on those fallbacks.

Do not treat every bare rate as cash-pay or automatically add PIK to a rate that already includes it. Optional floors/caps may be retained with evidence; a floor-tag name alone does not establish the economic meaning needed for a calculation.

**Validation:** a disclosed 11.49% cash plus 2% PIK example yields 13.49% all-in; a disclosed 13.49% all-in must remain 13.49%. Add ambiguous-rate, missing-PIK, rate-unit and effective-yield counterexamples. Report comparable-coupon coverage separately from rate fill. Reuse existing convention, grammar and income tests; update both storage and consumers in the same migration.

### D02. Should public cost-based analytics ever use an estimated cost?

**Basis:** F02; B1-B2, D1-D2, E2. The crosswalk found reported cost on 96.1% of its Q1 matched source sample, including legitimate zeros. Current FV proxies can flow into markdown/stress analytics. These are dated audit observations, not a fresh coverage certificate.

**Owner question answered:** principal is not the generic substitute for missing `cost` in the inspected holdings construction. The `with_cost` step in [unified_holdings.py](../../pipeline/unified_holdings.py) uses the first nonzero FV in its historical position partition and marks `cost_source=derived_proxy`; it currently also replaces explicit zero cost. Principal/par is used separately: [fund exports](../../pipeline/export/fund_exports.py) compare FV with USD principal for price-to-par stress, and [return calculations](../../pipeline/index_returns.py) use principal as the preferred income base and to compute per-unit prices. When principal is absent, the income calculation falls back to FV, not the reverse. Principal and acquisition cost are not interchangeable measures.

This is a source inspection of the shared construction and relevant consumers, not a certification that every per-CIK correction has never used another proxy.

**Owner decision:** "the first observed FV seems like an appropriate proxy". Use the first observed FV for the same position as a fallback when reported cost is missing. Preserve reported cost, including legitimate zero; missing reported cost remains missing in its source representation even when an analytical cost proxy is available. Record the donor observation/date, method and proxy status. Principal is not substituted for cost by this decision.

Cost-based analytics may use reported cost with this fallback, provided they disclose the proxy contribution and do not describe the result as wholly reported-cost data. This does not require a separate modeled-cost product page. Reported-only source-accuracy checks exclude proxy values from their verified numerator while retaining explicit coverage accounting. If no suitable FV exists, cost remains unknown. Donor eligibility and same-position selection must be tested; the choice does not certify the current partition key or its nonzero filtering as correct in every case. Donor timing must respect the history policy selected under D05.

**Validation:** source cost takes precedence; source zero is not replaced; two tranches of the same borrower cannot donate cost to one another. Save the selected donor anchor and date and produce identical selections on a reordered rebuild. A ratio with a zero denominator remains undefined. Illustrative case: FV 80 and absent cost may yield proxy cost 80 and zero change relative to that proxy, but this is not evidence of acquisition cost 80 or an independently verified zero markdown. Report proxy-dependent FV/rows separately.

### D03. How conservative should currency identification and conversion be?

**Basis:** F03; B1-B2, D1-D2. The crosswalk found source unit tokens such as `U_USD` that resolve to USD but currently miss the conversion route. Correctly resolving such a token is a deterministic fix, not inference.

**Clarification:** a USD-denominated loan needs no conversion. Its original principal is simply copied to the common USD-principal measure; recording an FX factor of 1 documents that identity. The defect is failing to recognize a token that already means USD. Website display currency does not establish the currency of the loan's principal: a EUR loan may already have FV reported in USD.

**Owner decision:** "we can assume USD unless otherwise stated". Apply USD as the default where the relevant source provides no contrary currency evidence. Preserve raw unit/currency evidence and distinguish `assumed_usd` from explicitly established USD in lineage; the default is usable but is not a verified source assertion. A filing-wide or position-specific currency declaration counts as source evidence when applicable. Borrower geography alone does not override this policy.

If EUR is disclosed but no FX rate is supplied, use an approved dated reference FX rate. Missing FX for a known foreign currency does not justify assuming USD. If the source indicates non-USD but the particular currency cannot be resolved, keep the conversion unresolved rather than invoking the default. A malformed or unresolved nonempty XBRL unit needs investigation; do not treat a parsing failure as source silence.

**Validation:** explicit USD and assumed USD copy principal unchanged but retain different evidence statuses; explicit non-USD evidence wins over the default. Foreign principal uses the approved dated FX convention; missing FX remains unresolved. Include a German borrower with a disclosed USD loan as a counterexample to country-only inference. Do not convert already-USD FV/cost because principal is foreign-denominated. Principal and valuation currency must be independently attributable; no common currency field may silently override source units for other monetary values. Report assumed-currency coverage separately from verified-currency coverage.

**Still to specify during implementation design:** the FX source and date convention for disclosed non-USD positions. The default decision does not authorize external data purchases or downloads.

### D04. Which percentage should users see by default?

**Basis:** F04; B1, B3-B4, E2. All options preserve three separate meanings: reported %NAV, calculated FV / comparable fund NAV, and FV / the declared portfolio FV population. The same field must not silently switch meanings.

**Clarification:** 0.02 and 2% are two representations of the same proportion. This decision is about the denominator. For an illustrative fund with investments worth $200m, liabilities of $100m and NAV of $100m, a $10m holding is **5% of investments** but **10% of NAV**. Both are meaningful; they answer different questions. The current [holdings table](../../frontend/src/components/FundHoldingsTab.tsx) already labels its column `% Portfolio`, derived in [fund exports](../../pipeline/export/fund_exports.py) from the selected holdings' FV total. Keeping that display is option A, not a new dashboard concept. Its existing positive-FV filter still needs the accepted population checks.

**Disposition:** the owner has "no further comment" after the explanation. Retain the existing portfolio-weight display; no new UI choice is needed. Preserve reported %NAV, calculated FV / compatible NAV and portfolio weight as separate meanings in the financial contract. Do not silently replace source percentages or add another public percentage column merely because the schema can represent it.

**Validation:** illustrative FV 10, portfolio FV 200 and NAV 100 produce 5% portfolio weight and 10% calculated NAV exposure. A leveraged portfolio can legitimately sum above 100% of NAV. Missing or incompatible NAV prevents the derived NAV ratio; the calculation requires aligned quarter, currency and consolidation scope.

## 4. History, identity and classification decisions

### D05. Should historical data reflect our best current understanding or what was known then?

**Basis:** F06; A3, C4, D1-D2, F2. Current output selects later amendments and can apply later enrichment or full-history corrections. Source lineage and reproducible releases are already required; a full historical information-cutoff product has not been requested.

- **A - Latest-best history (accepted).** Publish corrected historical observations using explicit source precedence, with original evidence retained and changes traceable by release. Identify which historical values depend on later corrections/enrichment. Do not claim this is an as-known-then predictive dataset.
- **B - Both latest-best and as-known-at-cutoff history (not selected).** Add reproducible historical cutoffs across filings, corrections, identities and enrichment decisions. This supports predictive backtesting but substantially expands data-version reconstruction and validation.

**Validation:** an amendment produces the correct source-linked revision; the earlier released result remains reproducible. Later corrections/enrichment retain their actual decision and source dates. A later observation must not be represented as an earlier reported fact. Reproducing a release does not certify historical information-cutoff safety; that product is outside the accepted scope.

### D06. How should partial maturity dates enter numerical analytics?

**Basis:** F07; B1-B2, C3, E2. Preserve original wording, exact/month/year precision, unknown reason and supported perpetual status.

**Owner decision:** use end-of-month where the filing supplies a month/year, unless a more specific applicable convention already supplies a date. This is a calculation convention; it does not depend on a typical loan-signing day. A missing maturity stays blank. A year-only value does not supply a month and is not assigned an invented month by this decision.

**Existing convention verified:** [BDC staging](../../pipeline/staging_bdc.py) uses DuckDB `last_day` for its month/year fallback and preserves a valid supplied exact date first. The [HTML bridge](../../pipeline/bdc_xbrl_html_bridge.py) also uses month-end for recognized month/year forms. Retain this month-end convention, preserving the distinction between an exact source date and a calculated representative date. Source-backed exact terms take precedence; any differing applicable per-CIK convention must have its scope/evidence recorded rather than being silently overwritten.

**Validation:** `June 2029` gives representative date `2029-06-30` with month precision; `2029-06-15` remains unchanged. Include February/leap-year cases and missing dates. Matching respects the underlying precision so a calculated day does not create a false exact-day veto. An unusual far-future date is not automatically perpetual; unsupported sentinels remain unresolved. Perpetual/unknown records do not become artificial finite maturities.

### D07. Is company concentration primarily at borrower level or corporate-group level?

**Basis:** F12 and entity assessment; C1-C2, E2. Within-filer instrument continuity and cross-filer company resolution are already in scope. This choice concerns grouping meaning, not whether identities should be stable.

- **A - Resolve the disclosed borrower/company, retain evidenced group links (accepted).** Keep distinct supported borrower identities separate. Record parent/operating-company/group relationships when evidenced; leave uncertain relationships unresolved. Default concentration uses the resolved borrower/company basis.
- **B - Also require corporate-group concentration (not selected).** Keep A's identities and add a versioned group rollup for concentration across related borrowers, with effective dates and relationship evidence. This adds research, coverage and validation work.

**Validation:** identical or similar names do not alone justify merging borrowers; shared ownership does not make two instruments identical. Test alias/name-change, unrelated same-name, parent/subsidiary and ownership-change cases. Borrower totals reconcile to their stated holdings population without duplicating exposures. Recorded group relationships retain evidence and effective dates where available; unknown group membership does not block borrower-level acceptance.

### D08. How much look-through analysis belongs in this release?

**Basis:** F10; A5, B3-B4, E2. Relevant cash, JV interests, subsidiary and underlying records stay available. The accepted headline remains the canonical holdings sum; it is not automatically a consolidated or ownership-adjusted exposure total.

- **A - Preserve relationships and separate reconciliation populations (accepted).** Make retained records and available parent/underlying relationships inspectable. Validate each against the right source total; disclose basis differences. Do not promise an ownership-adjusted look-through portfolio analytic.
- **B - Also calculate look-through exposure (not selected).** Add a separate analytical view that replaces eligible parent interests with appropriately ownership-adjusted underlying exposures, using supported ownership, scope and dates. Preserve A's source observations and the accepted public headline.

**Validation:** a parent investment of 100 and an underlying schedule of 200 are not assumed to represent 300 of comparable exposure; amounts alone cannot establish a 50% ownership ratio. Missing relationship evidence or incomplete underlying coverage remains explicit. Cash balances and investment-schedule cash instruments must be distinguished for source anchors. Acceptance requires record retention and correct accounting populations, without requiring a modeled ownership allocation.

**Headline contract:** retain the canonical holdings sum; D08 does not change it to consolidated or ownership-adjusted exposure.

### D09. How specific must a published GICS assignment be?

**Basis:** F06/F11 and enrichment assessment; D1-D3, E2. Versioned decisions, inference labels, source evidence and abstention are already required.

**Owner decision:** sector is the only required GICS level; deeper classifications are useful if available but are not necessary for release. This matches the current [homepage](../../frontend/src/app/page.tsx), [fund exposure](../../frontend/src/components/ExposureSection.tsx) and [fund peer comparison](../../frontend/src/components/FundPeersTab.tsx), which consume sector groupings even where the UI calls the chart industry exposure.

Support sector-level assignments directly; do not require an invented sub-industry just to populate sector. Preserve supported finer classifications when available, with their evidence, but do not impose a deeper-level coverage gate. A required sector capability does not mean forcing every position into a sector: unknown remains visible and counts in the sector coverage measure.

**Validation:** measure sector accuracy and coverage by method and meaningful exposure strata. Any finer levels that are published retain honest evidence/quality labels; a 95% sector-accuracy result does not certify sub-industry accuracy. All holdings remain in public FV totals, including unclassified records. Taxonomy changes and updated borrower evidence must be traceable.

## 5. Delivery and acceptance decisions

### D10. Which citation format should be delivered first?

**Basis:** F09 and source-navigation assessment; D4-D5, E1. Existing XBRL and HTML anchors are reusable; source-format coverage is not yet inventoried.

**Owner decision:** prioritize source click-through using HTML/inline XBRL; PDF highlighting is lower priority and may be deferred without blocking the core release. PDF renditions can be considered later. If generated, identify them as renditions and validate their source/page mapping; generating a PDF alone does not establish a correct highlight.

**Tool identified:** the owner confirmed, "it was arelle". Record **Arelle and its iXBRL Viewer for evaluation**; identifying the earlier recommendation does not itself select a replacement extractor. Arelle supplies XBRL processing/validation interfaces; its viewer prepares inline filings for interactive inspection of tagged facts. Prepared reports can use a locally served viewer bundle. [Arelle](https://github.com/Arelle/Arelle), [iXBRL Viewer](https://github.com/Arelle/ixbrl-viewer) (official project documentation checked 2026-09-09).

Evaluate reuse of cached filings and required taxonomy resources, preservation/mapping of fact and context IDs, exact passage navigation and compatibility with existing extraction rules. Runtime preparation must not silently download missing resources. A viewer does not itself provide lineage from a corrected/aggregated/inferred public value to the relevant source facts; that integration remains required. No installation, parser replacement, external service or automatic extraction-quality improvement is assumed.

**Validation:** click tests must check the passage actually supports the value, not merely that the document opens. Calculations expose inputs/formula and their citations; an inferred GICS assignment opens its evidence/method, not a misleading highlight implying the code was reported. Set coverage targets after inventory; neither choice makes an unavailable citation a pass.

### D11. What should happen when a required historical observation lacks usable XBRL data?

**Basis:** historical coverage assessment; A1-A3, D1, E1-E2. The current 70-fund cohort is not the operating-fund denominator for every historical quarter. Lifecycle eligibility must be established.

- **A - XBRL-focused core with measured gaps (accepted).** Use cached structured facts and existing source-backed recovery paths. Keep eligible missing fund-quarters in the coverage denominator and exception register. Evaluate the release against approved coverage targets; gaps outside tolerance remain failures pending remediation or an explicit exception.
- **B - Targeted additional HTML recovery (not selected).** Add extraction work for eligible material gaps lacking sufficient structured data. Validate recovered schedules independently and apply the same financial/evidence contracts. This improves potential coverage with more filer-specific maintenance.

**Validation:** distinguish not-operating, missing filing, unusable tagging and extraction failure; absent output alone proves none of them. Test complete schedules, not only found rows. Comparative selection must preserve reporting/disclosure dates and avoid duplicate historical positions. Both options respect cached-only operation unless separately authorized.

The accepted scope does not waive historical coverage failures or add a new HTML recovery campaign. Optional Q4 2022 remains optional.

### D12. When should we freeze the numerical thresholds?

**Basis:** F05 and the owner's acceptance qualification; A2, B2-B3, C2-C3, D3-D5, E3. The accepted framework contains numerical proposals but leaves field-specific tolerance, assessability floors, sample sizes and several coverage measures undefined.

- **A - Define, baseline, then freeze before remediation (accepted).** Complete a bounded measurement exercise using the accepted scope, preserving the section 4 proposals as starting targets. Present precise denominators, independent reference coverage, current results and feasibility trade-offs. The owner then approves the final numerical gate before agents optimize against it.
- **B - Freeze the proposed numbers now (not selected).** Treat the listed 99% FV / 95% row completeness and purity, 0.25% aggregate / 1% per-fund reconciliation, 99.5% link precision / 95% recall and 95% GICS-sector accuracy as firm targets. Missing definitions still must be resolved before evaluation. This offers earlier target certainty but may require more work or an explicit later revision.

**Required controls:** exact consistency checks can be specified now. Do not tune a denominator or benchmark after observing errors to make a target pass. Independently reviewed samples include apparently passing funds, difficult cases and the long tail; held-out acceptance cases stay separate from development cases. Preserve failed results and explain any proposed threshold change. Acceptance of D12 approves this process; it does not freeze the proposed numbers or change the live gate.

**Measurement deliverable:** criterion ID, formula/invariant, eligible population, exclusions, reference source, row/FV weighting, uncertainty/sample rule, current baseline, target, executable check and saved artifact. Particularly unresolved are per-fund coverage floors, numeric-field tolerances, chain completeness, enrichment coverage, highlighted-passage coverage and product latency.

### D13. How much of the agent subsystem should be redesigned alongside dbt?

**Basis:** F05/F11 and preparation plan P2; F1-F6. dbt migration is accepted. The earlier production stack plan limited agent changes; the programme now also requires working persistence, evidence and release integration. Those necessary integration changes cannot be avoided by treating the old boundary as immutable.

- **A - Preserve roles, fix required integration and control gaps (accepted).** Retain agent proposal, deterministic verification and promotion responsibilities. Permit changes to their contracts, inputs/outputs, checkpoints and known defects where needed to satisfy the accepted programme. Choose concrete dbt/Python boundaries during architecture design. This scope decision supersedes the earlier stack-plan restriction where required integration and control fixes need agent-subsystem changes.
- **B - Redesign the agent workflow as well (not selected).** Revisit roles, queueing and operator workflow as an additional deliverable. Keep independent acceptance and promotion safeguards, but budget for broader behavioral and migration validation.

**Validation:** migrated transforms reproduce unaffected behavior and document intended corrections. Check interruption/retry, duplicate promotion prevention, stale-input rejection, gate enforcement and signed-quarter regressions. SQL parity alone is not programme acceptance. Neither option authorizes dispatch, changes the existing fleet limits or requires a new orchestration product merely for architectural neatness.

## 6. Complete F01-F12 disposition and proposed authority

This map connects the accepted product choices to required engineering corrections. The authoritative implementation files below are starting homes to reconcile, not permission to preserve contradictory definitions.

| Finding | Disposition | Owner choice | Existing authority to retain or reconcile | Acceptance / test obligation |
|---|---|---|---|---|
| F01: rate meaning | **Retain target; correct storage/consumers; clarify uncertainty.** | D01 | Financial contract plus existing convention/grammar evidence; rate and income consumers migrate together. | B1/B2/B5: no double PIK; distinguish yield, cash and all-in; eligible coupon coverage. |
| F02: cost proxies | **Preserve source cost; implement approved first-observed-FV fallback with lineage.** | D02 resolved | Reported source cost and separately attributed proxy; consistent export eligibility. | B1/B2/D1: preserve zero, donor identity/date and proxy contribution; coverage-aware ratios. |
| F03: currency | **Correct unit resolution; implement USD default with explicit assumption status.** | D03 resolved | Source XBRL units, conversion/default policy and existing FX/currency fields. | B1/B2: explicit versus assumed USD, foreign FX, contrary evidence and independent valuation currency. |
| F04: %NAV | **Separate meanings; retain existing portfolio-weight display.** | D04 closed | Financial denominator definitions and lineage, then shared derived metrics. | B1/B3/B4: aligned denominator; source value preserved; no forced 100% NAV sum. |
| F05: validation/enforcement | **Correct contradictions and wire final gates.** | D12 governs risk numbers, not whether enforcement exists. | Reconcile `COLUMN_CONTRACTS`, physical schemas and quarter thresholds; preserve their distinct responsibilities. | F3/F5: check final post-overlay artifact; structural invalidity and stale/mixed release inputs cannot pass. Weak flags remain diagnostic unless explicitly promoted. |
| F06: historical information | **Publish latest-best history; retain source evidence; extend enrichment versions.** | D05, D09 resolved | Filing precedence, release manifests and versioned enrichment decisions. | A3/D2/F2: reproducible releases, amendment/enrichment lineage and declared information-cutoff limitations. |
| F07: maturity precision | **Retain month-end fallback; preserve source precision and exact-date precedence.** | D06 resolved | Existing maturity/HTML evidence; one shared interpretation for matcher and analytics. | B1/C3: exact versus month-end approximation/perpetual/unknown; no false day-level veto. |
| F08: absent versus negative evidence | **Correct and extend consistently; settled requirement.** | None needed to preserve unknown. | Existing strict PIK statuses; source coverage and non-accrual evidence. | B5/D1/E2: unknown stays unknown; a terms-started event is not proof of distress. |
| F09: normalized versus verbatim identifier | **Retain working keys; correct descriptions; extend citation resolution.** | D10 chooses format only. | Existing correction/matching keys plus raw document anchors; no requirement to duplicate verbatim text in every table. | D1/D4/D5: normalized text is not presented as a source quote; citations resolve exact source wording. |
| F10: population basis | **Retain rows/public sum; clarify each analytic basis.** | D08, D11 | Cohort manifest, published-basis definitions, explicit conservation/analytic populations. | A1/A5/B3/B4: no hidden drops, scope drift or source-anchor double counting. Paused threshold rollout follows explicit gate decisions. |
| F11: documentation/verification drift | **Correct documentation and map coverage; no new schema framework required.** | D13 only where agent workflow scope changes. | Existing schema reference, `output_schemas.py`, field validators and provenance ledger. | B1/D1/F1: distinguish supported, populated and verified fields; reported UGL is distinct from derived FV minus cost. |
| F12: identifier guarantees | **Retain identity layers; complete stability and join contracts.** | D07 concerns company/group meaning. | Existing row anchors, position registry/matcher and entity resolver; choose implementation after collision/lifecycle tests. | C1-C4/F2: stable rebuild/reorder results, traceable merges/splits, no run-local PIK key used as a durable join. |

Keep one authoritative financial meaning per field and one declared writer per released artifact. Extraction schemas, correction-proposal schemas and serving payloads may remain distinct. Consolidating authority does not require flattening them into one table or moving every operation into dbt.

## 7. Recording decisions and proceeding

**Resolved:** all D01-D13. Earlier dispositions remain: D01 (no missing-rate inference), D02 (first observed FV as a labeled missing-cost proxy), D03 (assume USD unless otherwise stated), D04 (retain existing portfolio-weight display), D06 (month-end for month/year maturity, preserving more specific source terms), D09 (sector required; deeper levels optional), D10 (HTML/inline-XBRL citation priority; PDF lower priority).

**Owner acceptance of uncommented recommendations, 2026-09-09:** "the items with no comments are resolved". Record option A for D05 (latest-best history), D07 (borrower/company resolution with evidenced group links), D08 (retained relationships and separate accounting populations), D11 (XBRL-focused core with measured gaps), D12 (define and baseline before freezing numerical gates), and D13 (preserve agent roles and fix necessary integration/control gaps). These dispositions are reflected in the outcome framework and preparation plan. No decision-sheet selection remains open.

The [target contract](programme_target_contract.md) and crosswalk extension provide the field/relationship authority map and schema deltas; the [measurement register](programme_measurement_register.md) maps each criterion to formulas/invariants, target status, evidence and remaining checks. The later [units/identity contract](programme_units_fx_identity_contract.md) specifies technical conventions. Remaining population validation, real FX integration, rule-authority implementation and Arelle integration belong to engineering packages. Final calibration follows the accepted amendment process; it is not a renewed vote on these policies.

Documentation verification: all twelve F findings remain mapped; all thirteen decisions have an explicit status and validation obligations. Source inspection answered the proxy, percentage-display, maturity and sector questions; no fresh population counts were measured. Criterion references/relative links checked. No tests, rebuilds, exports, live-threshold changes, SEC calls or model enrichment performed.
