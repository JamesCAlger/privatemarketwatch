# BDC holdings programme: accepted outcome acceptance framework

Date: 2026-09-09. Status: **accepted by the owner on 2026-09-09 as the programme's outcome framework, with measurement detail still incomplete**.

Acceptance record: "i accept this document as is, noting that there are not that many hard measurable metrics to validate against yet". Scope and outcome requirements are accepted. Section 4's numbers retain their stated provisional status; missing thresholds, denominators, benchmark definitions and executable checks still need to be specified. This acceptance is not evidence that the system meets the requirements or a change to the live gate. The existing filename is retained to preserve links.

Owner refinements from the [decision-sheet review](programme_decision_sheet.md), 2026-09-09: do not infer missing interest rates; GICS sector is the required depth and finer levels are optional; prioritize HTML/inline-XBRL source highlights and make PDF highlighting/renditions lower priority and deferrable.

Further financial dispositions, 2026-09-09: first observed FV is an acceptable labeled proxy for missing cost, preserving reported zero and donor evidence; assume USD unless the source states otherwise, distinguishing the assumption from explicit currency evidence; retain the current portfolio-percentage display; use the existing month-end convention for month/year maturity while preserving source precision and more specific dates.

Final decision-sheet disposition, 2026-09-09: the owner confirmed "the items with no comments are resolved", accepting option A for D05, D07-D08 and D11-D13. All thirteen decisions are resolved. Publish latest-best history; resolve borrowers/companies with evidenced group links; retain look-through relationships and separate accounting populations without requiring ownership-adjusted analytics; use an XBRL-focused core with measured gaps; define and baseline metrics before freezing the final gate; preserve agent roles while fixing required integration/control gaps. Numerical thresholds, authoritative implementation homes and detailed validation remain to be completed under those decisions.

This document defines the outcomes the target schema and architecture must support. It deliberately does not prescribe tables, column names, storage layout or dbt model boundaries. Develop those next, alongside detailed acceptance tests.

Inputs: [current-state assessment](current_state_assessment_2026-09-09.md), [current architecture](../reference/current_architecture.md), [financial/schema crosswalk](../reference/unified_holdings_contract_crosswalk.md) and [preparation plan](consolidation_readiness_plan.md). Existing operational safeguards and live thresholds remain in force until explicitly replaced.

## 1. End-state and scope

The programme is complete when a reproducible release candidate is **ready for owner approval**, with the required data, product functionality, target architecture implementation and saved acceptance evidence. This does not authorize deployment, baseline replacement or publication.

The release covers:

- The authoritative approximately 70-BDC cohort, with a documented historical eligibility decision for each fund-quarter.
- Quarterly position-level holdings and permitted fund/aggregate analytics from **Q1 2023 through Q1 2026**, inclusive, published as latest-best history with source-linked revisions and reproducible releases. An as-known-at-cutoff historical product is outside scope.
- An **optional Q4 2022 opening snapshot**, using available XBRL-tagged facts/comparatives where practical. Defer it with a recorded reason if reconstruction would materially delay the core programme; no separate pre-XBRL extraction campaign is required. Its absence does not block core acceptance or Q1 2023 holdings coverage. If deferred, mark opening-dependent transitions/calculations unavailable rather than inventing starting positions.
- A **lower-priority Q2 2026 forward-processing test**, after Q1 2026 is reproducible and accepted. Run with frozen rules where cached filings are sufficient. If deferred or inputs are insufficient, report its status and missing inputs separately; it does not block core acceptance. Do not claim an unexecuted test passed or silently download filings.
- Borrower/company resolution within/across filers and time, retaining evidenced group relationships; corporate-group concentration is not a required analytic. Position continuity between quarters; enrichment including inferred GICS sectors (finer levels optional); complete holdings access and value-to-source click-through using HTML/inline XBRL. PDF highlighting/renditions are lower priority and may be deferred without blocking core acceptance.
- Retained cash, JV/subsidiary and underlying records, inspectable relationships and separate source-reconciliation populations. Ownership-adjusted look-through analytics are not required; the canonical public holdings sum remains unchanged.
- An XBRL-focused core using cached structured facts and existing source-backed recovery paths. Eligible missing observations remain in coverage denominators and the exception register; an additional HTML recovery campaign is outside scope.
- Migration of the agreed transformation scope to dbt, with versioned inputs, explicit dependencies and resumable execution. Preserve agent proposal, deterministic verification and promotion roles; required interface, persistence and control fixes are in scope, while a broader workflow redesign is excluded.

No public index product or non-BDC product expansion. Distinct instruments belonging to one borrower remain separate positions. **Instrument/position identity is scoped within each filer across quarters. Cross-filer company/entity resolution is required; cross-filer instrument matching is out of scope.** A common borrower does not establish that two filers hold the same loan or tranche; available loan terms may be insufficient to establish that identity.

Delivery order: establish reproducible Q1 2026 data and acceptance, complete the required Q1 2023–Q1 2026 history, then prioritize the forward test. The focus is getting XBRL-tagged data into shape. Optional opening-history work must not delay that objective. These scope decisions do not approve the numerical proposals below.

## 2. How acceptance works

Three requirement types apply:

| Type | Meaning |
|---|---|
| Exact | A deterministic contract: no unexplained violations in the candidate release. Examples include internal totals, identifier uniqueness and artifact consistency. |
| Toleranced | Source coverage or measured accuracy where residual error can be acceptable. Requires an approved threshold, eligible denominator and measurement method. |
| Functional | A capability demonstrated through reproducible end-to-end scenarios and saved evidence. |

The observed approximately 0.16% difference between public FV and saved holdings is not a measured source error rate. Financial source reconciliation may allow a tolerance; outputs derived from the same holdings must agree exactly before presentation rounding.

Every criterion below must ultimately record: metric version, population, numerator/denominator, reference evidence, threshold, actual result, exclusions, run/input identities and verdict. Results are evaluated **per required quarter** as well as overall. A strong recent quarter cannot compensate for an unacceptable earlier quarter.

An exclusion must have an evidence-backed reason and remain visible in the obligation/coverage report. Missing inputs, unresolved classification or absent source evidence cannot simply be removed from denominators. Report unavailable measurements as unknown, not zero error or a pass.

## 3. Outcome acceptance matrix

### A. Scope, history and position completeness

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| A1 | Every cohort fund-quarter is accounted for. | **Exact:** 100% of cohort x required-quarter combinations have an evidenced status: eligible, not yet operating, ceased/merged, filing unavailable, or another approved reason. An eligible fund with missing data remains a coverage failure. | Versioned cohort and fund-quarter obligation register; source references for lifecycle decisions. |
| A2 | Eligible disclosed positions are captured without admitting totals or duplicates. | **Toleranced:** measure source-position recall and published-position precision, by row and absolute FV, per quarter and per fund, using A5's explicit record populations. Show missing positions and extra/subtotal/duplicate rows separately. Targets proposed in section 4. | Independently checked source schedules/reference rosters; matched/missing/extra row ledger. |
| A3 | Historical observations refer to the correct period and disclosure. | **Exact:** latest-best history has reporting-period and source-version attribution for every published observation. Comparative/amended filings follow explicit precedence; no unexplained duplicate observations for the same source-defined lot. Later corrections/enrichment retain their actual evidence and decision dates; earlier releases remain reproducible without claiming as-known-at-cutoff safety. | Historical selection tests, comparative/amendment cases, source accession lineage and release revision records. |
| A4 | Optional opening history and the lower-priority forward test have explicit dispositions. | **Functional, conditional:** if undertaken, Q4 2022 has its own coverage/verdict and tested opening-to-Q1 transitions. After reproducible Q1 2026 acceptance, Q2 2026 runs with frozen rules where inputs permit; defects and subsequent changes are reported separately from the initial result. Either activity may be deferred without blocking core acceptance, with reason and downstream limitations recorded. | Separate status records and, when executed, test reports; input sufficiency and opening-dependent limitations. |
| A5 | Relevant cash, JV/subsidiary and look-through records are retained with explicit accounting scope. | **Exact:** distinguish cash, direct investments, interests in JVs/subsidiaries and underlying look-through exposures. Preserve source anchors, relationship evidence and record-level inclusion flags. Source rosters and reconciliation anchors state which population they cover; parent interests and underlying exposures are not added together against the same economic total. No global cash/JV/look-through exclusion to satisfy a gate. Preserve current subsidiary retain-and-flag and published same-holdings sum contracts pending any explicit basis decision. | Source-backed parent/underlying examples; cash versus investment-total anchors; tests for legitimate retention, subtotal exclusion and prevention of double counting within a reconciliation basis. |

### B. Financial meaning and numerical accuracy

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| B1 | Financial fields have one authoritative meaning. | **Exact:** each published field has approved meaning, unit/currency, period basis, applicability, null policy, source precedence and calculation/evidence category. No unresolved material ambiguity in rate, principal, cost, FV, NAV denominator or PIK semantics. | Financial decision sheet extending F01-F12; field contracts and source-backed examples. |
| B2 | Position amounts and rates faithfully represent source disclosures. | **Toleranced:** field-specific accuracy on eligible disclosed observations, including magnitude/unit/currency errors. Report FV-weighted and row-weighted results, material exceptions and evidence coverage. Source rounding is distinct from extraction error. **Exact:** missing/unsupported interest rates remain blank; public analytics must not silently estimate them using peer rates or assumed benchmarks. Arithmetic from sufficient disclosed terms remains calculated evidence. | Raw-fact checks plus independent, stratified source review; currency/rate-scale cases; missing-rate and downstream-income eligibility checks. |
| B3 | Holdings reconcile to independent fund totals on a comparable basis. | **Toleranced:** report absolute discrepancy for each assessable fund-quarter and aggregate absolute discrepancy; never let positive and negative errors cancel. Use A5's record populations to bridge cash, subsidiary/JV interests and look-through exposures to the appropriate source anchor. A balance-sheet cash fact is not automatically part of an investment-schedule total. | Independent reported totals, record-to-anchor scope mappings, basis bridges, absolute-dollar and percentage residuals. |
| B4 | All public aggregations agree with the accepted holdings. | **Exact:** headline FV, instrument donut and industry donut equal the same cohort-quarter holdings sum before display rounding. Unknown classifications remain visible buckets. No scaling, overlays or hidden filtering to make totals agree. | Automated reconciliation across holdings, export payloads and displayed metrics. |
| B5 | PIK and rate analytics communicate the evidence actually available. | **Exact:** terms, current accrual/payment evidence and stressed amendments remain distinct. Unknown is not false. The all-in-rate storage change and dependent income formula change together. | Known-positive, known-negative and unknown examples; atomic migration/regression tests. |

Approved applications of B1-B2: a missing reported cost may use first observed position FV as an explicitly attributed analytical proxy; an undisclosed currency defaults to assumed USD only where no source evidence indicates otherwise; a month/year maturity may use a month-end representative date with month precision retained. These values remain distinguishable from reported facts and cannot increase the source-verified numerator merely because the rule was applied. Proxy-dependent cost analytics must identify the proxy contribution. Known foreign currency with unavailable FX remains unresolved. Exact maturity dates and legitimate zero costs are preserved.

### C. Entity identity and temporal position matching

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| C1 | Entity identities survive rebuilds and preserve meaningful distinctions. | **Exact:** unchanged entities retain identity under identical/reordered inputs; corrections, merges and splits have a traceable version/alias history. Parent/subsidiary and legal-entity versus commercial-group meanings are explicit. | Rebuild/reordering tests and reviewed merge/split cases across filers and quarters. |
| C2 | Entity links are accurate and sufficiently complete. | **Toleranced:** precision and recall on independently adjudicated within-filer, cross-filer and temporal samples, including ambiguous names and hard negatives. Abstentions count toward unresolved coverage. | Held-out reviewed entity benchmark, error categories and confidence intervals. |
| C3 | Different instruments remain distinct and continuing positions stay linked within each filer. | **Toleranced:** precision and recall of within-filer quarter-to-quarter links and complete expected chains, including zero-FV, maturity changes, name changes, amendments and gaps. No borrower-level collapse of distinct tranches or inferred cross-filer instrument equivalence. | Held-out within-filer pair and chain benchmarks with unmatched/ambiguous cases, not just accepted links. |
| C4 | Position identity and transitions remain auditable. | **Exact:** stable identity contract across rebuilds; source-row identity is separate from economic position identity. New holdings, exits, uncertain links and supported restructurings have explicit states; absence alone does not establish an economic sale. | Identity lifecycle tests, transition lineage and explicit restatement policy. |

### D. Enrichment, evidence and source navigation

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| D1 | Users can distinguish reported, calculated and inferred values. | **Exact:** every published value has an evidence category and traceable derivation. Composite derivations preserve both reported and inferred inputs. Mapping a reported industry label to GICS does not become an explicitly reported GICS code. | Field-level evidence audit; examples of each category and mixed derivations. |
| D2 | Enrichments are reproducible and honestly qualified. | **Exact:** decisions retain source/input, entity binding, method/model/config/taxonomy version, original decision time and review status as applicable. Unsupported assignments abstain except for explicitly approved defaults such as D03's assumed USD, which remain labeled assumptions; no inference silently overwrites source disclosure. Approved proxies preserve donor evidence and do not become reported facts. | Versioned decision records and repeatable cache application; stale/changed-evidence, proxy-donor and default-override cases. |
| D3 | GICS and other published enrichments meet measured quality/coverage targets. | **Toleranced:** GICS sector is the required classification depth; finer classifications are optional if available and supported, with no mandatory deeper-level coverage gate. Evaluate sector accuracy and coverage separately by method and material exposure; unknown remains explicit. Any finer published values retain honest evidence/quality labels. Self-reported model confidence is not the accuracy metric. | Independently reviewed held-out sample; sector error tables and unresolved FV/rows; evidence for any optional finer classifications. |
| D4 | A user can navigate from a number to its supporting evidence. | **Functional:** clicking a reported number opens the exact source with the supporting passage highlighted, prioritizing HTML/inline XBRL. PDF highlighting/renditions are lower priority and may be deferred without blocking core acceptance. Calculated values expose contributing records/formula; inferred values expose inference evidence and method. | End-to-end cases for direct values, aggregates, corrected values, inferences and historical filings; separately recorded PDF delivery/deferment status. |
| D5 | Citation coverage and failures are explicit. | **Exact:** every in-scope numerical display offers an evidence path or an explicit unavailable reason; never a misleading generic filer link presented as a citation. **Toleranced:** highlighted-source coverage target must be approved after the source-format inventory. A PDF is not required where the correct source highlight is provided in HTML/inline XBRL. | Citation resolver audit plus visual verification of passage correctness; missing-source register. |

### E. Product completeness and usability

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| E1 | Users can access the full accepted holdings history. | **Exact/functional:** all accepted positions and required quarters are accessible through the agreed product interface, beyond a latest-quarter top-20 selection. Filters/pagination preserve counts and totals. | End-to-end reconciliation of accessible records to released holdings; history/filter scenarios. |
| E2 | Public analytics expose their basis and limitations. | **Exact:** quarter, eligible population, denominator, exclusions and evidence/quality status accompany relevant analytics. Unknown classifications or unmatched positions are not silently dropped. | UI acceptance examples and export-contract checks. |
| E3 | The product remains within v1 scope and is usable at cohort scale. | **Functional:** holdings, fund analytics, evidence and history work at full volume with an approved interaction-time budget. No public index/non-BDC expansion. | Production-size navigation/build tests; measured latency on declared test hardware/browser. Performance budget to be set during product design. |

### F. Architecture, reproducibility and autonomous execution

| ID | Required outcome | Measurement and acceptance | Evidence |
|---|---|---|---|
| F1 | The target architecture is implemented, not only documented. | **Exact:** every production transformation, correction, validation and export has one declared responsibility/owner and explicit dependencies. The agreed transformation scope runs through dbt; retained Python/agent boundaries are documented and justified. No hidden competing production path. | Approved target architecture; executable dependency graph; rule/authority map and entrypoint integration tests. |
| F2 | A release is a consistent, reproducible snapshot. | **Exact:** inputs, code/local changes, rules, schemas and enrichment decisions are versioned. Same pinned inputs produce semantically identical results. CSV/Parquet and downstream products agree; byte identity is unnecessary for volatile metadata. | Repeat-run semantic comparison, companion parity and release manifest. |
| F3 | Invalid or mixed-generation artifacts cannot become the candidate release. | **Exact:** candidate assembly consumes acceptance evidence for the same snapshot and fails closed on missing/stale required stages. Serving changes as one consistent bundle with a recoverable previous release. | Failed-gate, stale-dependency, partial-write and rollback scenarios. |
| F4 | Work resumes without recreating completed verified work. | **Functional:** interruption between stages and during a worker task leaves recoverable state. Completed valid stages are reused, incomplete writes are isolated, stale checkpoints invalidated and retries do not duplicate corrections. | Controlled interruption/restart drill, durable work packets and before/after output comparison. No dependence on preserving a model conversation. |
| F5 | Agents cannot redefine success to complete their tasks. | **Exact:** corrections retain mechanism, evidence, before/after metrics and residual risk. Acceptance assets and held-out expectations are independently governed. Attempts are bounded; unresolved meaning or failed validation produces a documented blocker. | Existing promotion controls extended where needed; adversarial/negative acceptance cases and blocked-task example. |
| F6 | Migration preserves supported behavior or explains its changes. | **Exact:** no unexplained semantic deltas or signed-quarter regressions. Intended corrections have source-backed expectations; unrelated shared backend behavior remains covered. | Targeted/full checks as appropriate, semantic deltas and signed-quarter reattestation. |

## 4. Proposed tolerances for discussion

These are **starting proposals**, not calibrated promises, current performance claims or changes to the live gate. Under accepted decision D12, define each metric and reference population, measure its baseline, then obtain owner approval of the final numerical gate before remediation against it. Exact invariants can be specified now. If a proposed threshold proves impractical, report why; do not automatically relax it.

| Area | Starting proposal | Qualification / unresolved decision |
|---|---|---|
| Source-position completeness and purity (A2) | At least 99% recall and 99% precision by absolute FV; at least 95% each by row count, per required quarter. | Independently referenced source roster required. Add per-fund floors after measuring coverage; aggregate success alone is insufficient. Zero/missing-FV positions remain in row measures. |
| Fund-total reconciliation (B3) | Aggregate sum of absolute discrepancies no more than 0.25% of comparable reported FV; ordinary per-fund tolerance no more than 1%. | Explicitly provisional. Approve an absolute-dollar/rounding floor and treatment of small or zero denominators. A material individual failure cannot hide behind the aggregate. Assessable-population coverage needs its own minimum. |
| Entity links (C2) | At least 99.5% precision and 95% recall on the reviewed benchmark. | Define benchmark units and legal-entity scope before freezing; report difficult strata separately. False merges generally cost more than abstentions. |
| Position links (C3) | At least 99.5% precision and 95% recall on reviewed links. | Chain completeness needs a separate target after baseline. Good pair accuracy does not imply complete multi-quarter chains. |
| Enrichment (D3) | GICS sector accuracy at least 95% on independently reviewed published assignments. | Sector coverage/FV target remains open. Finer levels are optional; evaluate/label any that are published without creating a mandatory sub-industry completion target. |
| Numerical fields (B2) | No single blanket tolerance across FV, cost, principal, rates and percentages. | Define materiality and source rounding per field in the financial contract; separately track wrong units, wrong basis and legitimate rounding. |
| Citations (D4-D5) | Exact correctness for tested links; automated referential checks across all released citation records. | Set actual highlighted-passage coverage after inventory. HTML/inline-XBRL highlights are the priority; PDF highlighting/renditions are explicitly lower priority and deferrable by owner decision. |

For sampled accuracy, always publish sample size, sampling design and uncertainty. Set minimum sample sizes and the statistical pass rule before remediation; a tiny sample with no errors cannot establish a high-precision claim. Benchmarks must include both material FV and the long tail, ambiguous cases, missing fields and legitimate counterexamples. Source reconciliation and numeric provenance remain separate measures.

## 5. Candidate completion and exception policy

Each required criterion has one status: pass, fail, blocked/unmeasured, or explicitly not applicable with evidence. A4 and D4's supplemental PDF work permit **deferred** under the owner-approved priority policy; deferred activities are not passes and do not block core completion. Core source click-through remains required. The approval package identifies the core verdict and these supplemental statuses separately. A programme is not complete because a script finished, a dashboard looks plausible, or a metric improved from baseline.

The approval package contains:

1. The implemented target architecture and authoritative schema/financial contracts.
2. A versioned candidate release manifest and per-quarter acceptance results.
3. Source, matching, enrichment and citation benchmark results with denominator/uncertainty disclosures.
4. An exception register identifying affected funds/quarters/fields, row and FV impact, mechanism, evidence, proposed disposition and residual risk.
5. Migration deltas, signed-quarter reattestation, restart/rollback evidence and operating instructions.

Residual error within approved tolerances can pass while remaining disclosed. A failure outside tolerance requires remediation or an explicit owner decision changing the contract/accepting that exception; agents cannot self-waive it. Such an exception stays visible in the final verdict and does not rewrite the measured result to pass. No silent scope reduction.

## 6. Remaining specification and measurement work

- Evidence-backed historical fund-quarter obligations and reason codes for source unavailability, preserving eligible missing observations in coverage measures.
- Numerical tolerance, materiality, per-fund floors and statistical benchmark rules, defined and baselined before final approval under D12.
- Borrower/company identity contracts and within-filer position lifecycle rules; retain evidenced group links. Corporate-group concentration is not required, and cross-filer instrument matching is excluded.
- Cash, JV/subsidiary and look-through record relationships, source-anchor populations and explicit analytic inclusion rules. Preserve the published FV contract; ownership-adjusted look-through analytics are not a release obligation.
- Remaining F01-F12 implementation detail, including cost-proxy donor eligibility, non-USD FX source/date convention and latest-best historical revision handling. The USD default, missing-cost proxy, existing percentage display and month-end maturity convention are resolved policies.
- Evidence representation for reported, calculated, inferred and corrected values.
- Core source-highlight coverage and viewer/tool integration; HTML/inline-XBRL priority and optional PDF work are now decided.
- dbt/Python migration boundary, required integration/control changes within the accepted agent roles, and product access/performance requirements.

First design deliverables added 2026-09-09: the [target contract](programme_target_contract.md), exhaustive [88-field disposition map](../reference/programme_field_disposition.csv) and [28-criterion measurement register](programme_measurement_register.md). These extend the existing holding grain with authoritative field families, required schema changes, relationship contracts, metric formulas/populations and evidence requirements. Existing results are explicitly dated starting observations; missing references, executable checks and comparable baselines remain visible. Complete the bounded SPEC dependencies and calibrate/freeze the final numerical gate before accepting programme remediation. These drafts implement the resolved policies without claiming either a completed migration or a measured programme PASS.

## Documentation verification

Documentation-only change. Relative links and whitespace checked; no tests, rebuilds, exports, downloads, threshold changes or production data writes required or performed.
