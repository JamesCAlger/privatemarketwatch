# Programme reference evidence and historical eligibility

Date: 2026-09-09. Status: bounded preparation assessment complete; independent
acceptance labeling, executable baseline and final numerical gate remain open.
Scope: the accepted 70-CIK cohort, Q1-2023 through Q1-2026. D01-D13 unchanged.

Current governance, 10 September: the owner requires automated source verification without a mandatory human-labelled gold set. The [automated reference protocol](programme_spec_status.md#automated-reference-verification-no-human-label-prerequisite) supersedes any human-review prerequisite inferred from the historical assessment below. Independent review means a separate evidence-verification process, not necessarily a person. Existing labels, evidence statuses and dated measurements are preserved; none is automatically promoted.

## 1. Result

The 131 previously unexplained missing-output fund-quarters now separate into
**98 before investment activity, 32 eligible gaps and one unresolved quarter**.
Of the 32 eligible gaps, **23 have positive investment values in cached source
facts**. The other nine require a source roster or an evidenced empty/cash-only
status. They have not been excused as missing filings or later BDC elections.

Across all 910 obligations, 811 are assessed as eligible and 779 have saved
holdings: **96.05% fund-quarter presence on the assessed eligible population**.
This measures whether any rows exist, not their completeness or accuracy. The
unresolved quarter remains visible outside that conditional denominator; it
cannot silently disappear from the final gate. No holdings were removed.

The [evidence bundle](programme_reference_evidence_2026-09-09/README.md) contains
the 910-row register, 32 reviewed lifecycle records, 39 exact source passages,
source-document candidates, a 61-cluster calibration pilot, existing benchmark
inventories and concrete source examples. It pins 2,083 inputs and rechecks the
canonical holdings hash from the earlier assessment.

## 2. Historical eligibility and its limits

The assessment used cached companyfacts, original HTML/iXBRL and XBRL text blocks,
the filing index and existing cohort metadata. Companyfacts supplied positive
investment evidence for 791 fund-quarters; source-reviewed operating intervals
support another 20. A positive investment fact supports eligibility, but its
concept may represent a component rather than the fund's total portfolio. These
facts are **not automatically primary reconciliation anchors**.

Latest documents were inspected for lifecycle statements; 16 early filings were
also inspected for ambiguous starts and predecessor history. Five latest HTML
files exceeded the bounded reader's size cap, so cached XBRL text blocks were
used instead; these were not missing documents. StepStone's fallback used its
2023-Q2 document. Every quoted passage records the actual document and hash.

| Quarter | Assessed eligible | Before investment activity | Unresolved | Eligible with saved holdings | Eligible with no holdings |
|---|---:|---:|---:|---:|---:|
| Q1-2023 | 48 | 22 | 0 | 39 | 9 |
| Q2-2023 | 53 | 17 | 0 | 45 | 8 |
| Q3-2023 | 53 | 17 | 0 | 52 | 1 |
| Q4-2023 | 59 | 11 | 0 | 56 | 3 |
| Q1-2024 | 61 | 9 | 0 | 59 | 2 |
| Q2-2024 | 63 | 7 | 0 | 62 | 1 |
| Q3-2024 | 64 | 6 | 0 | 63 | 1 |
| Q4-2024 | 66 | 4 | 0 | 65 | 1 |
| Q1-2025 | 67 | 2 | 1 | 66 | 1 |
| Q2-2025 | 69 | 1 | 0 | 68 | 1 |
| Q3-2025 | 69 | 1 | 0 | 68 | 1 |
| Q4-2025 | 69 | 1 | 0 | 67 | 2 |
| Q1-2026 | 70 | 0 | 0 | 69 | 1 |
| **Total** | **811** | **98** | **1** | **779** | **32** |

These are source-backed engineering assessments, not owner-adjudicated labels
or a complete legal filing-obligation audit. No inference that every eligible
fund had the same quarterly reporting obligation is made. Operating history,
source availability, structured tagging, portfolio existence and output presence
are separate attributes. The 98 lifecycle exclusions require independent review
before becoming a release denominator; source evidence of earlier holdings
overrides a generic later commencement statement. Pre-operation cash and other
relevant disclosures remain subject to A5 retention and their own accounting
population; this assessment does not authorize dropping them.

Specific findings that matter:

- **Bain Capital Private Credit:** its later filing says operations commenced
  in November 2023, but its June 2023 schedule contains two Legacy Corporate
  Lending investments totaling $646,250, acquired in April. Q2 and Q3 remain
  eligible. This is a concrete counterexample to using the latest commencement
  date or first positive companyfacts concept as an automatic cutoff.
- **Fidelity:** the June 2023 filing explicitly preserves LP-to-LLC continuity
  and reports $737.7m of investments at December 2022. Its June 2023 BDC election
  cannot excuse the missing Q1-2023 history. A portfolio acquisition from another
  vehicle does not by itself establish this same continuity.
- **Lord Abbett:** source operations began in February 2024; the saved holdings
  contain none of its nine eligible quarters. Eight have positive source
  investment facts. At March 2026, its balance sheet and schedule report
  $1.413006bn of investments, including a $64.209m JV interest. The source total
  and schedule passages are pinned; a complete independent roster/accounting
  bridge is still required. Do not sum its repeated quarterly values as one
  missing portfolio amount.
- **Fortress, Q1-2025:** the June filing states no investment operations at
  December 2024 and reports investments at June 2025. It does not establish
  whether March was already investment-operating. No primary March document
  was identified in this bounded inventory. The quarter stays unresolved.
- **Quarter-boundary starts:** Golub's June 30, 2023 commencement makes Q2
  eligible for examination; it does not prove that a nonempty loan roster should
  exist on that date. Overland, Vista and the two Jefferies vehicles have bounded
  start intervals supported by early filings; no exact dates were invented.

The [missing-output register](programme_reference_evidence_2026-09-09/missing_output_obligations.csv)
retains all 131 original gaps and their dispositions. The nine eligible gaps
without a positive companyfacts investment amount are Silver Point Q1-2023,
SCP Q2-2023, Fidelity Q1-2023, T. Rowe Price OHA Q1-2023, Diameter Q4-2023,
Golub Q2-2023, Crescent Q2-2023, MidCap Apollo Q1-2024 and Lord Abbett Q1-2024.

## 3. Existing benchmarks: reuse rather than restart

| Existing asset | Measured contents | Programme use and limitation |
|---|---|---|
| `data/gold/labels/position_labels.jsonl` | 132 append records; 128 latest unique labels across 10 funds, all stored as `human_confirmed`; 127 in programme scope | Source-field regression/review starting point. All are `tail_census`, not a representative accuracy sample. All source files exist; none has `source_ref.context_id`, so precise locators need validation. Stored human status was inventoried, not independently re-certified. |
| `data/gold/samples/sample_frame_batch1.jsonl` | 562 units: 336 positions, 25 fund-quarters and 201 flags | Preserve original sampling design and labels. Old cohort/period scope differs; do not apply its probabilities unchanged to the new 70-CIK frame. Fund/flag label files were not found beside the position label file. |
| Match gold `mg3` | 535 completed packets: 360 chain and **175 entity**; 796 edge records | Includes within-fund name clusters, entity merges and cross-fund near misses. Existing entity-resolution evidence is substantial. Used in matcher experiments; not fresh held-out evidence for changes informed by it. |
| `mg4_contested` | 265 completed chain packets; 1,138 edge records | Used for the contested-matcher promotion gate. Reuse for regression and semantic compatibility checks; document exposure. |
| `mg5_recall` | 100 completed singleton packets | Previously an out-of-sample recall check. Now inspected/diagnostic; future held-out status cannot be assumed. Source counterparts absent from candidate packets must stay visible, not become false negatives for the source. |
| `mg1` | 577 worklist entries; only three complete canary packets and one edge record | Do not count the full worklist as labeled gold. |
| Older shadow flag gold | 45 rows, 24 labeled, across 29 funds | Flag-selected judgments, not source-roster coverage. |
| GICS quality gate, review queues and caches | Existing validation/enrichment apparatus located | Vocabulary/coherence and production decisions do not establish sector correctness. No independent reviewed sector benchmark was identified in this bounded inventory. |

Including evidence attached to proposed links, mg3/mg4/mg5 have evidence entries
in 518/535, 256/265 and 96/100 packets respectively. Presence is not citation
correctness; absence can accompany a valid insufficient-evidence verdict. Their
audit slices contain 52/29/14 rows with no recorded `owner_verdict`. This does not
prove no owner review happened elsewhere; it means these files cannot establish
that review. Existing data and statuses were not edited or rescored.

The [benchmark inventory](programme_reference_evidence_2026-09-09/benchmark_inventory.json)
and per-reference indices preserve the counts and paths. Promotion/exposure
history is documented in the September 6-8 entries of
[the changelog](../agent_changelog.md) and the
[agent campaign investigations](../investigations/agent_campaigns.md).

## 4. Frozen calibration frame and concrete examples

The [61-cluster pilot](programme_reference_evidence_2026-09-09/reference_pilot.csv)
contains:

- Two eligible fund-quarter clusters per required quarter, selected by a fixed
  hash seed from the source/lifecycle frame: 26 clusters. Selection did not filter
  on output presence, flags, apparent reconciliation success or easy parsing.
- All 32 eligible missing-output quarters; one overlaps the probability pilot.
- The unresolved Fortress quarter and three Bain lifecycle counterexamples.

For the probability component, the per-quarter selection probability is `2/N_q`;
the CSV's `selection_probability` belongs to the named component, not a pooled
61-cluster estimator. The targeted gap census and counterexamples are reported
separately. No failed/unavailable source is replaced with an easier sample.
Two clusters per quarter are a calibration pilot, not enough to certify the
proposed 99%+ accuracy thresholds or all 70 funds.

The full 910-row document frame identifies 810 HTML and 811 XML candidate slots,
including some pre-operation filings. Seven eligible gaps and the unresolved
quarter have no document candidate in this bounded primary-period/companyfacts
accession search. That is not proof the entire cache lacks useful comparative or
registration evidence. Candidate period, amendments, document scope and source
roster still need verification. The pilot pins 103 distinct source files.

Four [development case definitions](programme_reference_evidence_2026-09-09/development_expectations.json)
are grounded in raw HTML rows, inline facts, context/unit definitions, adjacent
schedule headings and document hashes:

| Example | Concrete check |
|---|---|
| Bain June 2023, complete two-position schedule | Two distinct instruments for one company; reported FV/cost $71,250 and $575,000. Subtotals and the separate affiliation roll-forward do not add lots. This one small schedule was reviewed in full. |
| Bain reported fields and citations | Cost equal to FV is still reported cost; empty equity rate fields are not numeric zero. This SOI is in dollars despite later MD&A tables using thousands. A repeated amount in another table is not an interchangeable citation. |
| Esdec loan, Q3-2023 to Q1-2024 | Three source observations support a development continuation case; 600bp spread is 6pp, floor 0.5%, maturity August 30, 2028. EUR principal coexists with USD cost/FV. The Q3 printed principal currency is EUR while its inline unit resolves to USD; preserve that conflict and require an evidenced resolution. Q4/Q1 agree on EUR. |
| Esdec comparative in the Q1-2024 filing | Current FV is $50.759m; the legitimate December comparative is $52.250m in another table. Keep report dates distinct and highlight the correct row/field. Parser-specific table ordinals are not portable raw DOM locators. |

These are source-grounded **development examples**, selected with knowledge of
existing investigations/gold. They are not a fresh blinded benchmark or a browser
test. The source row bundle includes 12 relevant rows across four documents, with
roll-forward/commitment/comparative rows explicitly distinguishable. No numeric
pipeline accuracy rate is inferred from them. Reported-zero cost, donor identity,
partial maturity, PIK, independent sector truth and broader accounting examples
remain explicit fixture gaps.

## 5. Independent reference protocol and next executable task

**Subsequent execution:** the [isolated pilot](programme_measurement_pilot_2026-09-09.md)
has now run. It resolves Fortress to eligible (812 eligible / 98 pre-investment),
compares two complete development rosters, measures tag-copy fidelity and reviews
existing-label conflicts. Its numerical proposal and remaining reference work
supersede the next-task instruction below. This document and its evidence retain
the original preparation snapshot; no frozen eligibility/sample files were edited.

Reuse the source-grounding and exposure controls in the existing
[gold labeler protocol](../../data/gold/labeler_protocol.md), with the automated
admission process specified in the current governance above. A human label or
signature is not required. Freeze a source-only packet before exposing candidate
values or flags. Give the independent reference process original schedules,
footnotes, units, periods, source identifiers and required questions. Keep output
comparison separate. Record automatic verification and agent adjudication with
their actual evidence basis; never label them `human_confirmed`.

The frozen unit must support all of the following, rather than only asking
whether an output row's FV looks right:

1. **Roster and fund anchor:** enumerate complete source lots and classify
   totals/presentation repeats; retain cash, parent interests and underlying
   schedules with explicit relationships. Independently select the fund total
   and establish its consolidation/currency basis. Missing source and ambiguous
   membership remain assessability failures, not empty correct portfolios.
2. **Field expectations:** record raw meaning, unit/scale, precision, source
   disclosure/applicability and permissible normalization. Preserve contradictory
   printed/tag evidence and unresolved values. Field coverage denominators cannot
   depend on candidate fill.
3. **Identity:** reuse mg3 entity/chain evidence after checking new semantics and
   source locators. Add source-selected continuations, genuine different-tranche
   pairs and nonmatches, including missing candidate counterparts. Hold out whole
   borrower/chain/filer-time clusters as appropriate, not random adjacent edges
   that leak the same instrument into training and evaluation.
4. **GICS:** label independent company business evidence against a pinned sector
   taxonomy, recording evidence date, ambiguous sectors and reviewer decision.
   Sample distinct enrichment decisions plus row/absolute-FV exposure, including
   unclassified and apparently plausible assignments. Production LLM/cache labels
   are comparison values, not truth. Historical availability and later knowledge
   must be explicit under latest-best history.
5. **Adjudication and exposure:** record preparer, reviewer, source/version,
   expected value, rationale, confidence, unresolved reason and disagreements.
   The current pilot is calibration/development. Acceptance hold-out membership,
   access restrictions and label authority must be frozen separately; a new
   filename in this shared writable repo does not create independence.

**Next bounded task: implement and run the isolated reference-measurement pilot.**
Start by resolving Fortress's quarter and searching existing cached comparative
evidence for the seven eligible slots without candidates. Complete independently
reviewable source-only rosters/anchors for the pilot and the missing field/sector
examples; preserve blocked items. Adapt existing evaluators in separate tested
packets to write isolated A1/A2/B2/B3/C/D results against a pinned candidate.
Validate the evaluator first using the development cases and counterexamples.

Deliver per-quarter denominators, row/FV residuals, source assessability,
uncertainty and a numerical threshold proposal. Link any measurement to the
actual release/input identities; saved holdings/matching/PIK are not yet a
certified synchronized candidate. This task does not authorize a production
rebuild, fleet, dbt migration, benchmark rewrite or threshold relaxation. Final
D12 gate approval follows the measured proposal; there is no new policy choice
for the owner to settle before that evidence is prepared.

## 6. Verification and boundaries

Bounded cache-only collectors completed. Checked all 910 unique obligations,
quarter sums, sample denominators, 39 exact normalized source passages, source
row locator references and 2,083 pinned input stats. Rehashed the canonical
holdings file against the previous assessment; no change. Source/gold files and
the dirty worktree were preserved. Collector syntax and document links checked.

No pytest, application build, benchmark scorer, production evaluator, rebuild,
frontend export, semantic output diff, reattestation, baseline refresh, downloads,
model enrichment or agent dispatch was run. This documentation/reference task
does not change pipeline behavior, data semantics, published data or live gates.
