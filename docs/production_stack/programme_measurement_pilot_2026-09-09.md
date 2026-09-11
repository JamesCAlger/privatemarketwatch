# Programme measurement pilot and numerical gate proposal

Subsequent update: the [overnight closeout](programme_spec_closeout_2026-09-09.md) supplies a byte-identical isolated rebuild, two additional development rosters, all 61 packet dispositions, label proposals, synchronized identity/PIK results and actual browser checks. This document preserves the earlier pilot's evidence and limits; use the closeout for current preparation status.

Date: 2026-09-09. Status: first isolated pilot executed; numerical proposal for
review, not approved thresholds. **The programme is not yet assessable against a
complete acceptance benchmark.** Production data, gold labels and live gates were
preserved.

The pilot establishes three useful results: all historical eligibility questions
now have an assessed disposition; two complete development rosters demonstrate
both correct and missing holdings; source checks expose defects in reference
labels as well as candidate data. It does **not** establish population accuracy
from a convenient subset of the filings.

References: [measurement register](programme_measurement_register.md),
[source/reference preparation](programme_reference_and_eligibility.md),
[evidence and reproduction](programme_pilot_evidence_2026-09-09/README.md).

## 1. Candidate, scope and method

The candidate is the saved `private_markets_holdings.csv`, SHA-256
`f175956d07649ed77dd3ec11c0ffd92f1af8074824d15ab881bc8495f4e81b68`.
It has 780,425 total rows and 261,613 observations in the required 70-BDC,
Q1-2023 through Q1-2026 population. This is not a newly rebuilt release. Saved
matching/PIK artifacts are not certified as belonging to that holdings generation.
HEAD, dirty worktree, source and evaluator identities are recorded in the bundle.

All 61 previously selected calibration clusters remain in the pilot: 26
quarter-stratified probability selections, the original missing-output census
with its overlap, three Bain lifecycle cases and Fortress's unresolved quarter.
The selection probabilities and original reasons are retained. Resolving Fortress
does not turn it into a random draw or silently revise that original design.

A separate [source reader](../../scripts/programme_reference/source_reader.py)
reads original inline facts, literal unit definitions, contexts, table rows and
locators. It does not import production extraction, classification, correction or
reconciliation rules. The existing reconciliation engine shares extraction
helpers with production; its output was therefore not relabeled independent
truth. The new reader is a **review aid**, not a second production extractor.

The source pass precedes the comparison pass. It produces 15,128 raw FV-bearing
row/context candidates from 53 source-document packets. These include subtotals,
repeated presentations and subsidiary schedules, and can omit untagged positions.
They are not 15,128 independently verified positions. The remaining eight clusters
have no primary HTML candidate in the bounded frame. A further search read 77
cached XML files across those eight filers; related comparative facts do not
establish complete historical schedules.

Comparisons use DuckDB and isolated scratch outputs. There were no SEC requests,
production rebuilds, exports, enrichment calls, gold promotions or fleet runs.

## 2. Historical obligations: 812 eligible, 98 pre-investment

Fortress CIK 2012139 is now assessed eligible at March 2025. Its June filing says
it already had an investment at March 31. Its March 2026 filing includes a March
2025 Level 3 roll-forward with a $1.092m reported ending total. That is sufficient
positive investment evidence; it is not a complete primary portfolio roster.
Management's phrase "single investment" must not become a one-position count:
the roll-forward distinguishes debt and preferred equity.

The [versioned obligation frame](programme_pilot_evidence_2026-09-09/obligations_v2.csv)
has 812 eligible slots, 98 pre-investment slots and no unresolved eligibility
slots. The original assessment is preserved. Lifecycle dispositions still need
independent review before becoming the final acceptance denominator.

| Quarter | Eligible | With saved rows | Without saved rows |
|---|---:|---:|---:|
| 2023 Q1 | 48 | 39 | 9 |
| 2023 Q2 | 53 | 45 | 8 |
| 2023 Q3 | 53 | 52 | 1 |
| 2023 Q4 | 59 | 56 | 3 |
| 2024 Q1 | 61 | 59 | 2 |
| 2024 Q2 | 63 | 62 | 1 |
| 2024 Q3 | 64 | 63 | 1 |
| 2024 Q4 | 66 | 65 | 1 |
| 2025 Q1 | 68 | 66 | 2 |
| 2025 Q2 | 69 | 68 | 1 |
| 2025 Q3 | 69 | 68 | 1 |
| 2025 Q4 | 69 | 67 | 2 |
| 2026 Q1 | 70 | 69 | 1 |
| **Total** | **812** | **779** | **33** |

779/812 = **95.94% presence**, not completeness or financial accuracy. Some
unrepresented quarters still need an evidenced empty/cash-only disposition; 33
is not automatically a count of erroneous missing portfolios. Missing source is
not permission to exclude an eligible quarter. Relevant pre-investment cash and
other disclosures remain under A5.

## 3. What the comparisons establish

### A2 and B3: two complete development rosters

| Source schedule | Reviewed roster and source total | Saved candidate | Result |
|---|---|---|---|
| Bain, June 2023 | Two separate Legacy equity instruments; $646,250 | Two correctly matched rows; $646,250 | Row and FV precision/recall 100%; primary-total residual $0, on this small schedule only |
| Lord Abbett, September 2024 | 33 loans/facilities; primary reported FV $313.562m | No holdings rows | All 33 source lots missing; row recall 0%; primary-total shortfall $313.562m, or 100% |

Lord Abbett's source review enumerates every physical row of the two-page
schedule. It retains separate term loans, delayed draws and revolvers, including
negative-FV facilities. Six instruments have an untagged FV dash. Their presence
is established; a numeric zero is not fabricated. Consequently the roster's
complete FV-weighted metrics remain unassessable, while its row recall and
independently printed primary-total shortfall are measurable. The 27 known
amounts sum to $313.562m signed and $314.430m absolute. Their agreement with the
total does not erase the six additional facilities.

The two primary anchors have explicit development accounting bases. Their
results are reported individually, not pooled across quarters into a cohort
error rate. The automatic inventory of 195 anchor candidates includes
percentages, components, cash variants and repeated totals; they have no blanket
basis certification. For example, Apollo Debt Solutions' June 2025 source
distinguishes before/after cash-equivalent totals. Picking whichever total is
closest to the candidate would invalidate the measurement.

Both rosters are agent-reviewed development evidence. Lord Abbett's missing
candidate was already known when its roster was reviewed. Neither is a fresh
held-out acceptance sample. The remaining 59 pilot clusters have no complete
adjudicated roster in this run, including the pre-investment and missing-source
cases; their status is retained in `pilot_status.csv`.

### B2: copying a tag is different from financial correctness

The probe matches source fields to candidate rows by CIK, report date, accession
and source context. Repeated agreeing source facts can support one field probe;
conflicting source facts and non-unique candidate matches cannot receive a pass.
Reported all-in/cash-ambiguous rate concepts are excluded from this probe; the
cash-rate concept is compared to the current pipeline's cash-leg storage.
Amounts use resolved source units and declared precision. This is not an
implementation of the target all-in rate contract.

| Field-probe disposition | Count |
|---|---:|
| Agrees within source precision | 26,345 |
| Numeric discrepancy | 30 |
| Candidate field missing | 49 |
| Candidate currency not resolved by this probe | 71 |
| Conflicting source values | 16 |
| Reference value unassessable | 1,234 |
| No exact candidate context | 19,485 |
| **Total field groups** | **47,230** |

These counts are **not** an accuracy percentage. Unmatched contexts include
totals, repeated/supplemental tables, intentionally unrepresented facts, absent
holdings and different accessions. The probe also conditions on FV-bearing
tagged source rows, so it cannot measure complete disclosure coverage. Currency
metadata gaps are distinct from the accepted, explicitly attributed USD default.
The probe does not turn missing currency metadata into a reported-currency claim.

The 30 numeric discrepancies comprise 12 share counts, two NAV percentages and
16 PIK-rate facts. Raw rows, values and locators are saved for review. A concrete
counterexample is Paragon in CIK 1918712, December 2023: the printed PIK is 3.38%,
and the candidate stores 3.38pp. The inline fact instead has `scale=0`, which
under fractional-rate interpretation produces 338pp. The candidate agrees with
the displayed percentage. Blindly fixing it to the tag would introduce an error.
The other cases need their own meaning/unit/donor review; no blanket correction
was applied.

The Esdec development comparison finds the three expected observations, FV/cost,
6pp spread and exact maturity. September 2023 still has printed-EUR/tagged-USD
principal evidence, which the output has copied as `U_USD`. Following periods
carry `U_EUR`; FV/cost remain USD. Stable entity ID across these three rows is a
useful example, not an entity-accuracy result. Their position IDs are blank.

### Existing gold: reusable, but not self-validating

The isolated comparison reuses the existing scorer's **historical 1% numeric
tolerance** only as a named regression diagnostic. It does not adopt that
tolerance as the programme's B2 contract or write to the gold directories.

Of 127 in-scope stored labels, 122 join uniquely to the current candidate, four
do not join and one joins twice. The ambiguous join is not arbitrarily selected.
Within unique, applicable labels, the old scorer flags two of 121 FV comparisons,
one of 121 cost comparisons and 13 of 119 classifications; it flags none of 73
lien comparisons. These selected tail cases are not a population sample.

Re-reading both apparent FV failures found reference problems:

- **Aurelia, CIK 1925309:** the source shows FV $385.453m and an accompanying
  EUR328.199m amount. The output has the USD value; the stored label uses the euro
  number. The same source also provides a month-only maturity example, `5/2031`,
  for the target month-end/precision contract.
- **Sentinel, CIK 1838126:** the parent's December 2025 schedule shows the term
  loan at FV $254.664m and cost $255.050m, matching the compared output. The stored
  -$188k/-$190k values belong to a delayed-draw facility in **ULTRA III's separate
  JV schedule**. Both use a `Sentinel Buyer Corp. 2` identifier and the same date;
  accounting scope, dimension path and instrument are essential to the label key.

These are proposed reference dispositions, not edits to confirmed labels. The
classification flags and unjoined cases have not all been adjudicated. Neither
the original flagged rate nor an adjusted rate excluding these examples is
presented as programme accuracy.

### Identity, enrichment and citations

C1-C4 remain blocked for a release-level score because the saved identity outputs
are not synchronized with the pinned holdings and persistent position IDs are
absent. Existing mg3 entity/chain, mg4 and mg5 evidence remains the regression
starting point; no benchmark or production identity output was changed.

D3 remains unmeasured against independent sector truth. The previously measured
Q1-2026 GICS fill (about 72.98% of absolute FV) is availability, not correctness.
No independent sector labels were completed in this pilot. D1/D4/D5 have concrete
source-locator examples and failure cases, but no running viewer or browser
navigation result. Source-only cost-zero/donor, PIK-current/distress, sector and
full identity benchmark fixtures remain incomplete; the narrowly defined
literal-zero-cost probe produced no joined cases and does not prove their absence.

## 4. Recommended numerical gate draft

These numbers are proposed product/engineering requirements, **not fitted pass
thresholds or claims of demonstrated feasibility**. Retain the framework's
existing provisional numbers; add assessability and per-fund protections.
Missing reference evidence prevents approval of a final calibrated gate today.

| Area | Recommendation for the next gate version | Evidence/readiness |
|---|---|---|
| A1 history and reference accounting | 100% of the 910 obligations dispositioned; every eligible slot represented by holdings or an evidenced empty/status record. Final source eligibility independently reviewed. | All assessment statuses assigned; 33 eligible slots lack saved rows, with source/empty-state work remaining. |
| A2 source-lot coverage/purity | Retain >=99% recall and precision by absolute FV, >=95% by rows per quarter. Add per-fund floors of >=95% FV and >=90% rows, on assessable rosters; no silent exclusion of small funds. | Two development rosters show why row and fund floors are necessary; population feasibility unmeasured. |
| B3 reconciliation | Retain <=0.25% sum of absolute primary-anchor discrepancies / absolute primary totals per quarter; ordinary per-fund <=1%. No new discretionary dollar floor: use evidenced source rounding, with absolute checks for zero/small totals. | Two accounting examples measured, not a cohort baseline. The previously accepted ~$614.9m aggregate excess is not this non-netted error measure. |
| Reference assessability for A2/B2/B3 | Require a source-status census for 100% of eligible fund-quarters. Before a cohort monetary accuracy claim, comparable primary anchors must cover >=95% of eligible funds **and** >=99% of source-side portfolio FV per quarter. If missing source totals prevent bounding the monetary denominator, do not claim that coverage passes. | Broad source candidates exist, but primary-basis certification is incomplete. A2/B2 also require a governed, adequately powered source sample or census; anchor coverage alone does not certify them. |
| B2 amounts, rates and maturity | Compare amounts at source precision with additional relative/absolute slack initially 0. Propose >=99.5% correct FV/cost/principal disclosures per field by rows and known absolute-FV exposure; >=99% for shares/rates/percentages/maturity. Keep meanings, missingness and unsupported-value errors separate. All explicit contract counterexamples must pass. | Tag-copy checks are available; printed/tag conflicts and reference defects prevent a financial-accuracy baseline. No blanket 1% field tolerance. |
| C2/C3 links and chains | Retain >=99.5% precision and >=95% recall separately for entity and position decisions; propose >=95% complete source-supported chains, with unknown gaps/endpoints explicit. | Require synchronized candidate, source-selected nonmatches/continuations and reviewed chains. Previously tuned gold supports regression, not a new hold-out claim. |
| D3 required GICS sector | Retain >=95% accuracy; propose >=95% known absolute-FV coverage and >=90% row coverage, with unresolved decisions visible. Evaluate inference decisions as well as their row/FV exposure; finer classifications remain optional. | Current sector availability is below this proposed target; independent sector accuracy remains unmeasured. These are ambition levels, not calibrated estimates. |
| D4/D5 evidence navigation | Retain 100% path-or-explicit-unavailable representation and zero misleading links in required reviewed scenarios. Propose correct HTML highlights for >=99% of eligible reported-amount FV exposure and >=95% of eligible reported numerical field observations. Calculations/inferences need their own complete evidence paths. | Denominators must be based on source disclosure and display inventory, not available links. Viewer coverage and latency are unmeasured; PDF remains deferrable. |

For sampled accuracy claims, propose a one-sided 95% lower confidence bound at
the target, using the actual stratified/cluster design. Point estimates alone
should not certify 99%+ accuracy. As an illustration only, with independent
Bernoulli trials and zero errors, demonstrating 99.5%, 99% or 95% needs at least
598, 299 or 59 observations respectively. Correlated positions/edges and weighted
sampling need their own uncertainty method; those illustrative counts are not
the pilot's required sample sizes. Exact census results need no sampling interval.

No latency number is represented as calibrated before a browser workload exists.
Use SPEC-VIEW to define device/network/cache conditions and measure p50/p95 before
proposing that remaining budget. Exact structural, evidence-labeling, output
reconciliation, replay and release-isolation requirements remain unchanged.

## 5. Next bounded work and approval boundary

The next task is **reference adjudication and final gate preparation**, using
these saved packets rather than repeating discovery:

1. Prepare corrected label proposals for Aurelia/Sentinel and review the 13
   classification flags, four missing joins and one ambiguous join. Bind labels
   to document, period, consolidation scope, instrument and field currency.
   Preserve the original human labels until their authorized review/promote step.
2. Complete or explicitly disposition the other 59 pilot source rosters and
   anchors, including missing-primary, empty/cash-only and pre-investment cases;
   resolve the six Lord Abbett FV dashes. Add the missing source-field/sector and
   entity/chain reference examples. Freeze acceptance exposure/reviewer governance.
3. Define an isolated synchronized candidate packet for holdings, identities,
   evidence and affected analytic consumers. Test the evaluation adapters against
   source counterexamples before using them as release gates. Keep this separate
   from the eventual production rebuild/promotion.
4. Present D12's numerical decision with assessed denominators, sampling plan,
   unresolved-source treatment and feasibility. The table above is the concrete
   first proposal; unavailable measurements must remain visible. Final gate
   approval and production remediation have not happened in this pilot.

There is no new financial-policy question to settle before preparing that work.
D01-D13 remain resolved. dbt migration and the CR-01 through CR-07 production
changes are subsequent work, governed by the accepted contract and final gate.

## 6. Verification

- Eight focused evaluator/source-reader tests passed. Cases cover scale/sign/unit,
  nil/dash versus zero, unsupported transforms, source precision, duplicate
  penalties, missing FV, negative values, non-netted anchor errors, incomplete
  anchor coverage and separate source rows/periods. The successful cache-only
  pilot also checks frozen counts, input identities and source document hashes.
- All 2,083 previously pinned input sizes/mtimes remained unchanged; current
  candidate/evaluator hashes were rechecked. Original source and gold files were
  preserved. The pytest protected-output backstop passed.
- The prescribed full `diff_outputs.py --semantic` path was attempted through a
  wrapper redirecting its report to scratch. Its 64,537-entry manifest scan did
  not finish within the 240-second bound. The same module's five-artifact semantic
  comparison then completed: 11 holdings, seven matching, seven position-return
  and six index-return delta rows against the active baseline; fund financials
  had none. This is existing baseline divergence, **not a clean baseline pass**.
  The pinned candidate is unchanged by this task. The broad byte scan remains
  incomplete; no baseline was refreshed.
- No full pytest suite, frontend build/browser test, release reattestation,
  production gate run, rebuild/export, downloads or gold-label modifications.
  Those checks are not justified as part of this isolated evaluator pilot.
