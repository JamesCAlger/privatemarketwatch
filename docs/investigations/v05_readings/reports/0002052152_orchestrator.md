# Apollo Origination II Levered - orchestrator review, 2026-10-16

Original snapshot: scratch/fund_runs/0002052152.snapshot.json. Final investigator sandbox aoyae,
before spon3. Mechanical checks and independent investigation review pass; all 48 prior funds
have been regression-tested, with unresolved drift blocking acceptance (see October 17 checkpoint).
No active verification/gate-change requests were submitted. This note is not fund acceptance.

## Final fund checkpoint: aoyae

The first full review rejected aoyad: unchanged delayed-draw IDs still joined Elk and Victors.
Four narrowly keyed reject directives in the existing match-override lane remove wrong-company
links. No forced pairs or global matching changes were made. All 33 family rows and complete
components were independently checked, including unchanged IDs; eight component memberships
changed and 746 others remained unchanged. Victors December DDT remains disconnected from its
March/June chain; Elk revolver fragmentation also remains. Removal of impurity is not complete
continuity. A second rejection required narrowing the report's overbroad continuity claim.

The orchestrator also challenged a sign inconsistency during repair review. Cached printed row,
issuer subtotal and industry subtotal establish December Elk DDT FV +18,000, while its tag says
-18,000. One exact-row correction raises quarter FV by 36,000 to the filed 1,517,967,000 exactly.
This triggers two source-disagreement findings, both retained with evidence-backed proposals.
No check was suppressed. Candidate detector: compare aligned visible-cell signs with decoded tags,
using independent subtotals and genuine negative DDT/revolver rows as controls; never flip signs
merely to make totals tie. This is the fourteenth observation, not an implemented ledger rule.

Root's aoyae/aoyad field diff: one FV, provenance, correction marker and calculated %NAV change;
seven position IDs; 95/100 columns unchanged and no rows added/removed. Final independent sample
r3: 20 cards, 260 labels, zero published errors. No eligible coupon/share-count/reported-%NAV
cases and only two PIK cases; this does not certify unsampled fields or population accuracy.

Final review: reviews/0002052152_aoyae_final.json supports all 13 findings and 14 observations.
Both rejected reviews remain preserved. Full original-snapshot gate: INCOMPLETE; investigation
COMPLETE, zero problems; 18 current findings, 13 outstanding, eight proposed dispositions and
five C04 source ambiguities. Six of six operating quarters tie within the gate tolerance, not
all exactly. No new detector, acceptance reason or gate relaxation was installed. Shared-code
regression was subsequently completed; its unresolved findings remain acceptance blockers.

## 2026-10-17 final regression and test checkpoint

All 48 previously accepted funds were rebuilt at their accepted quarter scope: 34 UNCHANGED,
14 MOVED. The initial seven-fund quarter-scope mistake was corrected by rebuilding those funds
without June; only corrected comparisons enter these counts. Reports in this directory document
the initial classification replay and batches 3, 4 and 5.

Substantive causes: historical c8cf047 precedence changes were not replayed over seven prior
funds; canonical issuer names depend on batch composition and can change GICS labels; corrected
provenance scope exposes four existing KKR coupon findings. Numerical representation differences
are separately verified as equal. One historical MidCap Asurion GICS value remains unexplained.
Explaining classification changes is not approval of either classification. No accepted sandbox
registry update, acceptance commit or publication was made.

Full suite: 6,650 passed, five failed, 13 skipped, two xfailed, 743 warnings, 15,716.86 seconds.
No protected-output audit violation. Anchor and migration failures reproduce with Apollo changes
disabled in memory. The migration assertion conflicts with the committed no-cost-proxy ruling;
the anchor fixture conflicts with its cached cash-inclusive basis. FX scope and source-refresh
pins lag committed inputs. Lord Abbett's exact extra-row attribution is not independently replayed.
These diagnoses do not turn the suite green. Evidence: scratch/fund_runs/apollo_full_pytest_failure_review.md.

The final original-snapshot gate was rerun after regressions: INCOMPLETE, investigation COMPLETE
with zero problems, 18 findings / 13 outstanding / eight proposals / five C04 ambiguities, six of
six operating quarters tying. The final report and independent review remain bound and unchanged.
Owner queue rebuilt; no proposals accepted. Baseline semantic backstop result is recorded below
when completed. Production artifacts were not rebuilt in this campaign.

## Active review checkpoint: aoyad

The first independent sample found a real issuer error (C020: Elk Bidco printed, Victors published).
Returned to the same investigator. Full source-scope audit found three wrong member assignments
across March 2026 and December 2025, also carrying the wrong industry. The orchestrator approved
new exact-key extracted_industry row-correction support and blocked an erroneous first patch that
instead duplicated the output schema column. That test run was aborted; corrected patch has 22
passing row-correction tests, including industry-to-GICS and wrong-key negatives.

Build 4 aoyad: 754 rows, 11 outstanding unchanged. Versus aoyac: 16 issuer names, three source
industries/sub-industries/sectors, seven position IDs, 31 entity IDs, three canonical names and
three correction audit fields change; 92 of 100 columns unchanged, no rows added/removed. No
amount/rate/maturity changes. Investigator explains IDs as removing a false cross-issuer loan
chain while retaining separate undrawn facilities; independent full review pending.

Second independent sample: 20/20 cards validated, zero published errors. First sample preserved.
No claim of full correctness. Full reviewer /root/apollo_investigation_reviewer now checks every
outstanding finding and observation, independently reconstructing rule coverage. Both original-
snapshot gates pass mechanics; no independent-review acceptance yet.

Two observations added in repair round: member-carries-another-rows-name (including cross-issuer
matching consequence) and floor-rate-tag-scale-disagrees-with-page (17 source floor-tag errors,
no unified floor output to repair). New detector proposals only. Shared-code regression pending.
Store inventory confirms all three extracted_industry corrections belong to this fund; no older
ignored corrections for another fund became active. This is useful impact evidence, not a substitute
for the prescribed regression build.

## Detector triage

The report proposes eleven detectors. They are not eleven implemented ledger rules. All require
independent matched source evidence and false-positive tests before a proposal to the owner for
production ledger inclusion. No new acceptance reasons or financial thresholds are authorized here.

| Observation key | Orchestrator assessment and next step |
|---|---|
| missing-cost-does-not-trigger-cost-conservation | Prioritize position-level source-cost presence/value comparison. Aggregate cost_conservation has a 5% band and field_coverage_drop requires a 20-point coverage change; neither guarantees catching a single omitted cost. Use Datavant as a regression fixture, plus dash/foreign-cost negatives. |
| fixed-coupon-percent-tag-scale-disagrees-with-page | Candidate source percentage comparison, not a generic minimum-rate rule. Test the reported 100x error alongside low legitimate fixed coupons and spreads. |
| margin-tagged-as-plain-rate-published-as-coupon | Existing spread_printed checks total margin, not every coupon's semantic interpretation. Extend independently parsed row evidence to distinguish coupon, margin, floor and PIK; do not validate a derived coupon against its own extraction. |
| pik-printed-on-the-row-and-not-tagged | Existing provenance can verify supplied facts but does not establish completeness against untagged printed PIK. Candidate printed-token coverage check with cash/floor negatives. |
| principal-currency-from-unit-tag-not-checked-against-page | Prioritize printed currency versus raw principal currency before FX. Existing FX consistency checks can pass an internally consistent wrong USD assumption. Test the yen example, USD rows and explicit dual-currency columns. |
| issuer-name-from-member-differs-from-page | Name-shape gate cannot detect a plausible wrong company. Candidate exact source-row name comparison with explicit aliases/DBA handling; never fuzzy-merge distinct positions to make names agree. |
| instrument-text-keeps-member-words | Candidate structural warning, with negatives for legitimate instrument names containing rate/maturity words. Source-column context required; keyword presence alone is insufficient. |
| fund-income-ratio-published-is-not-the-printed-ratio | Prioritize annualization metadata preservation. Compare the exact financial-highlights ratio and period; annualized and unannualized fixtures must both pass correctly. |
| unit-count-basis-changes-between-filings | C04 tests share-count coverage, not stable units. Proposed >100x/<50% heuristic is an uncalibrated review flag, not a correctness gate. Test splits, transactions and changed units before proposing thresholds. |
| seed-financials-suppressed-without-published-reason | First expose source-present suppression and its reason. Whether seed financials should be published is a product-policy decision, not a verifier repair. |
| reference-rate-code-misprinted-by-filer | Existing reference_rate_printed checks a configured column; it may repeat a wrong legend mapping. Candidate same-period footnote comparison with dated mapping and no cross-fund inference. |

Code inspected: pipeline/column_validation.py (X11/FX), pipeline/oracle_checks.py (C04),
pipeline/provenance_reverify.py, scripts/shadow_identity_engine.py (spread_printed,
reference_rate_printed, field_coverage_drop), scripts/shadow_conservation_engine.py.
This is mechanism triage, not independent certification of the fund agent's source readings.

## Handoff discipline

If a repair is returned to the investigator, it must checkpoint after each build and wait for the
orchestrator's response before another build. The orchestrator stays active to evaluate verifier
requests, detector candidates, side effects and remaining evidence. Independent sample findings
must be resolved or specifically justified, followed by a final independent all-finding review.

## Baseline semantic backstop and remaining work

The existing semantic_diff implementation completed against the active baseline, with its report
redirected to scratch/fund_runs/apollo_semantic_aggregate_report.json. Semantic delta groups:
holdings 14, matches seven, position returns 12, index returns nine, fund financials zero.
Published holdings are 783,763 rows versus baseline 780,455 (+3,308). This comparison includes
pre-existing published drift and does not attribute changes to Apollo. The full manifest byte
walk was stopped after the core semantic comparison completed; no full-byte-audit pass is claimed.
The normal full-suite protected-output guard completed without a violation. No baseline refresh.

Acceptance remains blocked by the unexplained historical Asurion classification; the full suite
also remains failed. Further source/identity investigation must address batch-dependent names,
classification losses and the four KKR coupons. Test expectation/pin repairs require independent
contract/source review, especially the unreplayed Lord Abbett row delta. Apollo retains five
source ambiguities and eight unaccepted disposition proposals. Fourteen observations have
explicit detection decisions, but no new detector or acceptance standard was installed.
All builds, tests, reviews and diagnostics have exited. Work remains uncommitted and resumable;
no next fund was started and neither the accepted registry nor published outputs were updated.
