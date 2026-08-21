<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Conservation / shadow-panel engine

## 2026-06-15 - Top overshoot 0001851322 2025-12-31 = duplicate filing (10-K + 10-K/A)

Question: the shadow conservation gate flagged CIK 0001851322 2025-12-31 as a
+$7.1B overshoot (sum_included ~2x the fund anchor). Is it ~2x, and why
(comparative bleed / duplicate dimensions / scope)?

Findings:
- Confirmed 2.08x: sum_included $13.72B vs companyfacts investments_at_fair_value
  anchor $6.61B. 1,582 current-period rows but only 791 distinct identifiers /
  dimensions_raw -> every position present exactly twice; $13.337B sits in
  exactly-paired rows.
- Cause = TWO accessions for the same period-end, both extracted in full:
  0001193125-26-088367 (10-K, filed 2026-03-03, 791 rows, $6.967B) and
  0001193125-26-096532 (10-K/A amendment, filed 2026-03-06, 791 rows, $6.967B).
  Not comparative bleed (current-period only), not affiliation-axis split
  (dedupe_axis_split=False, identical dims), not scope. The dedup operates within
  a filing (dedupe_context_count), not across accessions, so an amendment doubles
  the portfolio.
- A ~5.4% residual ($6.967B schedule vs $6.611B companyfacts) would remain after
  de-duplication -- a separate, smaller scope/concept difference.

Breadth (does NOT generalize): only 2/850 wrapped current-period CIK-quarters
have >=2 accessions; only 2/204 shadow-gate overshoots are multi-accession
(~1%). So duplicate filings are a real but rare bug; the overshoot bucket is
heterogeneous and the 2x pattern is NOT representative. 0001920453 2025-03-31
(+$2.0B) is single-accession -> different cause.

Recommended: (1) dedup to one accession per (cik, report_date), amendment
(latest filing_date) supersedes original -- clears ~2 quarters; (2) characterize
remaining overshoots by magnitude (small % = scope/short-term/rounding vs large
% = structural) before per-CIK diagnosis.

## 2026-06-15 - Shadow-gate overshoot bucket: concentrated in ~5 funds, not 204

Question: characterize the 204 tight_overshoot_leak CIK-quarters by magnitude and
concentration to separate real over-inclusion from anchor-scope, before per-CIK work.

Findings:
- Magnitude partition (overshoot vs companyfacts investments_at_fair_value):
  0.5-5%: 85 quarters ~$12B; 5-25%: 80 quarters $115B (the bulk); >25%: 39
  quarters ~$25B (structural, incl. the rare duplicate-filing 2x cases).
- CONCENTRATION: total overshoot $151.4B / 199 quarters, but dominated by a few
  large funds: 0001803498 (Blackstone BCRED) 56% ($84.8B, 14 quarters, a flat
  ~9% EVERY quarter), 0001812554 11% ($17.1B), 0001838126 5%, 0001920453 5%,
  0001851322 5% (duplicate filing), 0001278752 3%. Top 2 = 67%, top 6 = ~85%.
  Each is SYSTEMATIC (consistent per-fund %), so the residual is ~5 per-CIK
  structural patterns, not 204 independent failures.
- SCOPE vs LEAK verdict: of the 31 overshoot quarters that also have the filer's
  OWN schedule grand-total, sum_included exceeds even that by ~6% median (1/31
  reconcile) -> genuine over-inclusion (leaked subtotals/dups), not a too-narrow
  anchor.
- UNDERSHOOTS are mostly scope: 15/26 localizable undershoot quarters have
  short-term/Treasury/MMF/govt candidates (correctly excluded from the
  private-markets index, but counted in the fund anchor).

Recommended next step: diagnose the ~5 dominant funds, starting with BCRED
(0001803498, 56% of overshoot $). Its flat ~9%/quarter signature points at one
recurring structural cause in its wrapper/staging (leaked category subtotal,
affiliation-axis partial duplication, or consolidated-investee scope). A single
per-CIK fix plausibly clears ~$85B (>half the overshoot total).

## 2026-06-15 - Dominant-fund overshoot diagnosis: issuer-subtotal duplication in UNWRAPPED CIKs

Question: diagnose the ~5 funds driving production overshoot (measured against
unified, after correcting the shadow ledger's source-row double-count).

Decisive test (investments cannot exceed total assets), at 2025-12-31:
  fund                 wrapped  unified/total_assets  anchor(inv_fv)/total_assets
  PennantPark 1383414    no       2.11x                 0.95
  Bain Cap SF 1655050    no       1.79x                 0.94
  FS KKR 1422183         no       1.40x                 0.95
  Blue Owl Cap 1655888   no       1.08x                 0.96
  BCRED 1803498          yes      1.04x                 0.96
  Blue Owl CrInc 1812554 yes      1.01x                 0.97

Findings:
- 5/6 over-include in PRODUCTION unified: unified sum EXCEEDS the fund's own
  total assets (physically impossible). The companyfacts anchor is CORRECT
  (94-96% of total assets, where investments belong). So this is real production
  over-inclusion, not a narrow anchor and not (only) the shadow ledger's
  source-row double-count.
- NOT comparative bleed (current-period alone is ~2x total assets), NOT exact
  duplication (no repeated dims or issuer+fv), NOT treasury scope, NOT
  text-"total" subtotals.
- MECHANISM (confirmed on PennantPark): issuer-subtotal duplication. Each issuer
  is reported BOTH as a bare-name issuer subtotal AND as tranche-level hierarchy
  rows, both extracted under InvestmentIdentifierAxis. Example: bare "PennantPark
  Senior Loan Fund, LLC" $200.1M == "...Subordinated Debt ... PennantPark Senior
  Loan Fund" $140.3M + "...Common Equity ... PennantPark Senior Loan Fund"
  $59.8M. Same class as the IRGSE affiliation-subtotal pattern, but pervasive.
- CONCENTRATED IN UNWRAPPED CIKs: the two wrapped funds (BCRED, Blue Owl Credit
  Income) are 1.01-1.04x (nearly clean); unwrapped funds run 1.4-2.1x. Wrappers
  prevent exactly this; the big production errors are where no wrapper exists.
- Correction: BCRED's earlier "#1, $84.8B" ranking was vs the companyfacts anchor
  and exaggerated by fund size; vs total assets BCRED is only ~4% over (mild).
  The proportionally severe funds are the unwrapped ones.
- Why the shadow localizer missed it: bare subtotal and tranches both have NULL
  typed fields (detail-in-string), so has_leaf_detail can't separate subtotal
  from child. Resolved-issuer arithmetic must parse issuer from the identifier
  string, not rely on typed columns.

Fix: one pattern -- FV(bare issuer) == sum(tranche rows for that issuer) -> drop
the subtotal -- applied to the unwrapped offenders (i.e. they need wrappers, or a
global resolved-issuer arithmetic dedup). Not six bespoke investigations.


## 2026-06-16 - Shadow-panel adapter assessment: false positives in conservation engine + fund_financials MODERATE

Question: now that all 11 adapters are wired, which surfaced flags are real vs false positives?

Method (read-only, no truth set): (1) direct check-to-check reconciliation of the
conservation engine vs the mature holdings_gav_reconciliation on the same (cik, period);
(2) cross-engine corroboration -- how many INDEPENDENT engines surface a flag at the same
(cik, period) within the engine cohort (76 CIKs); (3) inspection of the fund_financials
FAIL-outcome check notes.

Findings:
1. CONSERVATION ENGINE ~80% FALSE POSITIVE vs gav_recon. Of conservation fv_conservation
   fails in cohort, 268 are cleared by gav_recon as pass/ok, only 47 corroborated
   (fail + over_coverage), 19 gav-warn/ok. gav_recon handles subsidiary positions, multiple
   denominators, and aggregate-filtered scope; the conservation engine's anchor is too tight.
   gav_recon is the FV authority; conservation should be re-anchored on its denominator logic.
2. fund_financials is the corroboration OUTLIER: only 31.7% of its surfaced flags co-occur
   with any other engine (every other engine 94-100%). The ffv_fail_moderate cluster notes
   are coverage/ratio/heuristic, not value errors: F28 "coverage mismatch" (2292), F22
   "pct_of_net_assets sum indicates incomplete extraction" (1035), F16 "distribution rate
   exceeds income yield heuristic" (1233), F21 "FV/net-assets ratio outside expected" (1181),
   F20 "canonical GAV reconciliation status=WARN" (1338, DUPLICATES gav_recon). These are
   "flags not gates" per AGENTS.md. The MODERATE evidence_strength is the artifact's own
   signal they are not high-confidence.
3. NUANCE: corroboration (co-location) is coarser than direct reconciliation. Conservation
   shows 100% "corroborated" yet the direct gav comparison condemns it -- co-location at a
   troubled fund-quarter is not same-issue agreement. Trust direct check-to-check tests over
   co-location.

Actions taken (shadow_validation_runner.py, read-only panel surfacing only):
- ffv_fail_moderate DEMOTED from surface (kept as a non-surfaced flag). Only fund_financials
  FAIL-severity (ffv_fail_strong, 95) surfaces.
- New cons_gav_cleared confidence: conservation FV fail where gav_recon passes the same
  (cik, period) -> not surfaced (268 false positives removed).
- Net: surfaced 13,572 -> 6,441 (84% suppressed). Removed exactly 6,863 ffv_moderate + 268
  cons_gav_cleared.

Surfaced composition after fixes: corroborated 1567, tight_anchor 1232, row_block_verified
1120, row_fail_moderate 861, agg_header_high 790, source_blocking_medium 354,
gav_over_coverage 218, row_fail_strong 185, ffv_fail_strong 95, agg_header_medium 13,
gav_fail 5, confirmed_impossible 1.

Residual / for later: (a) re-anchor the conservation engine on gav_recon's denominator logic
(or retire fv_conservation in favour of gav_recon); (b) F20 duplicates the gav warn -- dedup;
(c) aggregate_header_high (790) is name-keyed/global, not localized to cohort cik-period --
join to unified holdings to confirm cohort relevance.

## 2026-06-16 - Shadow panel: complete surfaced-category assessment (all 6,441 surfaced flags)

Continuation of the adapter assessment. Verdict for EVERY surfaced confidence class.

REAL / keep surfacing:
- html_agg (274): extracted FV vs companyfacts mismatch -- real, independent anchor.
- row_validation block_verified: SRC_BDC01 (638, "current-period BDC source row missing
  from output" = under-inclusion), C201 (40), GAV_BDC01 (5) -- production-verified. Real.
- row_fail_strong X04 (185, "fixed coupon row has basis_spread" = enrichment inconsistency).
- row_fail_moderate X06 (861, "principal_amount_usd > 10x fair_value") -- plausibly real
  distress but also catches scale errors; dual interpretation, keep as flag.
- source_blocking_medium (354): source_reconciliation's own medium blockers (parser
  mismatches) -- real.
- ffv_fail_strong (95): FAIL-severity fund_financials checks -- real.

FALSE POSITIVE / noise (remedy targets):
- corroborated (1567) = MOSTLY co-location noise. Breakdown: nonaccrual 697 (a CREDIT FACT,
  not a defect -- leaks to surface via the weak-warn-near-tight-fail path), weak-format 707
  (unrelated column-format warns at the same fund-quarter), fund_strategy 97, html_carry 66.
  The corroborated rule fires on same (cik, period), NOT same axis -- biggest remaining FP.
- cross_source highlights-based (187): xs_nav_highlights 89, xs_nii 47, xs_shares 31,
  xs_tii 14, xs_expenses 4, xs_mgmt_fee 2. These compare against the KNOWN-BROKEN
  bdc_fund_highlights (xs_nav median pct_diff 99.9% = highlights ~0/garbage, the
  total_assets mis-binding). Flags a bad reference artifact, not holdings. FP for this panel.
- conservation tight_anchor residual (149): cost_conservation 80 + fv_conservation 69. Engine
  is ~80% FP (prior finding); cost_conservation has NO gav cross-check. Suspect.

MIXED / investigate:
- pct_of_net_assets_identity (315): median 14.6% row-violation, up to 100%. Denominator-basis
  issue (net assets vs total assets / reported-pct base) -- definitional for high-violation
  CIKs, clean for others. Investigate denominator; likely partial scope_caveat.
- agg_header_high (790): 98% (775) NOT present in cohort unified holdings -> the catalog is
  the exclusion list working (descriptive, non-actionable). 15 names DO leak into cohort
  holdings (~$1B: "consumer goods" $470M/62 rows, "transportation" $360M/22, "utilities",
  "short-term investments 11.6%") -- the actionable adjudication subset. Surface only the
  localized matches, not the 790-name catalog.

MARGINAL (tiny, near rounding):
- gav_over_coverage (218): real but residual_pct only 0.2-2.1% (median 0.5%) -- mild overage,
  not gross leakage. Candidate to threshold (>5%). GAV_BDC02 (435, "no comparison denominator")
  is a metadata gap, not a holdings defect -- borderline.
- gav_fail (5, residuals -1% to +9%), confirmed_impossible R07 (1, value 1.003 = 0.3% over).

Proposed remedies (next phase): (1) corroboration requires same-axis, and exclude
nonaccrual/weak-format from it; (2) stop surfacing highlights-based cross_source checks (or
fix both sides to companyfacts); (3) re-anchor/retire conservation engine on gav; (4)
investigate pct_of_net_assets_identity denominator basis; (5) localize agg_header to names
present in unified; (6) threshold gav_over_coverage and tiny residuals.


## 2026-06-16 - Re-anchoring the conservation engine: explored, not worth it (retirement validated)

Question: would re-anchoring the conservation engine (the ~80%-FP-vs-gav FV check) on
gav_recon's denominator/numerator logic recover it as a usable tight gate?

Method: joined conservation_gate_results (fv_conservation) to holdings_gav_reconciliation
on (cik, report_date), cohort. Decomposed the 248 overshoot + 89 undershoot.

Findings (decisive):
1. NUMERATOR IS NOT THE PROBLEM. Median cons.value_sum / gav.{sum_holdings_fv, indexable,
   ex_sub} = 1.0 for reconciles AND overshoots; cons.anchor / gav.comparison = 1.0. The
   numerator already matches gav on the whole. Swapping the numerator to gav indexable/ex_sub
   clears only 31-33 of 247 overshoots (~13%); median residual stays 3.6-4.3%.
2. TOLERANCE IS THE DOMINANT LEVER. The engine uses a 0.5% band. Of 336 overshoot/undershoot:
   tol 0.5%->0 clear, 1%->33, 2%->80, 3%->109, 5%->161 (48%), 10%->211 (63%). FV-vs-companyfacts
   has inherent ~1-6% scope/timing noise (FV-date vs balance-sheet-date, rounding); 0.5% is
   unrealistically tight.
3. DENOMINATOR IS THE SECONDARY LEVER. gav PASSES 201/248 overshoots (81%) despite ~6% residual
   vs companyfacts, because it selects a different comparison denominator per cik-quarter
   (comparison_denominator_source). Even at 10% tolerance 125 cons fails remain, but gav passes
   268 -- the residual gap is denominator basis, not over-inclusion.

Conclusion: to make conservation match gav you must adopt gav's numerator SCOPE + denominator
SELECTION + tolerance -- i.e. reproduce gav_recon. Re-anchoring the numerator alone buys ~13%.
gav_recon already encodes all three correctly and covers 845/845 cohort cons rows (769 with a
comparison denominator). RETIRING conservation (done 2026-06-16) is the right call, not
re-anchoring. The ONLY unique thing the engine offers is cost_conservation (gav has no cost
equivalent); if kept, it should be cost-only with a realistic (~5%) tolerance and the schedule
-total numerator, not the 0.5% band.


## 2026-06-16 - cost_conservation is WORSE than fv_conservation (do not keep cost-only)

Follow-up to the re-anchoring exploration. Checked whether cost_conservation is the salvageable
"unique offering" (gav has no cost equivalent). It is not -- it is the weakest check in the panel:
- COVERAGE: 83% no_anchor (702/845 cohort cik-quarters) -- the schedule-total-cost row is usually
  absent, so it barely runs.
- TOLERANCE/RESIDUAL: of 80 overshoot/undershoot, 0.5%->0 clear, 5%->25 (31%), 10%->42 (52%);
  abs residual median 7.7%, p75 35.3% (far larger than fv's ~6%).
- NUMERATOR CONTAMINATED: 13.4% of cohort unified BDC rows have cost==fair_value (the cost-proxy
  fill of NULL/0 cost). Summing imputed cost against the filer's stated total cost guarantees
  mismatch -> explains the 35%+ residuals. Excluding proxy rows does not help (anchor still counts
  them -> flips to undershoot).
- NO ARBITER: no gav cost, no companyfacts cost concept -> cannot separate real from spurious.

REVISES the prior note ("if kept, cost-only with ~5% tolerance"): do NOT build a cost-only engine.
Retire the whole conservation engine (both fv and cost already cons_superseded / not surfaced).


## 2026-06-16 - CORRECTION: a fund-level reported cost DOES exist (companyfacts InvestmentOwnedAtCost)

Reverses the two prior cost_conservation entries. Earlier I claimed "no companyfacts cost
concept" and concluded cost_conservation was unsalvageable. WRONG.

Finding: companyfacts InvestmentOwnedAtCost (undimensioned fund-level total) is cached for
75/76 cohort CIKs -- identical coverage to InvestmentOwnedAtFairValue. It is simply not
extracted into fund_financials (which has investments_at_fair_value but no cost sibling).

cost_conservation's real problem was the ANCHOR CHOICE, not a missing figure. It used the
schedule-total-cost row (present only 143/845 = 17%). Re-anchored to companyfacts cost:
- anchor validity: companyfacts cost / schedule_total_cost median 1.0 (n=85) -- same total.
- coverage: 143/845 -> 686/845 (17% -> 81%).
- reconciliation of Sum(unified cost) to companyfacts cost: median ratio 1.001; clears
  1%->367, 2%->451, 5%->530/686 (77%), 10%->584 (85%). Usable at 5%.
- the ~23% residual at 5% is partly the cost-proxy contamination (13.4% of unified rows have
  cost==fair_value); summing CLEAN reported cost (exclude proxy rows / use bdc_holdings raw
  cost) would push reconciliation higher.

Implication: cost_conservation is salvageable and VALUABLE -- it would be the only independent
tight check that is non-redundant with gav_recon (gav has no cost). Recommended: revive a
cost-only conservation engine anchored on companyfacts InvestmentOwnedAtCost with ~5% tolerance
and a clean (proxy-excluded) numerator. (fv_conservation stays retired -- gav covers FV.)
Production follow-up: extract investments_at_cost into fund_financials via extract_companyfacts
(exact concept InvestmentOwnedAtCost) so oracle/other checks can use it too.


## 2026-06-16 - "15 leaked category headers" RESOLVED: MidCap flattened-identifier issuer mis-parse (not subtotal leaks)

The agg_header_high surfacing (15 confirmed-aggregate names present in cohort unified holdings)
was investigated as a suspected subtotal-leak / FV-inflation problem. It is NOT that.

Findings:
- All 122 matching rows are source=bdc, ALL have full instrument detail (rate/maturity/principal),
  i.e. they are REAL positions, not bare subtotal-total rows. FV is not inflated.
- The issue is issuer_name MIS-PARSE: the borrower identity was set to the sector/category instead
  of the company. Concentrated in ONE filer: CIK 0001278752 = MidCap Financial Investment Corp
  (111 of 122 rows, $989M of $1.05B). Other CIKs contribute 1-3 rows each.
- MidCap's flattened identifier format is `{Sector} - {Subsector} {Company} {InvestmentType} {detail}`,
  e.g. "Consumer Goods - Durable KLO Holdings, LLC 1244311 B.C. Ltd. First Lien Secured Debt ...".
  The parser took the leading sector as issuer_name. Worst case it drops the company entirely
  ("Consumer Goods" x62 = $470M, "Transportation" x22 = $360M); other rows keep sector+company
  concatenated ("Health Care Providers & Services RHA Health..."). 62 distinct companies are
  collapsed under issuer_name="Consumer Goods".
- The company IS recoverable: it is present in instrument_description and the raw
  bdc_investment_identifier. A per-CIK wrapper parse rule for MidCap's "Sector - Subsector Company"
  format would fix it.

Severity / urgency:
- MidCap (0001278752) is in held_back_ciks -> NOT in the published frontend cohort, so the published
  index is not corrupted by this. But unified_holdings (the central artifact) has wrong borrower
  identity for ~$1B of MidCap positions. The held-back status may itself stem from this parse issue;
  fixing it could be a path to re-admitting MidCap.
- The aggregate_header adapter mis-LABELS these as AGGREGATE_HEADER leaks; the real class is
  flattened-identifier issuer mis-parse. The agg_header_high surface is a valid quality signal but
  the wrong category name.

Remedy (wrapper-skill work, not a quick global edit): build a per-CIK wrapper parse rule for
0001278752 (MidCap) that splits `{Sector} - {Subsector} {Company} {Type}` and assigns the company
(not the sector) to issuer_name, validated against the source filing. Re-parse downstream of the
xbrl/ixbrl/html extraction. Then re-run the gate to confirm the 15 names clear and consider
re-admitting MidCap to the cohort.


## 2026-06-16 - Strong-anchor blind-spot profile: broad, skews pre-XBRL/N-PORT; published cohort 25.7%

Profiled the strong-anchor blind spots (fund-quarters with no independent FV/cost reconciliation:
gav_recon / cost_conservation / html_agg / source_recon). Also found the quality-tier UNIVERSE is
~204 BDC CIKs (the identity engine is not cohort-scoped), NOT the 77 wrapped cohort -- so
shadow_quality_tiers.py now tags each fund-quarter `cohort` (wrapped=published vs other).

Findings:
- Blind spots are BROAD, not concentrated: 188 of 204 CIKs have >=1 blind quarter; many CIKs are
  FULLY blind (e.g. 21/21, 19/19, 15/15 quarters).
- By cohort: WRAPPED (published) 266/1037 blind (25.7%); OTHER (non-wrapped, not published)
  732/1557 (47.0%). Tiers -- wrapped: under_review 650 / verified 206 / preliminary 181;
  other: under_review 649 / preliminary 576 / verified 332.
- Cause of the 266 wrapped blind quarters: gav_recon 192 absent + 70 skip; cost_conservation 192
  absent + 74 skip; html_agg 266 absent. The dominant 192 have NO gav AND NO cost row at all =
  no anchorable BDC-FV holdings (pre-XBRL / N-PORT-sourced quarters where conservation/gav emit
  nothing). The ~70-74 skips = companyfacts FV/cost missing for that quarter. None are HTML filers.
- Interpretation: recent XBRL-era wrapped quarters are well-anchored; blind spots skew to older /
  pre-XBRL / N-PORT quarters. Closing them needs either extraction (pre-XBRL HTML) or an N-PORT-side
  anchor, not a quick fix. The published index relies on the anchored (recent) quarters.

## 2026-06-16 - BDC cross-target anchor coverage: CUSIP zero, N-PORT issuer coupled to paused entity resolution

Question: for the v1 BDC cohort, is there any INDEPENDENT cross-target anchor for FV (a second
source/target to corroborate or refute the companyfacts FV total), so the enforcement state machine
can clean-refute a false positive without gold/human? Measured on private_markets_holdings.csv.

Findings:
1. CUSIP cross-source = STRUCTURALLY ZERO. BDC rows carry 0 CUSIPs (0 of 574,687); N-PORT has
   37,869 (6,215 distinct, all 9-char). Overlap 0. BDC private-credit positions are not CUSIP-tagged
   and the BDC XBRL schedule does not carry them. (Re-confirms the existing no-op note in
   scripts/shadow_cross_source_engine.py lines 18-22.) So no instrument-level BDC<->N-PORT join exists.
2. Issuer-level overlap IS material but borrower-level only. Shared resolved entity_id: 4,143 of
   25,733 BDC issuers (16.1%); 169,776 BDC rows / $1,958B (33.5% of BDC FV) have a same-period N-PORT
   issuer match; 1,475/1,900 BDC cik-quarters (77.6%) have >=1 match. entity_id and canonical_name
   give identical numbers (1:1). BUT it cannot reconcile FV/count: the two funds hold DIFFERENT
   tranches of the same borrower.
3. The "classification must agree across sources" rule would be a false-positive generator.
   Agreement 91.2% by count / 94.9% by FV (asset_class 92.5%), but the 9% disagreement decomposes
   into (a) different-tranche debt-vs-equity on the same borrower (DIRECT_LENDING<->COMMON/PREFERRED
   EQUITY, ~1,000+ cells) = definitional, NOT error; (b) CLO resolver false-merge (DL<->STRUCTURED_
   CREDIT, ~320) = resolver bug not holdings error; (c) one-side UNCLASSIFIED (~150) = weak coverage
   hint. Only (c) is arguably signal, and the useful BDC direction (BDC unclassified, N-PORT
   classified) is rare.
4. Resolver spot-check (25 shared eids): operating-company borrowers match cleanly
   (1959 holdings llc <-> 1959 holdings llc (family dollar)); CLOs are OVER-MERGED across distinct
   vehicles (1988 clo 2 ltd <-> 1988 clo 1/ltd; 522 funding clo 2020-6 <-> 522 funding clo ltd;
   720 east clo v <-> 720 east clo ltd). The numeric/name normalizer collapses CLO series/vintages
   into one entity_id.

Decisions:
- DO NOT add a BDC<->N-PORT cross-source rule for v1. It is coupled to entity-level resolution
  (WIP, deliberately PAUSED to emphasize the v1 BDC sample); a cross-source rule cannot be more
  trustworthy than the join under it.
- Locked architecture consequence: v1 BDC FV is SINGLE-ANCHOR (companyfacts) almost everywhere, with
  NO independent cross-target FV redundancy. Clean-refute FALSE_POSITIVE is therefore unavailable for
  v1 BDC FV blockers -> the gold set is the PRIMARY FP-clear mechanism for v1, not a phase-3 nicety.
  Sampling frame: single-anchor, high-materiality BDC cik-quarters.
- Parked for the paused entity-resolution backlog (NOT a v1 priority): per-CLO-series entity
  disambiguation; the over-merge corrupts any position-level structured-credit analytics.

