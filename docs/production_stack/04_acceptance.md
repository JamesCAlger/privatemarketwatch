# 04 Acceptance: populations, evidence, the gate and working targets

Consolidated 2026-09-12. Operationalizes the 28 accepted outcome criteria under [decisions](01_decisions.md). The gate is the live quarter-acceptance mechanism in `pipeline/quarter_acceptance.py` with thresholds in `data/reference/quarter_acceptance_thresholds.json`, extended as described in section 4. There is no separate programme evaluator. Current saved results are dated observations, not fresh runs.

## 1. Populations

**Refactor versus production acceptance, owner clarification 2026-09-14.** The numerical data and delivery thresholds below remain requirements for production readiness. The current refactor is complete when the required architecture, collectors and controls are implemented and verified, including isolated full-data integration, all-quarter evaluation/re-attestation, exact implementation invariants and required software/browser/recovery tests. A correctly measured data FAIL or evidence-dependent UNASSESSABLE result does not require B1/B2 or enrichment operations before that handoff. An absent collector or faulty evaluator is still an incomplete implementation. Pending floor adoption must be represented and tested as pending, never silently defaulted to a passing bar. Record operational residuals separately from implementation defects; actual refactor-induced regressions still require diagnosis and repair. See [decisions](01_decisions.md).

For each required quarter q:

- `O_q`: all cohort fund-quarter obligations with source-backed eligibility. The current 910-row register, `programme_pilot_evidence_2026-09-09/obligations_v2.csv`, gives 812 eligible, 98 pre-investment, 0 unresolved.
- `H_q`: all final retained holdings for the cohort and quarter across classifications and record kinds, bound to one release. This is the public population. Zero, negative and unknown-classification rows are members; missing FV is reported separately.
- `R_q`: the source position roster derived from XBRL investment contexts in cached instance documents, as built by `pipeline/source_reconciliation.py`. Rows with no XBRL context are outside `R_q` by design (D11).
- `A_q`: independent fund-quarter anchors with basis, currency and date: promoted anchor leaves, companyfacts `InvestmentOwnedAtFairValue` plus cash where a cash row exists, companyfacts investments at fair value. The filer's own schedule total is a fallback anchor and is not independent.
- `E_fq`: observations eligible for field f by instrument applicability and source disclosure. Eligibility is never inferred from whether the candidate populated the field.

Public totals use signed FV. Error and coverage weights use absolute FV. Source-side weights use source FV, never the candidate's value.

## 2. Evidence sources and what each proves

No HTML reader. These five sources are the whole evidence base.

| Source | Module | Proves | Cannot prove |
|---|---|---|---|
| XBRL-context reconciliation | `source_reconciliation.py` | Which tagged source positions are missing, extra or mismatched; blocking source-only rows by mechanism | Anything about untagged rows: an untagged fund reconciles perfectly |
| Fund-level totals | `shadow_conservation_engine.py`, `published_basis.py` | Aggregate over- or under-inclusion per fund-quarter against companyfacts or a promoted anchor | Which rows are wrong; funds with no anchor are unassessable, not bad |
| Provenance replay | `provenance_reverify.py` | Each stored numeric field replays from its cited fact and declared transforms (eight fields, about 99.75% of Q1-2026 FV) | Completeness; a correctly copied subtotal still replays |
| Cross-quarter continuity | `position_matching.py`, chain audits, exposed mg3 packets | Unexplained appearances and disappearances, chain breaks, same-period collisions | Which side of a mismatch is right without adjudication |
| Published-basis invariants | `published_basis.py`, export checks | Exact equality of headline and partitions; companion parity; ID fill | Source correctness |

**Exception class, source-backed per fund-quarter.** An eligible fund-quarter with zero output rows is classified by a deterministic collector that reads the cached XBRL instance of the selected filing. Candidate contexts carry investment facts (`InvestmentOwnedAtFairValue`, `InvestmentOwnedAtCost`, `InvestmentOwnedBalancePrincipalAmount` or their versioned filer-extension equivalents). These concepts also occur on totals: the concept name alone does not establish a position. Count each candidate context once, regardless of its number of facts, and use its economic period to select the target quarter; comparative periods remain separate. Incomplete source reads or unresolved concept/period mappings cannot establish absence.

Every candidate context has exactly one source-backed role. Record its document, period, dimensions, supporting facts and classification reason:

| Context role | Count | Required evidence |
|---|---|---|
| `confirmed_position` | `P` | The context identifies an individual disclosed investment, instrument or lot within an accounting scope. Source-backed explicit-member patterns can qualify even when extraction does not recognize them; zero or negative FV does not disqualify them. |
| `aggregate` | `A` | The context represents a fund total, subtotal or category total, supported by its source dimensions and accounting basis. A monetary concept, absence of dimensions or extractor rejection alone is insufficient. These contexts never count as positions. |
| `unresolved` | `U` | Evidence does not establish either role, or interpretations conflict. Unknown dimension or concept patterns remain here until resolved; they cannot support a no-position exception. |

`candidate_context_count = P + A + U`; the three sets are disjoint. Context counts are diagnostic counts, not unique position counts: repeated facts and dimension paths still require the roster's one-to-one correspondence checks. Separately record `extractor_recognized` for each context from the existing predicate. This is a compatibility flag, not a source-role decision: a confirmed NexPoint position can have `extractor_recognized = false`, and an unresolved context can have either flag value.

For eligible fund-quarters with zero output, apply the following mutually exclusive cases. Keep all three counts with the result; aggregate count `A` does not change the class.

| Source assessment | Confirmed positions `P` | Unresolved contexts `U` | Companyfacts investment total | Class | Treatment |
|---|---|---|---|---|---|
| Instance missing, unreadable or assessment incomplete | any | any | any | `source_unavailable` | No exception; unassessable exposure. Preserve any identified position omissions and the source failure reason; no download implied. |
| Complete | > 0 | any | any | `extraction_failure` | Confirmed position omissions count against A2 recall. If `U > 0`, retain that additional unassessed exposure; the failure class does not resolve it. |
| Complete | 0 | > 0 | any | `unresolved_context_pattern` | No exception; queued for source interpretation, parser or wrapper work; unassessable exposure. |
| Complete | 0 | 0 | positive, resolved | `eligible_no_position_facts` | In coverage denominator; listed with its total; excluded from roster accuracy. Aggregate-only facts are allowed. |
| Complete | 0 | 0 | nonpositive, absent or unresolved | `eligible_empty_candidate` | No automatic exclusion; needs source/lifecycle evidence before it can leave the denominator. |

The collector must not reuse the extractor's context predicate as its only test. That predicate in `pipeline/bdc_filings.py` sets `is_investment` only from a `typedMember` on an investment-identifier dimension or from the cash-equivalents rescue; explicit members on `dei:LegalEntityAxis` do not mark the context. `source_reconciliation.py` reuses the same predicate, so a zero from either path proves nothing about position facts.

**Collector acceptance cases (E0).** NexPoint Capital Q1-2023, accession 0001193125-23-145196, is the positive control: the cached instance has 807 `dei:LegalEntityAxis` references and no `InvestmentIdentifierAxis`; Auris Luxembourg III is an explicit member on that axis with FV $1,331,038. The full schedule has 39 position contexts with signed FV $48,731,529, equal to the disclosed investment total. The former 32-context statement misread the first table's candidate count in the retained packet; it was not a full-schedule position count. E0 must recover all 39 as `confirmed_position` despite `extractor_recognized = false`, keep aggregate contexts separate, and classify the zero-output fund-quarter as `extraction_failure`. This is defect class 16 in the [plan](05_plan.md); its cohort extent is E2. A supported aggregate-only case (`P=0, A>0, U=0`, positive total) must produce `eligible_no_position_facts`; an ambiguous-context case (`P=0, U>0`) must produce `unresolved_context_pattern`; a mixed case (`P>0, U>0`) must retain both the extraction failure and unresolved exposure. These controls are implemented in `tests/test_context_inventory.py`; current execution evidence and limitations are recorded in [the source-reconciliation investigation](../investigations/source_reconciliation.md).

The class is never inferred from the missing-output register alone; that register only records a positive companyfacts total. The population for classification is the 33 eligible zero-output fund-quarters in `programme_pilot_evidence_2026-09-09/obligations_v2.csv` (the earlier `obligations.csv` has 32 and predates the Fortress Q1-2025 resolution). Run experiment E1 before any fund-quarter carries the exception class.

**Reconciliation coverage caveat.** Because reconciliation shares the extractor's predicate, it can report nothing for unsupported position patterns and under-count source-only rows for partially affected filers. Report `reconciliation_coverage` (eligible fund-quarters with a reconciliation result for at least one confirmed position context over all eligible fund-quarters); extractor recognition alone is not a result. Report `unrecognized_context_share = (P_unrecognized + U_unrecognized) / (P + U)` per fund-quarter, using the separate compatibility flag and excluding aggregates from both sides. Report `U` and its assessable source FV separately even when the extractor recognizes those contexts. A zero `P + U` gives an unavailable ratio with the fund-quarter disposition, not perfect coverage. Neither a recognized pattern nor a small unrecognized share resolves `U`; uncovered portions remain unassessed. Experiment E2 sizes this across the cohort.

## 3. Formulas

**Roster (A2).** One-to-one correspondence between `R_q` and `H_q` within the comparable population. Row recall, row precision, FV recall, FV precision as usual; under- and over-inclusion reported separately; per-fund floors reported per fund-quarter. Duplicates in the candidate cannot raise recall.

**Field fidelity (B2).** Per field f and quarter q, every disclosed value in `E_fq` falls into exactly one category:

| Category | Definition | Counts toward |
|---|---|---|
| `correct` | Candidate value matches source at source precision, with the right unit, currency, kind and denominator | Accuracy numerator and denominator |
| `incorrect` | Candidate value present and does not match | Accuracy denominator |
| `missing_output` | Source discloses the value; candidate has null or no row | Accuracy denominator (an error) |
| `disclosed_unassessable` | Source discloses a value but its unit, currency, scale or period cannot be resolved from the instance, or printed and tagged values conflict | Assessability shortfall; never in the accuracy denominator |
| `not_disclosed` | Source does not disclose the field for this position | Disclosure coverage only |
| `not_applicable` | Field does not apply to the instrument | Excluded |

Accuracy = `correct / (correct + incorrect + missing_output)`, row-weighted and source-FV-weighted. Assessed coverage = `(correct + incorrect + missing_output) / (all disclosed)`, also both weightings. An accuracy figure is reported only when assessed coverage meets the field's assessability floor; below the floor the metric is `UNASSESSABLE` for that field and quarter, whatever the accuracy on the assessed subset. The floor is set by amendment after experiment E4 measures achievable coverage per field. Selecting an easy subset therefore cannot raise the score: the excluded values appear in the shortfall and block the pass. Comparison is at source precision; no absolute-dollar or relative tolerance is active. Wrong currency, rate kind or denominator is `incorrect` regardless of numeric proximity.

Collector implementation update, 2026-09-14: the eight numeric fields are complemented by `categorical_field_assessment.py`, which independently reads cached XBRL facts and explicit classification members for rate kind, maturity date/precision/status, instrument type and lien position. Unsupported source meanings remain `disclosed_unassessable`; missing candidate values remain errors where the source is assessable. Focused controls pass, but fresh full-candidate evaluation is still required. Versioned floor/denominator/roster policy loading is implemented and tested; no numerical floor or source-roster certification has been adopted.

**Reconciliation (B3).** Per anchor a: signed residual `d_a = P_a - T_a`, absolute and percentage. Cohort headline `sum(abs(d_a)) / sum(abs(T_a))` over one primary anchor per fund-quarter; never net signs. Zero anchors use the exact zero-balance rule; percentage is undefined.

**Public consistency (B4).** Exact: `sum(H_q.fair_value)` equals the unrounded headline, the instrument-bucket total and the sector-bucket total; contributor row sets are identical; each row is in exactly one bucket per partition.

**Continuity and identity (C2, C3).** Precision and recall from the existing source-question vocabulary; complete-chain rate over reference chains; unresolved kept as bounds. Scored from exposed regression sets, so reported as monitored (section 5).

**Enrichment (D3).** Sector coverage by row and absolute FV over `H_q`; accuracy from reviewed decisions where available, otherwise monitored.

## 4. The gate

The live gate already evaluates nine data-driven checks per quarter, fails closed on missing inputs, and sums on the published basis. Current v3 thresholds:

| Check | Metric | Bar |
|---|---|---|
| fund_coverage | funds with holdings | >= 60 (see amendment below) |
| reconcile_rate | conservation reconcile rate | >= 90% |
| flagged_fv_share | conservation flagged FV share | <= 10% |
| source_blocking_fv_share | source-only blocking FV share | <= 1% |
| verified_fv_share | verified-tier FV share | >= 70% |
| promoted_rule_drift | drift observations | <= 0 |
| promoted_rule_health | rule execution failures | <= 0 |
| over_inclusion_fv_share | over-inclusion FV share | <= 0.5% |
| unfinished_investigations | stale investigations | <= 0 |

Pre-gate: `NOT_ASSESSABLE` when fewer than 50% of funds have an anchor.

**Amendment required for `fund_coverage`.** The fixed floor of 60 was calibrated for a current quarter. The eligibility register shows 48, 53, 53 and 59 eligible funds in the four 2023 quarters, so the historical gate cannot pass as written. Replace the metric with `fund_coverage_share = funds with holdings / eligible funds in that quarter`, eligible counts from `programme_pilot_evidence_2026-09-09/obligations_v2.csv` or its successor, with a working bar of 95% and a per-quarter result. The denominator is adopted only after experiment E3 has audited the 98 lifecycle exclusions with the same context counter; until then the check reports against the unaudited register and is labelled provisional. This changes a live threshold and follows [decisions section 4](01_decisions.md): record the register version, evaluate old and new on the same candidate, keep the v3 result as history. Caveats: the 98 lifecycle exclusions are engineering assessments with quoted source passages, not owner-adjudicated; a wrongly excluded fund shrinks the denominator. Add `excluded_with_positive_facts = 0`: an excluded fund-quarter with `P > 0` or a positive companyfacts investment total fails the check. `U > 0` or an incomplete source assessment prevents certification of the exclusion and denominator; aggregate contexts alone do not prove positions or justify an exclusion.

**Complete gate table.** Every metric labelled Gate in section 6 appears here with its collector. A release is blocked by any failing or unassessable row. P4 is complete only when every row evaluates on a sealed candidate for all thirteen quarters.

| Check | Metric and formula | Bar | Collector | Criterion |
|---|---|---|---|---|
| fund_coverage_share | per section above | >= 0.95 | obligation register plus holdings | A1 |
| excluded_with_positive_facts | excluded fund-quarters with `P > 0` or positive total; unresolved/incomplete exclusions are unassessable | 0; exclusion audit must be assessable | instance context counter plus companyfacts | A1 |
| obligation_status_coverage | obligations with an evidenced class from section 2 | 100% | instance context counter | A1 |
| reconciliation_coverage | eligible fund-quarters with reconciliation results for confirmed position contexts over eligible | reported; floor by amendment after E2 | context counter plus reconciliation results | A2 |
| unrecognized_context_share | `(P_unrecognized + U_unrecognized) / (P + U)`; report `U` separately, per fund-quarter | reported; unsupported or unresolved portions remain unassessed | context counter and compatibility flags | A2 |
| roster_fv_recall, roster_fv_precision | section 3, tagged population | >= 0.99 | source reconciliation, class-aware | A2 |
| roster_row_recall, roster_row_precision | section 3 | >= 0.95 | source reconciliation | A2 |
| fund_roster_floor_breaches | eligible tagged funds below 0.95 FV or 0.90 row floor | 0 | source reconciliation per fund | A2 |
| amount_field_accuracy | section 3 categories; eight numeric fields today | >= 0.995 with assessability floor met | provenance replay plus source comparison | B2 |
| other_field_accuracy | section 3 categories | >= 0.99 with assessability floor met | cached categorical facts and explicit members; unsupported evidence remains unassessable | B2 |
| field_assessed_coverage | assessed over disclosed, per field | floor by amendment after E4 | same collectors | B2 |
| primary_absolute_error_ratio | non-netted sum of abs residuals over sum of abs anchors, one primary anchor per fund-quarter | <= 0.0025 | conservation engine, programme aggregation | B3 |
| fund_primary_error_ratio | per fund-quarter residual | <= 0.01 per fund | conservation engine | B3 |
| primary_fund_coverage | fund-quarters with an independent primary anchor over eligible | >= 0.95 | anchor loader; schedule totals excluded | B3 |
| primary_source_fv_coverage | source FV under an independent anchor over all source FV | >= 0.99 | same | B3 |
| public_partition_delta | headline minus each partition total; symmetric difference of contributor row IDs | 0 | export check | B4 |
| spread_unit_violations | overlay values outside declared unit range | 0 | overlay audit | B1 |
| schema_violations_post_write | structural violations on the written artifact | 0 | post-write validator | B1 |
| position_id_fill | cohort rows with a position ID | 100% | holdings scan | C4 |
| companion_parity | typed CSV/Parquet multiset differences, eleven artifacts | 0 | pair verifier | F2 |
| proposed_input_admission | proposed or unadmitted files loaded by any loader | 0 | loader audit | F5 |
| sector_fv_coverage, sector_row_coverage | assigned over `H_q` | >= 0.95, >= 0.90 | holdings scan | D3 |
| existing v3 rows | reconcile_rate, flagged_fv_share, source_blocking_fv_share, verified_fv_share, promoted_rule_drift, promoted_rule_health, over_inclusion_fv_share, unfinished_investigations | unchanged | live | B3, F1, F5 |

Delivery-gate rows (citation coverage, `evidence_path_or_unavailable`, `misleading_links`, `local_citation_p95_ms`) are evaluated on the exported bundle by P8 and block readiness, not data acceptance.

Delivery collector definition (2026-09-14): the history table displays fair value, cost and all-in coupon as numeric cells. Its reported-or-unknown population includes every finite displayed value; an absent locator never removes a value. Calculated values are counted separately: costs explicitly labelled `derived_proxy` or `first_observed_fv_proxy`, and cash-plus-PIK coupons with the recorded transform, cash source kind and finite inputs that reproduce the displayed result. They are excluded from reported-value highlighting; missing or inconsistent derivation evidence does not earn an exclusion. Numeric row coverage is the share of rows with at least one such numeric cell for which every such cell has a valid direct highlight. Amount FV coverage is the absolute-FV-weighted share of rows with populated reported-or-unknown fair value or cost for which every such amount cell has a valid direct highlight. Negative amounts use absolute FV weights; zero-FV rows still count in the row metric; an empty or unknown weighted denominator is unassessable. Report per-field detail for all eight downloadable numeric fields as well as these displayed-field metrics, and report each quarter separately. Coverage remains provisional until the complete browser anchor census passes; it is not a source-accuracy claim.

Per-quarter results are required for every quarter in the history; an overall figure never hides a failing quarter. `scripts/reattest_quarters.py` re-checks signed-off quarters after any pipeline change; a regression is stop-and-report.

The programme contract JSON and `pipeline/programme/measurement.py` are retired as a gate. Their catalog IDs are retained only as names in this document.

## 5. Monitored metrics

These keep working targets but cannot block a release, because the owner has ruled out a human-labelled reference set and automation can only measure agreement.

| Metric | Working target | How it is scored | Published as |
|---|---|---|---|
| entity_precision, entity_recall | 99.5%, 95% | Exposed mg3 entity packets (175): false merges, false splits, consistent | Regression counts and rates against the exposed set |
| position_precision, position_recall | 99.5%, 95% | Exposed mg3 chain packets (360) plus continuation scorer | Regression counts; missed and wrong links |
| complete_chain_rate | 95% | Chain audit over required history; singletons separate | Rate with unresolved bounds |
| sector_accuracy | 95% | Consistency across quarters and across funds holding the same entity; reviewed decisions where they exist | Agreement rate, never labelled accuracy |

Last exposed regression result (September 9 closeout): 22 labelled distinct positions sharing an ID, 19 labelled continuations with different IDs, 13 entity false merges, 2 false splits. These are development counts, not population estimates.

## 6. Working numerical targets

From `pipeline/programme/contracts/working-v1.json`, endorsed 2026-09-10 as amendable. Status column added 2026-09-12.

**How this table applies to the current refactor (2026-09-14).** Gate and Delivery gate labels below describe production readiness. For refactor completion, implement and test the corresponding measurements and report the actual candidate verdicts. Population-level shortfalls go to later remediation/enrichment; reaching every population-level target is not a refactor completion condition. The exact implementation invariants (including artifact/public-total equality, complete retained-history access, correct evidence handling, no misleading links and repeatable identity) and the declared citation performance requirement still must pass in this run. A missing collector or supported evidence lost by faulty wiring is an implementation defect. Genuine source/approval gaps or pending adoption remain explicit operational residuals. The per-package architectural completion criteria and later operational targets are separated in [plan section 2](05_plan.md).

| Metric | Op | Value | Status |
|---|---|---|---|
| roster_fv_recall, roster_fv_precision | min | 0.99 | Gate (tagged population) |
| roster_row_recall, roster_row_precision | min | 0.95 | Gate (tagged population) |
| fund_roster_fv_floor, fund_roster_row_floor | min | 0.95, 0.90 | Gate per fund |
| amount_field_accuracy, other_field_accuracy | min | 0.995, 0.99 | Gate, source precision |
| primary_absolute_error_ratio | max | 0.0025 | Gate |
| fund_primary_error_ratio | max | 0.01 | Gate per fund |
| primary_fund_coverage, primary_source_fv_coverage | min | 0.95, 0.99 | Gate |
| entity_precision, entity_recall | min | 0.995, 0.95 | Monitored |
| position_precision, position_recall | min | 0.995, 0.95 | Monitored |
| complete_chain_rate | min | 0.95 | Monitored |
| sector_accuracy | min | 0.95 | Monitored |
| sector_fv_coverage, sector_row_coverage | min | 0.95, 0.90 | Gate |
| reported_amount_highlight_fv_coverage | min | 0.99 | Delivery gate |
| reported_numeric_highlight_row_coverage | min | 0.95 | Delivery gate |
| evidence_path_or_unavailable | min | 1.0 | Exact |
| misleading_links | max | 0 | Exact |
| local_citation_p95_ms | max | 5000 | Delivery gate |

Amendments follow [decisions section 4](01_decisions.md).

## 7. Criteria map

Implementation status updated 2026-09-14. Implemented does not mean accepted: the fresh candidate's remaining integration stages, independent evaluations and final verification must supply the completion evidence.

| ID | Outcome | Decisive check | Status |
|---|---|---|---|
| A1 | Every obligation has an evidenced status | obligation_status_coverage, fund_coverage_share, excluded_with_positive_facts | Collectors implemented; prior E1/E3 measured; fresh all-quarter evaluation and later denominator adoption remain |
| A2 | Roster completeness and purity | roster metrics over tagged population; reconciliation_coverage; exception class source-backed | Context inventory and scoped scoring implemented; fresh candidate E2 evaluation remains |
| A3 | Source selection is reproducible | selection audit over all history | Fixtures exist |
| A4 | Supplemental quarters dispositioned | status record | Deferred by decision |
| A5 | Accounting scope violations | membership audit | Scope retention and per-anchor membership implemented; focused controls pass; full source evaluation remains |
| B1 | Field contract coverage | schema_violations_post_write, spread_unit_violations | Post-mutation validation and spread-unit audit implemented; fresh quarterly evaluation remains |
| B2 | Field fidelity | accuracy with assessability floor and category counts | Eight numeric and six categorical collectors implemented; fresh E4 evaluation and later floor adoption remain |
| B3 | Fund reconciliation | conservation on the published basis | Live |
| B4 | Public consistency | public_partition_delta | Shared signed holdings aggregation implemented; full export/history readback passes; independent public partition/build audit remains |
| B5 | Rate and PIK semantics | contract cases | Atomic all-in migration implemented; full candidate returns sealed; financial-delta review remains |
| C1 | Stable entity IDs | rebuild comparison | Registry implemented; full identity stage sealed; identical-input cold twin remains |
| C2 | Entity link quality | monitored | |
| C3 | Continuation and chains | monitored | |
| C4 | Position lifecycle | position_id_fill plus lifecycle audit | Assignment and aliases implemented; full identity stage sealed; quarterly evaluation and migration review remain |
| D1 | Evidence contract coverage | evidence graph audit | V8 full census has zero metadata errors and evidence-path-or-unavailable 1.0; source-supported numeric citation repairs require replacement integration |
| D2 | Enrichment replay | pinned decision replay | Versioned ingestion, provenance and replay implemented; legacy cache evidence gaps remain explicit |
| D3 | Sector coverage and accuracy | coverage gate; accuracy monitored | Collectors implemented; prior coverage below floor; fresh measurement remains, new classification campaign deferred |
| D4 | Citation scenarios | browser scenarios on the staged bundle | V8 seven actual-data scenarios and labelled synthetic controls passed; inferred-sector evidence was absent from actual data; replacement run remains |
| D5 | Citation coverage | highlight coverage metrics | Collector controls and full v8 census complete; 489,012 field links across 776 documents have zero misleading targets. Coverage gaps exposed zero-transform and numeric-cast defects; repairs require replacement measurement |
| E1 | Complete holdings access | accessible rows equal `H_q` | V8 full 261,772-row, 100-column history readback has zero differences; browser access passed. Replacement integration remains after producer repairs |
| E2 | Analytic display basis | display audit | Signed aggregation and reported/inferred distinctions implemented; actual public build audit remains |
| E3 | Scope and performance | route audit and p95 | V8 static build and 70-fund scope audit passed; local citation p95 3,593.57 ms. Replacement build and browser measurement remain |
| F1 | Writer authority | ordered plan and one finalizer | Ordered replay and finalizer implemented; all five full integration stages sealed; independent evaluations remain |
| F2 | Semantic repeat and companion parity | companion_parity, twin build | Full holdings/identity pairs have zero differences; all eleven-artifact evaluation and cold twin remain |
| F3 | Release failure scenarios | fault drills | Recovery/fault controls implemented; fresh candidate drill remains |
| F4 | Resume scenarios | drills | Completed-stage reuse and restore controls implemented; fresh candidate drill remains |
| F5 | Acceptance control | proposed_input_admission, tamper tests | Evidence-bound promotion/admission controls pass focused tests; legacy inputs remain unverified; fresh gate evaluation remains |
| F6 | Migration deltas and re-attestation | semantic diff, reattest | Actual semantic backstop shows no new material drift; fresh candidate deltas and all-quarter re-attestation remain |

## 8. Baseline at consolidation (Q1-2026 unless stated)

| Measure | Value | Source |
|---|---|---|
| Cohort rows and signed FV | 30,067 rows; $381,537,030,207 | canonical CSV, 2026-09-08 |
| Published `portfolioFv` | $382,151,960,774 | stale JSON of 2026-09-08 07:38 |
| Recomputed headline with `fair_value > 0` | $381,781,927,926 | export recipe; gap to canonical is negative and zero rows |
| Sector donut source | $264.8B overlay, $117.3B holdings fallback | `sourceBreakdown` |
| Live gate v3 | FAIL 4/9: reconcile 80.9%, flagged 25.7%, verified 60.3%, drift 15, over-inclusion 0.883% | `quarter_acceptance.json` 2026-09-08 |
| Sector coverage | 73% of absolute FV; $99B of the gap on direct-credit rows with entity IDs | probe 2026-09-12 |
| Position IDs | 0 of 780,425 rows populated | Parquet, 2026-09-12 |
| Matches CSV vs Parquet | 497,456 vs 536,455 rows | mtimes 2026-09-08 |
| Spread overlay | 21 positions at 1/100 of disclosed spread | `identifier_spread_corrections.json` |
| Proposed bridge live | 41 records, CIK 0001838126 | bridge directory |
| Provenance replay | 30,026 of 30,067 rows, 99.75% of FV | active ledger |
| Eligible fund-quarters with zero output | 33 in `obligations_v2.csv` (23 with a positive companyfacts total, about $13.3B); class not yet established (E1) | pilot evidence |
| Known extraction failure among them | NexPoint Q1-2023: 32 fact-bearing contexts on `dei:LegalEntityAxis` explicit members, zero output, zero reconciliation rows | cached instance 0001193125-23-145196; closeout packet REF-0001588272-2023-03-31 |
| Eligible funds per 2023 quarter | 48, 53, 53, 59 against a live floor of 60 | eligibility register |
| Exposed mg3 regression | 22 false position merges, 19 missed continuations, 13 entity false merges, 2 false splits | closeout |
