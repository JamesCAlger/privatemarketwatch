<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Agentic campaign retrospectives

## 2026-07-07 - Per-fingerprint stratification retrospective re-cut of ens2 B1 adjudications

**Question:** Do per-rule pooled real-rates (the ens2 calibration table) hide material
per-fingerprint-group (rule_id, cik) variation that would change B1->B2 routing? This is
the pre-adoption experiment specified in docs/weak_rule_remediation_architecture.md
section 5, step 1 (retrospective; zero new adjudications).

**Method:** scripts/ensemble/eda_fingerprint_stratification.py. 875 decided ens2
verdicts (360 real / 515 FA) re-cut into 420 (rule, cik) groups across 32 rules.
(a) dispersion: Monte Carlo chi-square (20k sims, seeded) of per-group real counts vs
the rule's pooled rate; (b) routing disagreement vs the direct-dispatch boundary
(real-rate >= 0.8), raw = n>=5 point estimate crosses, strict = n>=3 Wilson 95% CI on
the other side; weighted by n_units (flagged rows; fv_at_risk is empty on review-lane
queue rows, so FV weighting was not possible retrospectively); (c) per-group sample
sufficiency. Outputs: data/output/ensemble/ens2/fingerprint_stratification_by_rule.csv
and fingerprint_groups.csv.

**Results:**
- Sufficiency kills census stratification: median group n=1 (240/420 singletons), only
  42 groups n>=5 and 6 groups n>=10. The per-rule run spreads samples far too thin for
  per-group estimation; full per-stratum calibration (30-50/group) is out of reach.
- Dispersion is real but concentrated: 4/32 rules overdispersed at p<0.05 -- FX01
  (p~5e-5, survives any multiple-testing correction), PP03 (p=0.017), GAV_BDC02
  (p=0.045) and PCT01 (p=0.045) marginal (32 tests -> ~1.6 expected false positives).
- Routing disagreement is dominated by FX01: ciks 0001901037 (9/10 real) and
  0001803498/BCRED (10/10 real) vs pooled 0.51 [gated] -- 2,014 of 7,427 sampled FX01
  flagged units (27%) sit in these two direct-worthy groups. Also PP03 x 0001803498
  (9/9 real), X08 x 0002031750 (5/5 real vs pooled 0.45), and one counter-signal
  X02 x 0001989817 (0/3 real vs pooled 0.84 [direct]).
- 0001803498 (BCRED) is ~100% real across two rules; 0002031750 across two rules.
  Heterogeneity is per-FILER, exactly the fingerprint hypothesis.

**Decision per the spec's rule:** dispersion is material but narrow. Adopt only the
cheap form: RECORD the fingerprint on every future B1 calibration sample (costless),
do NOT build per-group sampling infrastructure. Caveat that tempers even that: FX01 --
the strongest heterogeneity -- is already slated for a deterministic structured-
attribute gate (spec section 4) that supersedes routing priors entirely; once it
ships, the residual case for stratification rests on PP03/X08-sized signals. Re-run
this cut after the FX01 gate and the next calibration pass. Prospective validation
candidates if routing changes are wanted sooner: FX01 x {0001901037, 0001803498},
PP03 x 0001803498, X08 x 0002031750.

## 2026-08-20 - B2 correction-agent Q4 2025 track record: cross-batch metrics rollup + round-4 fleet acceptance criteria

**Question.** Before approving the queued round-4 re-author fleet: how did the
B2 lane actually perform across the Q4 2025 batches (q4b2t4a, q4b2t4b,
q4b2exp, q4b2exp2)? Is it improving round-over-round, what did each failure
class cost, is every failure class now blocked by a mechanical contract, and
what acceptance bars should round 4 be held to?

**Method.** New reusable extractor `scripts/b2_run_metrics.py` ->
`data/output/agent_b2/b2_run_metrics.csv` (154 rows). All numbers below come
from batch artifacts (manifests, wrappers/prompts/logs, validate.txt, the
apply_gate JSONL logs, corrections_archive, findings_ledger.csv,
agent_fix_application_audit.csv, replay_live_stats_20260816.json.txt), not
from the changelog. Items only supported by the changelog are labeled
"narrated, unverified". Ledger basis: findings_ledger.csv as written
2026-08-16 15:04 (pre-q4final refresh).

### Artifact corrections to the task brief

- `manifest.json` is overwritten by each dispatch wave into the same batch
  dir, so it records only the LAST wave (e.g. q4b2exp manifest shows 2 rows
  vs 126 actually dispatched). True dispatch counts come from
  wrappers/prompts/logs; the extractor reports both.
- Two distinct gate schemas exist, not one: the leaf/replay gate (replay_ok,
  replay_equivalence, field_sanity, grounding_verified, conservation; v3 adds
  off_scope_invariance + defect_signature) and the value-packet gate used for
  q4b2t4b (target_cleared, no_new_flags, fv_at_risk_non_increasing,
  residual_improved, no_over_deletion, bands_hold, held_out_coverage).
- q4b2t4b gate log contains 20 CIK entries: 19 PASS / 1 FAIL. The changelog
  narrated "20/21 CIKs PASS"; the artifact says 19/20. One CIK short of the
  narrative either way; promoted archive = 21 leaves (19 store leaves + 2
  wrapper patches, consistent).
- Worker validate.txt files are UTF-16 LE (PowerShell Out-File default) and
  the q4b2t4b gate log carries a UTF-8 BOM; naive UTF-8 readers misparse
  both. The extractor BOM-sniffs.

### Per-batch rollup (artifact-derived)

| batch | dispatched | worker completed | authoring valid (dispatch-time validator) | gate result (CIK level) |
|---|---|---|---|---|
| q4b2t4a (canary, 08-12) | 2 | 1/2 | 0/1 (invalid template) | none run |
| q4b2t4b (wave 1, 08-12) | 22 | 22/22 | 22/22 = 100% | value gate: 19 PASS / 1 FAIL |
| q4b2exp (round 1, 08-13) | 126 (130 prompts; 4 missing_position_add not fired) | 125/126 | 123 OK / 1 missing / 1 invalid = 98.4% BUT the validator itself was defective: 94/124 authored leaves later schema-unusable => true validity ~24% | gate v1: 0 PASS / 61 FAIL (124 leaves) |
| q4b2exp2 (round 2, 08-13) | 96 (100 prompts; 1 skipped_stale recorded) | 95/96 | 94/95 = 98.9% (post-fix validator) | gate v2: 30 PASS / 30 FAIL (105 leaves); re-gate v3 scoped: 22 PASS / 8 FAIL (58 leaves) |

Gate refusal decomposition (FAIL reasons, categorized):

- v1 (round 1): bad_field_names 43, noop_stale 32, replay_equivalence_mismatch
  29, selector_unusable 6, missing_scope_columns 3, target_not_cleared 3,
  residual_not_improved 3, applier_error 2, other 2. Dominated by schema
  garbage the round-1 validator let through.
- v2 (round 2): selector_noop_stale 18 + selector_noop 2 (the "20
  selector-noops"), target_not_cleared 6, applier_error 4,
  new_flags_introduced 3, residual_not_improved 3, over_deletion 2, other 2.
  Schema classes GONE; the residual defect moved to ungrounded selectors.
- v3 (round 3 scoped re-gate): defect_signature 8, everything else 0
  (replay_ok 0 fails, replay_equivalence 0, off_scope_invariance 0,
  conservation 0). The remaining failures are B1 diagnosis quality (fixes
  authored for rates that were already plausible), not authoring mechanics.

Lifecycle (store + archive counts): staged `corrections/` currently holds the
round-3 40-leaf promotion set (21 column_remap, 11 classification_fix, 8
unit_rescale, all stamped 2026-08-13 14:17). Live store
`data/overrides/agent_b2_corrections/` = 34 leaves, which reconciles exactly
as 21 wave-1 promoted (archive promoted_q4b2t4b) + 40 round-3 promoted
- 7 v3 magnitude pulls - 13 production-noop pulls - 2 wrapper patches
(live in bdc_xbrl_wrappers, not this store) - 5 round-4 magnitude pulls = 34,
and matches the 2026-08-16 replay audit's 39 pre-pull leaves minus 5.

### Failure-class taxonomy vs corrections_archive (17 dirs; 11 are Q4-relevant)

| failure class | leaves | archive dir | mechanical contract now | verified? |
|---|---|---|---|---|
| Hard-coded prompt template (canary) | 3 | q4b2t4a_invalid_template | prompts generated from pipeline.correction_leaf.TEMPLATE_REGISTRY | code: dispatch_preflight.py, 9 refs |
| Schema-invalid authoring (filing-column names, coordinate-only selectors) | 94 | q4b2exp_schema_invalid_round1 | unified-schema field enums + identity-key selectors in validate_corrections -> correction_leaf | code + v2 refusals show class eliminated |
| Round-1 gate refusals (bad fields / stale noop / equivalence) | 47 | q4b2exp_gate_fail | same contracts + trial-output filename contract | v3: 0 replay/equivalence fails |
| Re-authored duplicates of already-promoted leaves | 21 | q4b2exp_duplicate_of_promoted | manifest skipped_existing preflight | manifest key present (0 hits since) |
| Unscoped historical rewrite (promoted then reverted) | 58 | q4b2exp_promoted_REVERTED_20260813 | scope.quarters REQUIRED + apply_scoped structural partition + off_scope_invariance gate + fingerprint_blast_radius.py | code (agent_b2_appliers.apply_scoped) + v3 off_scope 0 fails |
| Fix authored for a defect not present (wrong B1 diagnosis, rates) | 18 (8 CIKs) | q4b2exp_v3_gate_fail | defect_signature predicate (is the catcher) | v3 log |
| In-scope magnitude defect (principal x1000, rates /100) | 7 | q4b2exp_v3_magnitude_pull | check_magnitude_plausibility in gate_value_packet (run_remediation.py) | code |
| Production noop / inert first-wave dedup | 13 | q4b2exp_production_noop_pull | drift+health gates + grounded selectors (n_grounded_identifiers per manifest row) | code (dispatch_preflight) |
| Wrong mechanism class (missing position authored as comparative filter) | 1 | q4b2t4b_gate_fail_0001965934_comparative.json | value gate target_cleared caught it; missing_position_add applier now EXISTS in POST_STAGING_APPLIERS | code |
| LIVE FV-invariant corruption (magnitude class missed because conservation sees FV only) | 5 | q4b2exp_round4_magnitude_pull_20260816 (README evidence table) | magnitude predicate + replay_gate.py --stats-only live-store audit | code + the 2026-08-16 audit itself |

Classes WITHOUT a complete mechanical contract (residual risk):

1. Wrong-diagnosis B1 verdicts: defect_signature refuses the fix but nothing
   yet forces the verdict re-type (8 narrated re-types pending; the 0001965934
   packet still needs a missing_position_add re-author).
2. Magnitude blind spots: 2 live column_remap leaves (0001959568, 0002011498
   shares_held) have `no_norm` legs -- the predicate cannot judge a field with
   no off-target fund norm. 0001674760 column_remap is watchlisted
   (dev_log10 2.25, plausibly correct, needs human eyes).
3. rule_scope (11 packets) has no applier by design -- human basket.

### Cost of each failure class

- Round-1 schema invalids: 94/124 authored leaves unusable = ~75% of a
  126-worker fleet's authoring wasted (token cost "~230 workers over 24h" is
  narrated, unverified). Zero production impact (never promoted).
- Unscoped rewrites: 58 leaves reached production and rewrote historical
  quarters at 23 CIKs (narrated count; revert verified clean by fingerprint,
  net FV delta $16K on $7.46T narrated from the round-3 fingerprint).
  Worst-case class: caught by a one-off blast-radius audit, not a gate --
  the gate contract (off_scope_invariance) was built FROM this incident.
- Round-4 live pulls: 5 leaves corrupted production principal/shares at 5
  CIKs for ~3 days (08-13 promotion -> 08-16 pull). FV-invariant (README:
  FV untouched, acceptance blind), so public headline numbers were never
  wrong, but principal_amount/shares_held at those CIKs were (x1000 or
  vacated). This is the strongest argument for the magnitude predicate being
  a hard gate rather than a stats view.
- Everything else (canary invalids, gate refusals, noops, duplicates): caught
  pre-promotion, cost = authoring tokens + operator time only.

### Findings-ledger reconciliation (report_date = 2025-12-31)

Every expected number in the task brief reproduces exactly from
findings_ledger.csv: 2,609 findings; 763 with B1 verdicts (verdict_status not
MISSING and not placeholder_autodrafted; raw non-MISSING is 789 incl. 26
placeholders); states: adjudicated_false_alarm 312 (311 in-cohort),
real_error_unremediated 202 (187 in-cohort per
v2_70_gate_verified_wrapper_manifest entries[].cik), remediation_pulled 124,
remediated_promoted 51, needs_human 42, remediation_staged 30,
evidence_backlog 2 -- these seven sum to exactly the 763 verdict set -- plus
1,846 open (only 51 in-cohort; open fv_at_risk sum $12.78B is dominated by
out-of-cohort blocker-lane findings). No drift vs the brief: the q4final
quarter pass had not refreshed the ledger as of this read. Caveat:
fv_at_risk_m is only populated for open/false-alarm rows (real-error rows
carry 0.0), so FV-at-risk by lifecycle state cannot be read off the ledger.

### Production-side health

- agent_fix_application_audit.csv: 140 rules, ALL status=ok, zero noop, zero
  drift flags. B2 share: 18 unified_b2_corrections + 16 raw_bdc_staging = 34
  = exactly the live store; 106 unified_agent_rules unrelated to B2.
- replay_live_stats_20260816.json.txt: 39 leaves audited, 0 gate FAIL, 11
  magnitude legs out of band across 7 leaves/6 CIKs -> 5 pulled (evidence
  table in the archive README), 1 kept with row-selected evidence (0002011498
  column_remap), 1 watchlisted (0001674760). Post-pull acceptance PASS 7/7 is
  narrated (and consistent with commit 86f7539's calibrated re-stamp).

### Is B2 improving? Yes, on every measured axis

- Authoring validity: 24% (round 1, true) -> 97.9% (round 2) -> 100% on the
  mature template classes (wave 1). The jump is attributable to one
  mechanism: prompts and validator sharing TEMPLATE_REGISTRY as one truth.
- CIK-level gate pass: 0% (v1) -> 50% (v2) -> 73% (v3) -> 95% (19/20, wave-1
  value gate on mature classes).
- Refusal mix migrated from authoring mechanics (schema, fields, equivalence)
  to upstream diagnosis quality (defect_signature) -- the correct direction:
  the gate is now refusing B1 mistakes, not B2 mistakes.
- Each incident produced a named, code-level contract; v3 measured all four
  older failure classes at zero.
- Honest caveat: acceptance-metric movement from B2 in Q4 was modest
  (wave 1 measured no movement; the calibrated PASS rests on the 34 live
  corrections plus the excusal/classifier work). B2's Q4 value is proven
  correction infrastructure + row hygiene, not headline movement.

### PRE-DECLARED round-4 fleet acceptance criteria

Declared before dispatch, against measured baselines. FAIL on any bar means
stop, diagnose, re-fleet -- not widen the bar.

1. Authoring validity >= 95% of dispatched packets (baseline 97.9% round 2;
   validator unchanged since).
2. Selector no-op refusals = 0 (baseline 20 in v2; grounded selectors with
   per-string match counts + do-not-use marking are specifically designed to
   zero this; any occurrence is a grounding-pipeline defect).
3. Replay-equivalence and off-scope-invariance failures = 0 at the gate
   (baseline 0 in v3; regression = new contract breach).
4. Zero POST-promotion discoveries: no magnitude pulls, noop pulls, or
   reverts after leaves go live (baseline: 58 reverted + 13 noop + 7 + 5
   magnitude across rounds 2-4). Gate-time magnitude/defect refusals are
   acceptable outcomes; anything found by replay_gate --stats-only AFTER
   promotion is a round-4 FAIL.
5. Mandatory post-promotion audit: replay_gate.py --stats-only over the full
   live store with every leg in_band, explicitly evidence-excepted, or
   no_norm-documented; plus fix-application audit remaining 100% ok / 0
   drift; plus quarter acceptance PASS 7/7 under thresholds v2.
6. Zero NEW failure classes: any archive pull reason outside the 10 tabulated
   classes triggers a stop and a taxonomy update before further dispatch.
7. defect_signature refusals <= 10% of gated CIKs (baseline 27% in v3): the 8
   wrong-diagnosis verdicts are supposed to be re-typed BEFORE round 4; if
   the rate does not drop, B1 verdict quality -- not B2 -- is the binding
   constraint and the fleet should pause for re-adjudication.
8. Scope: round 4 draws from the ledger's actionable Q4 pool
   (real_error_unremediated 202 + remediation_pulled 124, of which 187 + 124
   in-cohort) and must not touch data/output/quarter_pass/ while q4final runs.

**Residual risk after round 4 (declared):** no_norm magnitude blind spot on
sparse fields; missing_position_add applier is code-present but has zero
promoted uses (first uses deserve manual review); rule_scope stays human;
fund-strategy oscillation is pinned only from the next quarter pass onward;
the ledger's FV-at-risk accounting for non-open states is absent, so
"cost of remaining errors in FV" is currently unmeasurable from the ledger.

## Match-gold batch mg3: first full-cohort position-match gold set (2026-09-05/06)

**Question:** what is per-tier position-match precision on the wrapper cohort, and
which match/entity failures dominate?

**Batch:** `mg3`, 535 blinded packets, 7 strata. 475 adjudicated by sandboxed Codex
workers (88.8%); 60 undispatched when the Codex account quota tripped the fleet's
circuit breaker. The missing 60 are spread evenly across strata (8.3%-17.5%,
overall 11.2%), so the scored set is representative, not a biased tail.
Scoring: `score_gold.py`; 475 valid, **0 invalid**.

### Build defect found and fixed first

`sample_chains` drew `tier_random` and `fv_jump` from `position_id_edges.csv`, which
is not cohort-filtered, while the holdings frame is. Sampled position_ids from
non-cohort funds resolved to no rows and the packets were written EMPTY, surfacing
in the worklist only as `has_cached_filing=False` -- indistinguishable from a cached
HTML shortfall. Batch mg2 had 223/580 empty (199 of them tier_random). Fixed with the
`e_cohort` view plus a fail-loud zero-row guard in `write_batch`; mg2 -> mg3 on
identical holdings: empty 223 -> 0, adjudicable 357 -> 535, tier_random adjudicable
84 -> 240. Without the fix, per-tier precision would have been published on a third
of the intended n.

### Per-tier edge precision

`tier_random` only (the unbiased, production-representative stratum; the other six are
deliberately anomaly-selected and run ~10pp lower by construction). UNCERTAIN excluded
from the denominator per the runbook.

| tier | precision | 95% Wilson | n |
|---|---|---|---|
| SUPP_B2_unique_exact_name | 0.95 | [0.91, 0.98] | 191 |
| B1b_position_key | 0.95 | [0.87, 0.98] | 73 |
| B2_exact_name | 0.94 | [0.87, 0.97] | 93 |
| A_within_filing | 0.93 | [0.84, 0.97] | 69 |
| E_entity_fingerprint | 0.92 | [0.80, 0.97] | 39 |
| C_normalized_name | 0.84 | [0.70, 0.93] | 38 |
| D_fuzzy | 0.82 | [0.73, 0.89] | 84 |
| **ALL (tier_random)** | **0.92** | **[0.89, 0.94]** | **587** |

All-strata pooled (what `precision_by_tier.csv` reports) is 0.89; anomaly-selected
strata alone are 0.82 [0.75, 0.88].

**Finding:** the four identity-based tiers cluster at 0.93-0.95 and are statistically
indistinguishable from each other. The two approximate tiers -- `C_normalized_name`
0.84 and `D_fuzzy` 0.82 -- are ~10pp worse. Tier reliability splits on
exact-vs-approximate, not on the assumed A > B1 > B2 > C > D ladder.

**Watch item raised and withdrawn:** at 28% of the batch `A_within_filing` read 0.84
(n=19) and looked inverted against B2. It regressed to 0.92 (n=52) at 61% and 0.93
(n=69) at completion. Small-sample noise, correctly bracketed by the reported interval.

### Two dominant defect families -- both borrower/position confusion

1. **Chains hop between tranches of the same borrower.** Affects even `A_within_filing`
   (e.g. a chain jumping from a $1.22M SOFR+5.75% tranche maturing 2037 to a separate
   $1.40M tranche maturing 2030, same issuer). Directly violates the position-level
   contract in AGENTS.md.
2. **Entity clustering merges genuinely different borrowers.** Magenta Buyer (McAfee)
   with Oranje Holdco (KnowBe4); PHC Buyer (Patriot Home Care) with Cherry Bekaert
   Advisory; Circustrix (SkyZone, Leisure) with Intelligent Medical Objects (Health
   Care Tech). Mechanism is measurable: WRONG_MERGE packets carry a median max
   `issuer_name` of **201 chars** vs **70** for CONFIRMED -- unparsed
   `bdc_investment_identifier` strings where shared category boilerplate
   ("Debt Investments | Internet Software and Services | ...") dominates the similarity
   and the borrower name is buried. 76 of 83 WRONG_MERGEs are on names >=60 chars.
   Spread over 14 of 18 entity CIKs seen, top two only 44 of 83 -- **global
   identifier-parsing defect, not a per-CIK quirk.** The fix belongs upstream of
   entity clustering: extract the borrower from the identifier first.

### Stratum yields (each stratum found what it was built to find)

| stratum | headline |
|---|---|
| within_fund_name_cluster | **0 CONFIRMED / 54 WRONG_MERGE** |
| cross_fund_near_miss | 1 CONFIRMED / 45 WRONG_MERGE |
| entity_merge_verify | 37 CONFIRMED / 16 WRONG_MERGE (30% error) |
| interior_singleton | 21/33 MISSED_LINK |
| fv_jump | 15/35 MIXED, 2 WRONG_MERGE |
| drift_break | 9/35 MISSED_LINK |
| tier_random | 177/215 CONFIRMED at packet level (82%) |

### Anti-fabrication check

All 87 coordinate citations in the first tranche of verdicts were resolved against the
cached filings via `evidence_cli tables`: **87/87 point at tables and rows that exist**.
Quoted text verified verbatim cell-for-cell on spot-checks. Two workers declined to
adjudicate rather than guess when the sandbox rejected their process spawns.

### Caveats

- **Single adjudicator vs the matcher, not ground truth.** These are one Codex
  adjudicator's verdicts; the human audit slice (runbook step 5, `audit_slice.csv`)
  is what converts this into a defensible number. Precision here is a strong proxy.
- **Confidence is uninformative**: 0 of 475 verdicts below 0.90, median 0.99. It
  cannot be used to filter, weight, or triage, and should not be published as a
  quality signal.
- 60 packets (11.2%) unscored pending quota reset; strata evenly affected.
  **Resolved 2026-09-07 -- see "Completion" below.**
- Anomaly-selected strata cannot support base-rate claims by construction -- only
  `tier_random` does.
- Cross-quarter stability not measured; gold set versioned by batch id (mg3).

### Completion 2026-09-07: 535/535 scored

The 60 quota-blocked packets were dispatched at 10:26 after the Codex reset
(`scripts/match_gold/dispatch_match_gold_workers.ps1 -BatchId mg3 -MaxParallel 2
-MaxAttempts 3`, elevated shell): **60/60 OK, 0 failed, 72.6 min**, one sandbox-logon
retry. `score_gold.py`: 535 valid, 0 invalid, 0 missing. Final tables
(`scratch/2026-09-07_mg3_resume/final_tables.py` over `gold_set.csv`):

`tier_random` edge precision, UNCERTAIN excluded:

| tier | precision | 95% Wilson | n | was (475) |
|---|---|---|---|---|
| SUPP_B2_unique_exact_name | 0.96 | [0.92, 0.98] | 200 | 0.95 |
| B1b_position_key | 0.95 | [0.89, 0.98] | 85 | 0.95 |
| B2_exact_name | 0.94 | [0.88, 0.97] | 104 | 0.94 |
| E_entity_fingerprint | 0.93 | [0.81, 0.98] | 42 | 0.92 |
| A_within_filing | 0.90 | [0.82, 0.95] | 73 | 0.93 |
| C_normalized_name | 0.86 | [0.72, 0.93] | 42 | 0.84 |
| D_fuzzy | 0.82 | [0.74, 0.89] | 97 | 0.82 |
| **ALL (tier_random)** | **0.92** | **[0.90, 0.94]** | **643** | 0.92 |

Pooled all-strata 0.90 [0.88, 0.92] (n=769); anomaly-only 0.82 [0.74, 0.88] (n=126).

**What moved:** `A_within_filing` 0.93 -> 0.90 (66/7 of 73): the last four edges
included one more WRONG, and at n=73 one edge is 1.4pp. Still inside the interval
reported at 475 and still indistinguishable from the other identity tiers, but the
tranche-hopping finding in F-section of the assessment below is the mechanism -- it
is the one identity tier that ranks tranches of the same borrower by FV proximity.
The headline (0.92, exact-vs-approximate split) is unchanged.

Final packet-level stratum yields (535): within_fund_name_cluster 0/59 CONFIRMED
(59 WRONG_MERGE); cross_fund_near_miss 2 CONFIRMED / 51 WRONG_MERGE;
entity_merge_verify 40 / 19 WRONG_MERGE (32%); interior_singleton 26/40 MISSED_LINK;
drift_break 10/40 MISSED_LINK; fv_jump 15/40 MIXED, 4 WRONG_MERGE; tier_random
198/240 CONFIRMED (82.5%), 21 INSUFFICIENT_EVIDENCE across all strata (3.9%).
Confidence still uninformative: min 0.90, median 0.99, 0/535 below 0.90.

**Note on basis:** the 2026-09-06 assessment and the contested A/B tables below were
computed on the 475-verdict slice. The 60 additions do not change any of their
mechanism conclusions; the per-CIK WRONG_MERGE counts in F1 are undercounts by the
same ~11% and the replay harness should be re-run on the full 535 before the
mg4_contested comparison is published.

## 2026-09-06 - mg3 assessment: where position-match errors come from and what to change

**Question:** taking mg3 as it stands (475/535 scored), which mechanisms produce the
WRONG / WRONG_MERGE / MISSED_LINK verdicts, and which fixes belong in the global
pipeline vs per-CIK overrides?

**Basis:** the 475 verdicts + packets under `data/output/match_quality/gold/mg3`
(728 edge verdicts); exposure counts from `private_markets_holdings.csv` restricted to
the 77 manifest CIKs (282,937 rows; 2026-03-31 = 32,285 rows / $393B FV). Diagnostic
scripts were session scratch (not committed); every count below is reproducible from
those two inputs.

### F1. WRONG_MERGE is concentrated in a few identifier-format families

"Unparsed" = `issuer_name == bdc_investment_identifier` in the packet rows.

| CIK | fund | packets | unparsed rows | WRONG_MERGE |
|---|---|---|---|---|
| 0001899996 | Fidelity Private Credit Central Fund | 35 | 76/79 | 32 |
| 0001834543 | BlackRock Direct Lending Corp | 31 | 67/67 | 29 |
| 0001287750 | Ares Capital | 61 | 3213/4313 | 18 (13 are co-borrower labels, see F3) |
| 0001572694 | Goldman Sachs BDC | 25 | 399/708 | 10 |
| 0001786108 | Trinity Capital | 17 | 75/75 | 10 |
| 0001646614 | Silver Point Specialty Credit | 11 | 25/29 | 8 |

Six CIKs account for 107 of 129 WRONG_MERGE packets. The earlier "global, not per-CIK"
reading was right about the fix location (the parser) but wrong about the spread: the
defect is a handful of identifier dialects, each concentrated in specific filers.

Mechanism, verified in code: `entity_resolution._extract_bdc_name` only enters its
metadata-blob branch on three keywords (`investment type`, `interest rate`,
`maturity date`). The BlackRock / Fidelity / Trinity / Silver Point dialects use other
vocabulary (`Instrument`, `Ref SOFR(Q)`, `Maturity 7/27/2028`, `Type of Investment`), so
the blob branch is skipped, the legal-suffix cutoff keeps the leading section+industry
boilerplate (`Debt Investments Internet Software & Services Magenta Buyer, LLC`), and
`token_sort_ratio >= 85` in `_fuzzy_cluster` merges any two borrowers sharing that
boilerplate. All five of these CIKs already have per-CIK anchors under
`data/overrides/identifier_anchors/` (SECDEBT / EQUITY / ASSETTYPE labels) that would
strip the prefix; entity resolution does not consult them.

Exposure at 2026-03-31: 7,537 cohort rows (23.3%) and 46.0% of FV carry an unparsed
issuer_name. Two sub-populations: (a) flattened boilerplate dialects, names >= 100 chars
(Trinity 456/461, BlackRock 242/247, Silver Point 191/198, Bain PC 170/412, Fidelity PCF
106/347, GSBD 165/563); (b) `Company, Instrument N` dialects where issuer_name carries the
instrument label + ordinal (Ares 1400/1421, Ares Strategic Income 1245/1260, BCRED
1054/1277, HPS CLF 767/831, T. Rowe OHA 384/384). Population (b) is where F2 lives.

### F2. Tranche hopping is the dominant chain defect in the identity tiers

tier_random WRONG edges: 47. Roughly 36 are same-borrower / different-tranche
(examples: OneDigital S+4.25% 11/2027 to S+3.25% 07/2031 via B2; UKG 5/2026 to 2/2031 via
A_within_filing; Qlik 10/26/2030 to 10/28/2030 via C; SGA Dental $86K to $2.57M par via
C; Banyan $48K to $1.88M via C; Eye Health $329K to $72K via B1b; Kaseya lots with equal
par and different cost via B2). The remaining 11 are all GSBD D_fuzzy (F4).

Mechanism: A / B1b / B2 / SUPP_B2 resolve contested name groups by FV proximity first;
maturity, spread and principal are secondary tiebreakers (B1b, B2) or absent (A,
SUPP_B2). `MAX_FV_RATIO_IDENTIFIER = 50` admits pairs 30-40x apart in principal. The
365-day maturity veto exists only in C / D / E. Nothing checks coexistence: the begin
row's near-identical twin (same name, maturity, spread, principal within 1%) is present
in the end quarter and the edge still goes elsewhere.

Exposure, 2026-03-31 cohort, share of rows in a within-quarter group with n >= 2:

| grouping key | rows | FV |
|---|---|---|
| exact issuer_name | 56.7% | 37.2% |
| + trailing ordinal and parenthetical stripped | 68.9% | 60.3% |
| + maturity_date + basis_spread | 51.6% | 39.4% |
| + principal_amount (exact) | 9.2% | 3.9% |

Null shares: maturity 13.0%, spread 22.0%, principal 18.9%. Name alone is
non-identifying for more than half of cohort rows; principal is the discriminator that
collapses contention, and it drifts only by amortisation / draws quarter to quarter.

Trailing ordinals (`First lien senior secured loan 2`, `One stop 3`) are filer-side and
renumbered between quarters (Gateway US 2 to 3 was a MISSED_LINK; Alera / Formerra /
Apex hops were WRONG). They currently let SUPP_B2's uniqueness guard pass on the wrong
row. Ordinal share at 2026-03-31: T. Rowe OHA 92%, HPS CLF 73%, BCRED 50%, Ares 35%.

### F3. The entity_merge_verify "30% error" is mostly a rubric artefact

13 of 16 WRONG_MERGE there are Ares co-borrower labels (`Acrisure, LLC and Acrisure
Finance, Inc.` vs `Acrisure LLC`; Higginbotham + HIG Operations; AthenaHealth + Minerva
Holdco + BCPE Co-Invest), ruled wrong at legal-entity grain. Three are real: MRI Software
/ Bullhorn (one identifier concatenating two positions), Coding Solutions /
Governmentjobs.com, Integrity Marketing Acquisition (debt) vs Integrity Marketing Group
(equity). "X and Y" labels at 2026-03-31: Ares 470 rows, Ares Strategic Income 208.
Decision needed before Phase 1 borrower_id: co-borrower group = one borrower_id
(recommended for position tracking) or separate legal entities under one
borrower_group_id. Until decided, entity precision on Ares / ASIF is undefined.

### F4. The GSBD header leak alone drags D_fuzzy

GSBD issuer_names carry `United States - 200.15% 1st Lien/Senior Secured Debt - 188.54%`
(pct-of-net-assets that change every quarter): 2,448 rows. Exact-name never matches across
quarters, so every GSBD chain routes through D_fuzzy, where Jaro-Winkler prefix weighting
makes all same-section names look alike. 11 of 15 tier_random D_fuzzy WRONG edges are
GSBD; without them D_fuzzy is about 0.95, in line with the identity tiers.
`bdc_identifier._parse_bdc_identifier` handles the no-dash GS form (`Investment ... N%
Company Industry ...`) but not this dashed `Country - N% Category - N% Company` form.

### F5. MISSED_LINK (30 packets) and packet defects

- Legal-suffix / punctuation variants: `Ltd.` vs `Limited`, `S.A R.L.` vs `Sarl`, `Inc`
  vs `Inc.`, `Holdco` vs `Holdco, LLC`, comma placement, LaserAway typo. C / D should
  catch these; which guard vetoed them is unmeasured.
- Identical rows across three quarters simply unmatched (Metropolis, L&J Holding, AEP
  Passion, AWI, Pearl Media, CloudBees). Candidates: `MAX_NAME_MULTIPLICITY`, FV>0
  requirements, cascade consumption. Needs the replay in R1.
- Co-borrower header change (`Cradle Lux Bidco` to `... and Hamilton Thorne`): F3.
- Packet defects that cap what the gold set can say: drift_break rows carry null
  `row_id` (proposed_links unusable); interior_singleton `candidate_rows` often omit the
  true neighbour (NEFCO, Sovos, Meritus, Routeware, all INSUFFICIENT_EVIDENCE); 8
  tier_random packets shipped empty filing bundles.

### Recommendations, ordered by expected precision gain per unit of work

G = global pipeline, P = per-CIK override, M = measurement.

1. **(M, do first) Missed-link / wrong-edge replay harness.** For every MISSED_LINK
   proposed pair and every WRONG edge in mg3, re-run each tier predicate
   deterministically and log which guard admitted or vetoed it. Cheap (475 packets),
   turns F2 / F5 hypotheses into counts before any threshold moves, and becomes the
   regression gate for R2-R5. Fix `build_packets`: emit `row_id` for drift rows; widen
   `candidate_rows` to all adjacent-quarter rows in the same 4-char block or entity_id.
2. **(G) Contested-group assignment in the identity tiers.** When (cik, quarter,
   ordinal-stripped name) has n >= 2 on either side: cost = principal log-ratio, then
   maturity equality, then spread equality, then FV proximity; veto maturity mismatch
   when both known, in every tier; tighten `MAX_FV_RATIO_IDENTIFIER` to about 5 inside
   contested groups; add a coexistence veto (if a near-identical row exists in the end
   quarter, the edge goes there or nowhere). Gate: mg3 WRONG edges fall, no new
   MISSED_LINK on the replay.
3. **(G) Treat trailing ordinals as non-identifying** in the exact tiers (strip in
   `_name_lower`, keep only as a weak tiebreaker). Ship with R2.
4. **(G + P) Fix issuer-name extraction upstream of entity clustering.** In
   `_extract_bdc_name`: strip section / industry prefixes using `_INDUSTRY_LABELS` and the
   per-CIK anchors; extend `_METADATA_KEYWORDS` to the observed vocab (`instrument`,
   `ref `, `type of investment`, `maturity `). In `_fuzzy_cluster`: compare distinctive
   tokens only (drop category / industry vocabulary before `token_sort_ratio`) so shared
   boilerplate cannot reach 85. Regression set: the 99 within_fund_name_cluster +
   cross_fund_near_miss packets (0/54 and 1/45 CONFIRMED today).
5. **(P) GSBD 0001572694.** Add the dashed `Country - N% Category - N% Company` form to
   `_parse_bdc_identifier` (or an anchor), rebuild. Expected: D_fuzzy 0.82 to about 0.95
   and GSBD chains move to exact tiers.
6. **(P) Row-level fixes through existing mechanisms.** MRI Software / Bullhorn
   concatenated identifier: `row_corrections.csv` or aggregate-row override; Coding
   Solutions / Governmentjobs.com: `entity_overrides.json` split once R4 lands. Do not
   add per-CIK entity merges for Ares co-borrowers until F3 is decided.
7. **(M) Rubric and publication.** Add verdict sub-codes (tranche_hop,
   different_borrower, co_borrower_group, name_variant, renumbered_ordinal,
   comparative_row) so the next batch is machine-classifiable; drop confidence from
   published outputs; decide co-borrower grain; finish the 60 quota-blocked packets and
   the 43-packet `audit_slice.csv` before quoting 0.92 outside the repo.

**Non-recommendation:** do not move `MIN_JW_SIMILARITY` or the entity fuzzy threshold
globally on this evidence. The failures are input-name quality and assignment cost, not
threshold placement.

### Recommendation detail (2026-09-06, same session)

Each item: mechanism, the change and where it goes, verification, risk.

**R1. Replay harness + packet-builder fixes (measurement, first).**
Mechanism: mg3 tells us *that* an edge is wrong or a link was missed, not *which guard*
admitted or vetoed it. Without that, R2-R5 are guesses.
Change: new `scripts/match_gold/replay_verdicts.py`. Input = mg3 `gold_set.csv`, the
verdict JSONs (proposed_links row_ids), packet edges (begin/end row_ids), unified
holdings, `position_id_edges.csv`. For every WRONG edge and MISSED pair compute the
features each tier consumes: cik/source/quarter adjacency, exact-lower name equality,
`_normalize_name_sql` equality, Jaro-Winkler, 4-char block, per-side name multiplicity
vs `MAX_NAME_MULTIPLICITY`, FV>0, FV ratio vs each tier cap, classification flip,
`_inst_subtype`, maturity gap, `_strong_position_key_sql`, CUSIP. Emit per pair per
tier: ADMITTED / VETOED(reason) / N/A. For WRONG edges also emit the "twin" (best
alternative end row by name+maturity+principal) and its cost vs the chosen row. For
MISSED pairs flag cascade consumption (either row already used by another edge).
Packet fixes in `scripts/match_gold/build_packets.py`: drift_break rows are emitted
without `row_id` (the drift candidate query around line 127 never selects it), so
proposed_links cannot be applied; `candidate_rows` for interior_singleton should include
every adjacent-quarter row in the same cik sharing the 4-char block or `entity_id`,
capped at ~40; mark packets whose accessions have no cached HTML at build time
(`cache_coverage.py`) instead of letting workers discover it.
Verify: one table, veto-reason x tier, for the 30 MISSED and 69 WRONG. Re-run after each
of R2-R5; the harness is the regression gate.
Risk: none to production; read-only.

**R2. Contested-group assignment in the identity tiers (global).**
Mechanism: when a borrower has several concurrent tranches with the same name, A / B1b /
B2 / SUPP_B2 pick by FV proximity (`ORDER BY _fv_prox` first, or after
`_suffix_match`/`_attr_penalty`), `MAX_FV_RATIO_IDENTIFIER = 50` admits 30-40x principal
gaps, the 365-day maturity veto exists only in C/D/E, and nothing checks whether the
begin row's twin is sitting in the end quarter.
Change (all in `pipeline/position_matching.py`):
- One CTE computing `contested` = ordinal- and parenthetical-stripped lower name has
  n >= 2 on either side within (cik, quarter, source). Reuse in every tier.
- Cost order for identity tiers inside contested groups: maturity equality (when both
  known) -> principal log-ratio -> spread delta -> FV proximity -> trailing-ordinal
  match (demoted from first to last). Route A/B1b/B2/SUPP_B2 through `_bipartite_dedup`
  with a new `tier_b` entry in `_compute_pair_cost`, so assignment is optimal per
  component instead of greedy `ROW_NUMBER`.
- Caps inside contested groups: principal ratio <= 4 when both known (DDTL draws can
  double; Ruppert 15.6 -> 18 was a confirmed same-facility draw), FV ratio <= 5. Keep 50
  for uncontested groups (unit-scale cases).
- Maturity: hard veto on mismatch when both known *and* an equal-maturity candidate
  exists; otherwise allow the 365-day gap (amendments and extensions are real; Qlik
  10/26 vs 10/28 is caught because the equal-maturity twin exists).
- Coexistence veto as a safety net after assignment: if a twin of the begin row (same
  stripped name, same maturity, principal within 2%) exists in the end quarter and the
  edge does not go to it, drop the edge. Prefer a singleton to a wrong link: wrong
  merges corrupt per-unit return series, missing links only shorten them.
- Tier A (`_match_bdc_within_filing`): comparative rows restate prior-quarter principal,
  so add principal equality as the first key; UKG 5/2026 vs 2/2031 would not survive.
- Null principal (19% of rows): fall back to today's order. Keep the new cost behind a
  module flag for a side-by-side run.
Verify: R1 replay (target: the ~36 tranche-hop edges gone, <= 2 new MISSED);
`pipeline/match_quality.py` chain_continuity and singleton_decomposition move within a
stated tolerance (continuity may dip; the trade must be shown, not assumed);
`diff_outputs.py --semantic`; per-unit price-return outliers in `position_returns.csv`
should fall (the downstream harm metric); `tests/test_position_matching.py` plus new
cases for each mg3 example class.
Risk: continuity loss where principal is null or filers restate principal; mitigated by
the fallback and the flag.

**R3. Trailing ordinals are not identifying (global).**
Mechanism: `First lien senior secured loan 2` / `One stop 3` ordinals are filer-side
and renumbered between quarters (Gateway US 2 -> 3 missed; Alera, Formerra, Apex hops
wrong). B2 and SUPP_B2 key on the raw lowercase name, so the ordinal is part of the
identity and SUPP_B2's n=1 uniqueness guard passes on the wrong row.
Change: preferred at the parser, not the matcher. Have `_parse_bdc_identifier` emit the
ordinal into a new additive column `instrument_ordinal` and drop it from `issuer_name`
(keep it in `instrument_description`). Then B2/SUPP_B2 `_name_lower` and the SUPP_B2
uniqueness count are ordinal-free automatically, and `_trailing_num` stays as the last
tiebreaker. Restrict stripping to ordinals that follow an instrument label or legal
suffix, so `Fund II` and `CIFC 2019-1` are untouched (entity_resolution already has the
numeric-suffix guard for the same reason).
Verify: R1 replay recovers the renumbered-ordinal MISSED cases; contested share rises
from 57% to 69% of rows, which is intended because those rows now go through R2's cost;
`test_bdc_identifier.py` cases for both forms.
Risk: must ship with R2. Alone, it turns exact-name uniqueness into contention with no
better cost to resolve it.

**R4. Issuer-name extraction upstream of entity clustering (global + per-CIK).**
Mechanism: population (a) rows have `issuer_name == bdc_investment_identifier` because
the no-dash, no-pipe branch of `_parse_bdc_identifier` returns the whole string. Then
`_extract_bdc_name` enters its blob branch only on three keywords, keeps everything up
to the first legal suffix, and `_fuzzy_cluster` scores the shared section+industry
boilerplate at >= 85.
Change, two layers:
- Parser (primary): in the no-dash branch use the per-CIK anchors
  (`data/overrides/identifier_anchors/<cik>.json`, SECDEBT / EQUITY / ASSETTYPE /
  RATE / MAT labels) plus `_INDUSTRY_LABELS` to split section | industry | company |
  instrument. This fixes `issuer_name` in unified holdings for matching, entity
  resolution and the frontend at once. BlackRock DLC, Trinity, Silver Point, Fidelity
  PCCF, Fidelity PCF and Bain PC already have anchors.
- Entity resolution (hardening): extend `_METADATA_KEYWORDS` with `instrument`,
  ` ref `, `type of investment`, `maturity `, `investment date`, `total coupon`;
  strip a leading industry phrase before the legal-suffix cut; in `_fuzzy_cluster`
  remove category/industry/instrument vocabulary before `token_sort_ratio` and refuse
  to merge names whose distinctive-token sets are disjoint; log clusters spanning many
  distinct extracted names to `entity_resolution_stats.csv`.
Verify: deterministic re-check of the 99 within_fund + cross_fund packets after rebuild
(target >= 90 split) *and* the 37 confirmed entity_merge_verify packets stay merged
(no over-splitting); `entity_stats` coverage in match_quality does not drop below the
94.3% baseline; new false-positive and true-positive tests in
`tests/test_entity_resolution.py`; export check because issuer names change on the
public site.
Risk: over-splitting real alias clusters (Cotiviti / Verscend). The confirmed-merge
regression set guards it.

**R5. GSBD dashed percent-prefix form (per-CIK parser rule).**
Mechanism: `United States - 200.15% 1st Lien/Senior Secured Debt - 188.54% AQ Helios
Buyer, Inc. (dba SurePoint)`; the percentages are pct-of-net-assets and change every
quarter, so exact-name never matches across quarters and every GSBD chain falls to
D_fuzzy, where Jaro-Winkler's prefix weighting makes all same-section names similar.
Change: in the dashed branch of `_parse_bdc_identifier`, when segment 0 is a geography
label, segment 1 starts with a percent and a category, and segment 2 starts with a
percent followed by text, issuer = segment 2 with the leading percent stripped, cut at
`_GS_KEYWORD_RE` (Industry / Interest Rate / Reference Rate / Maturity). Also check the
9 matching rows at 0001377936.
Verify: test with the AQ Helios string; `--unified` rebuild moves GSBD unparsed 165/563
to ~0; rerun matching and confirm GSBD edges migrate from D_fuzzy to B2/B1b; replay the
11 GSBD WRONG edges; semantic diff; export check.
Risk: low; one filer, one regex, gated by tests.

**R6. Row-level fixes through existing mechanisms (per-CIK).**
- MRI Software / Bullhorn: identifier `MRI Software LLC, First Lien Bullhorn, Inc.,
  First Lien Undrawn1` concatenates two positions in one fact. Inspect the cached XBRL
  context first; then either `data/overrides/row_corrections.csv` (field=issuer_name,
  with source evidence) or an aggregate-row override if it is a subtotal. Do not guess.
- Coding Solutions / Governmentjobs.com: re-check after R4; if still merged,
  `entity_overrides.json` needs a `splits` list (schema bump to v2, it only has
  `merges` and `canonical_overrides` today). Adding it before R4 papers over the
  global mechanism.
- Integrity Marketing Acquisition (debt) vs Group (equity): two legal entities, one
  sponsor deal. A borrower_group case; park until the grain decision.
- Ares / ASIF co-borrower labels (470 + 208 rows): no per-CIK merges. Recommended
  grain: `borrower_id` = first-named legal entity, full set kept in an additive
  `co_borrowers` column, business rollup in Phase 2.

**R7. Rubric, scoring and publication (measurement).**
- Verdict sub-codes in `validate_verdict.py` and the prompt in `build_packets.py`:
  `wrong_merge_kind` in {tranche_hop, different_borrower, co_borrower_group,
  concatenated_identifier, comparative_row}; `missed_link_kind` in {name_variant,
  renumbered_ordinal, co_borrower_header, unmatched_identical, other}. `score_gold.py`
  aggregates by kind. This session needed ~1,300 lines of rationale read by hand to
  get those counts.
- Drop `confidence` from `precision_by_tier.csv` / `summary.md` or publish a calibration
  check with it; median 0.99 with nothing below 0.90 is not a signal.
- Record the co-borrower grain decision in the spec and deterministically relabel the
  13 Ares entity_merge_verify packets under it before quoting that stratum.
- Finish mg3: resume the 60 packets after the Sep 7 quota reset (command in the mg3
  campaign entry), rescore, then the owner completes the 43-row `audit_slice.csv` with
  an `owner_verdict` column; the disagreement rate is the published caveat. Only then
  quote 0.92 [0.89, 0.94] outside the repo.
- Freeze mg3 as a regression fixture: R1's replay runs on every matcher change.

**Sequencing.** R1 -> (R2 + R3 together) -> R4 -> R5 -> R6 -> R7 alongside. R5 is
independent and can go first if a quick, visible win is wanted. R2/R3 are the largest
precision gain; R4 is the largest entity gain. Nothing here touches the v1 headline-FV
contract; all new columns are additive.

### Results of running R1, R5, R2+R3 (same day, 2026-09-06 afternoon)

Everything below ran from cached data with production artifacts untouched
(`private_markets_holdings.csv`, `position_matches.csv`, `position_id_edges.csv` still
carry the 2026-09-05 09:53 build). Scratch: `scratch/2026-09-06_mg3_replay/`.

**R1 replay harness** (`scripts/match_gold/replay_verdicts.py`, 5 tests): 760 pairs
(637 CONFIRMED, 69 WRONG, 32 MISSED with usable row ids, 22 UNCERTAIN; 9 proposed
links unusable because the packet carried no row_id).

| finding | WRONG (n=69) | CONFIRMED control (n=637) |
|---|---|---|
| begin row sits in a contested name group | 57 | 268 |
| same-name twin present in end quarter | 51 | 1 |
| twin with equal maturity | 47 | 1 |
| principal-led ordering would pick the twin | 44 | 1 |
| coexistence-veto rule fires | 27 | 1 |

MISSED pairs: 21 of the 24 adjacent-quarter pairs are ADMITTED by at least one tier
today (D 20, C 16, B1b 15, B2 13). They are not vetoed; they are lost in the 1:1
contest, and the supplementary pass refuses them because the name is not unique
(name_not_unique = 18 of 24). MISSED and WRONG are the same defect seen from both sides.

**R5 GSBD** (`data/overrides/bdc_xbrl_wrappers/0001572694.json`, `hierarchy_issuer_re`
now skips repeated `<label> - N% ` levels, dash / en-dash / U+FFFD): test
`test_gsbd_multilevel_pct_hierarchy_extracts_issuer` RED then GREEN. GSBD-only
matcher run, flag off, before vs after the fix:

| | edges | D_fuzzy | B2_exact_name | C | singleton share |
|---|---|---|---|---|---|
| unpatched | 2,659 | 2,045 | 593 | 6 | 39.2% |
| patched | 2,662 | 42 | 2,587 | 18 | 40.7% |

4,845 of 5,859 GSBD cohort rows change issuer_name. 11 of the 15 tier_random D_fuzzy
WRONG edges disappear from the fix alone. The production `--unified` rebuild was killed
by the OS memory watchdog (5 GB free with the owner's applications running) and is
still pending; the A/B below applied the identical regex in memory.

**R2+R3 prototype** (`pipeline/position_matching.py`, flag `contested_assignment`,
default off, 6 tests): ordinal-stripped `_name_key` for B2 and the supplementary
pass; contested 1:1 ordering principal log-ratio -> maturity rank -> legacy keys in
B1b, B2 and the supplementary pass; supplementary pass admits names up to
`MAX_NAME_MULTIPLICITY` instead of n = 1; coexistence veto on every chain edge (drop
the edge when a same-name, equal-maturity row with principal within 2% exists in the
end quarter and the chosen row is outside 2%). Hungarian routing and Tier A ordering
were NOT changed. Per-CIK A/B over the 54 gold CIKs (252,686 rows):

| | linked, flag off | linked, flag on |
|---|---|---|
| WRONG edges (69) | 58 | 25 |
| CONFIRMED edges (637) | 630 | 615 |
| MISSED pairs (32) | 0 | 23 |
| UNCERTAIN (22) | 18 | 17 |

- 33 wrong edges broken (B1b 11, SUPP 9, B2 5, A 4, C 4); 11 more were already gone
  from the GSBD fix; 0 new wrong edges.
- 16 confirmed edges lost (2.5%). Mechanisms, from the rows: revolver / DDTL draws
  where principal legitimately jumped 3x-23x while a sibling row sat closer (Ideal
  Image, Help/Systems, Eye Health, Coding Solutions); filers whose ordinals ARE stable
  and whose tranches differ by <2% principal (Capripack Debtco PLC "2" vs bare: the
  stripped key plus principal-first ordering crossed them); near-identical lots
  (Kaseya, Diligent). Fix candidates, not yet built: band the principal cost (about
  5% steps) so near-ties fall through to maturity and then the ordinal; weight
  principal less for REVOLVER / DDTL subtypes.
- 23 missed links recovered (all interior_singleton). The 9 not recovered: comma
  variants that name_key does not normalise (`Inc., First Lien 1` vs `Inc. First Lien
  1`; `Services, Inc., Emerald JV LP` vs without comma), a parenthetical `(fka ...)`,
  one name over the multiplicity cap, one GSBD row whose proposed partner is missing.
- 25 wrong edges remain: Tier A 4 (untouched), Kaseya 6 identical-principal lots
  (only cost differs), E 3, D_fuzzy 4 (Silver Point unparsed names, an Ares
  co-borrower revolver), and a few with no close twin.
- Aggregate over the 54 CIKs: edges 137,587 -> 163,164; singleton share 27.1% ->
  16.7%; C edges 815 -> 238 (absorbed by name-key B2). The +25.6K edges are almost
  all supplementary edges on formerly refused multi-tranche names. **Their precision
  is unmeasured**: the gold set validates only the sampled pairs. A `contested_supp`
  stratum must be adjudicated before the flag is promoted.

**Net on the gold sample:** error rate among adjudicated linked pairs 58/(58+630) =
8.4% -> 25/(25+615) = 3.9%, at the cost of 2.5% of confirmed edges.

**Not done today:** production `--unified` rebuild (memory), full pytest suite (the
matcher file 104/104 and the wrapper test file were run; see changelog), promotion of
the flag, human audit slice, the 60 quota-blocked packets.

### Production rebuild completed (2026-09-06 evening)

Memory freed later in the day, so the chain ran: staging test classes
(`TestPrepareBdc`, `TestGSPrivateCreditSqlPath`, `TestCrescentHierarchySqlPath`,
`TestPctPrefixSqlPath`, `TestBadIssuerNameInPrepareBdc` = 98 passed, 48 min;
`TestWrapperAuthoritativeStaging`, `TestWrapperNonPrivateMarketFiltering`,
`TestBuildUnifiedHoldings`, `TestSqlTiebreakDeterminism` = 39 passed, 20 min) ->
`rebuild_outputs.py --unified` (780,455 rows, 40 min) -> `--returns` (477,250 position
rows, 233 index rows, 8 min) -> `diff_outputs.py --semantic`. The
`contested_assignment` flag stayed OFF for the production rebuild; only the GSBD
wrapper fix is live.

Semantic diff: holdings 0 delta rows, matches 4, position_returns 1, index_returns 1
(DIRECT_LENDING 2023q3 constituents 18,344 -> 18,343), fund_financials 0. Row-level
check of `private_markets_holdings.csv` against the baseline by `row_id`: identical row
set (780,455 / 780,455, none only-in-one-side), zero fair_value or principal changes in
any CIK, issuer_name changed on 3,959 rows all at GSBD, chain membership changed on 3,272
rows all at GSBD. Production GSBD edge mix: D_fuzzy 2,045 -> 42, B2_exact_name 593 ->
2,585, E 0 -> 12 (baseline vs current `position_id_edges.csv`).

The remaining byte-level divergences are position_id relabelling (global ordinal
re-sequences when any chain changes) and two acceptance artifacts
(`quarter_acceptance*.{json,csv}`, `acceptance_reattestation_ledger.csv`) whose current
copies carry `generated_utc 2026-09-05T09:20Z` / target 2026-03-31 while the baseline
snapshot holds the 2025-12-31 versions from 2026-09-05T05:43Z. That drift predates
today's work (the files were not rewritten today) and is a baseline-snapshot bookkeeping
item, not a data change. The active baseline is NOT refreshed; GSBD issuer names on the
public export will change at the next `--export-frontend`.

### Overnight run 2026-09-06/07: matcher refinements v2, position_key pass, four wrapper fixes, flag-on packet set

Scope: everything runnable without a fleet. Scratch: `scratch/2026-09-06_mg3_replay/`
(A/B v2/v3 in `ab_percik_v{2,3}*`, flag-on run in `flag_on/`, wrapper probes in the
session scratchpad). All matcher work is test-first; every regex was probed against the
CIK's full cohort identifier set before it was written into the wrapper.

**1. Contested-assignment refinements (flag `contested_assignment`, still default OFF).**
`tests/test_position_matching.py::TestContestedRefinements` (5 tests RED then GREEN):

- `_name_key_sql` also drops commas, an `(fka ...)` / `(f/k/a ...)` / `(formerly ...)`
  parenthetical and collapses whitespace (mg3 MISSED: `Inc., First Lien 1` vs `Inc. First
  Lien 1`; `Corp (fka 1272775 B.C. LTD.)`; `Capripack Debtco PLC, 2` vs `... PLC`).
- 1:1 contest ordering (B1b, B2, supplementary): **banded principal** (5% log-band; 4x when
  either side is REVOLVER / DDTL) -> maturity rank -> rate -> **raw-name equality**
  (ordinal) -> **cost proximity** -> FV -> continuous principal
  (`CONTESTED_PA_BAND`, `CONTESTED_PA_BAND_REVOLVER`).
- **Leftover rounds** (`CONTESTED_MAX_ROUNDS` = 4): the B2 name-key contest and the
  supplementary pass re-run on still-unmatched rows so a sibling taking the nearest partner
  no longer orphans the other tranche. Extra pairs are labelled `B2_leftover_round` /
  `SUPP_B2_contested_leftover`; round-1 supplementary edges are
  `SUPP_B2_contested_name_key`. Contested supplementary edges also enforce instrument
  sub-type continuity.

**2. Supplementary position_key pass (flag-independent; changes production behaviour).**
`assign_position_ids` gained a third supplementary step after the name pass: rows whose
*strong* `position_key` is identical in adjacent quarters and unique per
cik/source/quarter on both sides are chained (FV ratio <= 5, report-date guard as for every
union). Edges are `SUPP_B1b_unique_position_key`, edge_type `supplementary_position_key`.
`tests/test_position_matching.py::TestSupplementaryPositionKeyPass` (3 tests). Why it
exists is in section 3; what it does on the gold set is in the A/B below.

Per-CIK A/B on the 54 gold CIKs (252,686 rows). "off" is production behaviour; v3 arms both
carry the key pass:

| | off (yesterday) | off + key pass | on v1 (yesterday) | on v2 | on v3 (= v2 + key pass) |
|---|---|---|---|---|---|
| WRONG edges still linked (69) | 58 | 58 | 25 | 29 | 29 |
| CONFIRMED edges kept (637) | 630 | 630 | 615 | 619 | 622 |
| MISSED pairs recovered (32) | 0 | 22 | 23 | 29 | 30 |
| new WRONG edges | - | 0 | 0 | 0 | 0 |
| singleton share | 27.1% | 18.7% | 16.7% | 16.1% | 14.9% |
| edges | 137,587 | 156,870 | 163,164 | 165,771 | 170,632 |

Reading: the key pass alone, under the production flag, recovers 22 of the 32 adjudicated
missed links, touches no WRONG or CONFIRMED verdict, and cuts the singleton share by a
third (19,283 new edges on these CIKs). v2 vs v1 by pair: +6 MISSED (Al Altius x2, CHG x2,
Everest x2, all name-key), +5 CONFIRMED regained (Capripack x2 name-key; MHE x2 and Coding
Solutions leftover rounds; Diligent raw-name), -2 CONFIRMED (Sonar equal-par lots, Orion
DDTL), +4 WRONG re-linked: three Ares `Diligent ... loan 4 -> loan 4` (identical 100K lots,
equal FV / cost / maturity; the gold set ruled 3 of 4 such links WRONG at Ares, whose
ordinals renumber -- economically neutral either way, same par / FV / cost / maturity) and
one WSHP FC supplementary leftover (par 33.8M -> 74.6M, now labelled for measurement). v3
additionally regains Streamland, Galway (revolver) and Eye Health (DDTL) via the key pass.
Error rate among adjudicated links: off 8.4%, v1 3.9%, v3 4.5% (4.0% excluding the
identical-lot Diligent links). v3 is the promotion candidate; the gate is still the
adjudication of its supplementary edges (section 4).

Remaining WRONG under v3 (29): Kaseya 6 (three lots with par within 0.2%, FV 4x apart; cost
did not separate them), Diligent 4 (identical lots), Tier A 4 (untouched), E 3, D_fuzzy 4
(Silver Point unparsed names -- fixed below -- plus an Ares co-borrower revolver and
Danforth amendment tranches), maturity-differing hops in B2 / B1b / SUPP 8. Remaining
MISSED (2): Olympus Terminals (name duplicated inside the identifier), one GSBD row whose
partner is outside the cohort slice.

**3. Four wrapper fixes for unparsed-identifier dialects (mg3 F1).** Probed against every
cohort identifier for the CIK, then test-first in `tests/test_unified_holdings.py::TestPrepareBdc`
(4 tests RED then GREEN; the existing Fidelity tests still pass):

| CIK | fund | defect | rows affected | probe: rows extracting a clean issuer |
|---|---|---|---|---|
| 0001646614 | Silver Point Specialty Lending | 2024+ form drops the `Non-Controlled/... Investments` prefix the regex required | 1,599 / 1,867 unparsed | 96.8% (198 issuers) |
| 0001834543 | BlackRock Direct Lending Corp | no staging block; `Debt Investments <Industry> <Company> [Instrument] <instr> Ref ...` | 3,020 / 3,028 unparsed | 99.3% (266) |
| 0001786108 | Trinity Capital | no staging block; `Portfolio Company <Section>- <Region> <Industry> <Company> Type of Investment ...`, venture-sector industry vocabulary | 5,008 / 5,065 unparsed | 99.1% (280) |
| 0001899996 | Fidelity Private Credit Co | from 2025-09-30 the filer inserts `Type` before the instrument; leaf-guard marker did not know it | 283 / 342 current-quarter names ended in ` Type`, so every chain broke at 2025Q3 | marker extended (`(?:type\s+)?`, `Maturity Date`, `Convertible Promissory Note`, `Class A LP Units`, `Series A Preferred Stock`) |

Trinity's 30 industry labels were derived from its own identifiers and kept inline in the
regex so they do not enter the global `MSD_INDUSTRY_LABELS` union.

**Why the key pass was needed (the finding of the night).** Flag OFF, per-CIK matcher run
on the cohort slice, unpatched vs patched issuer names, *before* the key pass:

| cik | rows | edges | D_fuzzy | B2_exact_name | singleton share |
|---|---|---|---|---|---|
| Silver Point | 1,867 | 1,053 -> 1,053 | 162 -> 8 | 46 -> 177 | 16.0% -> 22.3% |
| Trinity | 5,065 | 3,451 -> 1,684 | 368 -> 13 | 3 -> 166 | **7.9% -> 51.0%** |
| BlackRock DLC | 3,028 | 1,762 -> 1,719 | 263 -> 32 | 0 -> 165 | 20.5% -> 24.0% |

While issuer_name was the whole raw identifier, every tranche had a unique "name" and the
default supplementary pass (exact name, n = 1 per quarter) chained Trinity almost
completely. With the real company name, a company with several equipment-financing draws
fails n = 1 and is refused; the identity tiers pick up only part of the slack. The tranche
identity still lives in `position_key` (normalised full identifier: unique per row at
Trinity, 96-98% at the other two). The same runs *with* the key pass:

| cik | edges | D_fuzzy | B2_exact_name | singleton share |
|---|---|---|---|---|
| Silver Point | 1,085 -> 1,168 | 162 -> 8 | 46 -> 177 | 14.1% -> 13.2% |
| Trinity | 3,586 -> 3,527 | 368 -> 13 | 3 -> 166 | 6.9% -> 8.8% |
| BlackRock DLC | 1,997 -> 1,999 | 263 -> 32 | 0 -> 165 | 10.3% -> 11.5% |

The residual 1-2 point rise is where D_fuzzy edges on boilerplate-heavy strings used to be;
some of those were right, some were the WRONG_MERGE class mg3 found, and no gold exists
for BlackRock or Trinity chains yet -- the mg4 packets below sample them.

**4. Flag-on packet set for the fleet.** `scripts/match_gold/build_packets.py` gained
`--holdings-file`, `--edges-file`, `--strata`, `--tiers` and `--max-entities 0`, so a
candidate build persisted under `scratch/` can be scored without touching `data/output`
(`tests/test_match_gold_packets.py` + `test_match_gold_score.py` 19/19). A flag-ON v3 run
over all 76 cohort CIKs (the four wrapper regexes applied in memory, Fidelity's marker not
included) is at `scratch/2026-09-06_mg3_replay/flag_on/{holdings.csv,position_id_edges.csv}`:
282,937 rows, 191,072 edges, singleton share 14.8%; edge mix SUPP_B2_contested_name_key
84,599, B1b 63,335, B2 18,751, A 16,253, SUPP_B1b_unique_position_key 4,947, D 1,657,
SUPP_B2_contested_leftover 1,037, E 203, C 163, B2_leftover_round 127.

Built with `--batch-id mg4_contested --max-entities 0 --strata tier_random,interior_singleton
--tiers SUPP_B2_contested_name_key,SUPP_B2_contested_leftover,B2_leftover_round,SUPP_B1b_unique_position_key
--max-chains 40`: **271 packets** at `data/output/match_quality/gold/mg4_contested/`
(231 tier_random chains that contain at least one edge of the four new tiers, 40
interior_singleton under the flag; 257 with cached filings, 14 without). Because a chain
carries edges of several tiers, the per-edge verdicts will also re-score A / B1b / B2 edges
that sit in the same chains (A 79 packets, B1b 105, B2 29, SUPP_B1b_unique_position_key 51,
SUPP_B2_contested_name_key 175, SUPP_B2_contested_leftover 43, B2_leftover_round 40).
Same blinded prompt / verdict schema as mg3; dispatch with the existing match-gold worker
fleet once quota resets. Promotion rule proposed: promote the flag if the
`SUPP_B2_contested_name_key` edge precision is >= the mg3 `SUPP_B2_unique_exact_name`
precision and `SUPP_B2_contested_leftover` is >= 80%; otherwise disable leftover rounds
(`CONTESTED_MAX_ROUNDS = 1`) and re-score. The `SUPP_B1b_unique_position_key` verdicts also
measure the production key pass.

**5. Production.** Chain launched 21:53 local: staging gate (the 137 `TestPrepareBdc` /
wrapper / build test classes) -> `rebuild_outputs.py --unified` -> `--returns` ->
`diff_outputs.py --semantic` -> `pipeline.main --export-frontend`. Flag OFF in production;
what ships is the four wrapper fixes and the key pass. Result appended below when the chain finishes.

**Not done / owner decisions:** promote the flag (gate: the mg4 verdicts); Kaseya-style
equal-par lots (needs the filing's funded / unfunded split, not in XBRL); Tier A ordering;
baseline refresh; commit; full pytest suite.

**6. Leftover rounds tightened after a structural profile (v4, supersedes the mg4 build in
section 4).** Profile of every flag-on edge tier on the 76-CIK run (proxy only -- these
rates are partly selected by the ordering that produced the edges, so they show internal
consistency, not truth):

| tier | n | maturity equal (both known) | principal within 5% | within 50% | cost within 5% | median FV ratio |
|---|---|---|---|---|---|---|
| SUPP_B2_contested_name_key | 84,601 | 93.9% | 83.2% | 94.2% | 82.8% | 1.010 |
| B1b_position_key | 63,335 | 96.6% | 80.3% | 90.2% | 80.5% | 1.008 |
| B2_exact_name | 18,751 | 92.2% | 79.0% | 89.3% | 75.9% | 1.010 |
| A_within_filing | 16,253 | 95.0% | 78.2% | 89.7% | 79.8% | 1.012 |
| SUPP_B1b_unique_position_key | 5,042 | 94.9% | 76.5% | 89.3% | 77.1% | 1.019 |
| D_fuzzy | 1,658 | 89.2% | 67.0% | 80.3% | 68.6% | 1.015 |
| SUPP_B2_contested_leftover (v3) | 1,037 | 79.9% | 17.3% | 44.4% | 22.9% | 1.512 |
| B2_leftover_round (v3) | 127 | 74.8% | 17.2% | 24.2% | 21.0% | 1.995 |

The main new tier profiles like the adjudicated exact tiers; the two leftover tiers did
not, and a draw on an existing facility keeps its maturity. Leftover rounds (B2 and
supplementary, rounds >= 2) now require equal, known maturities
(`tests/test_position_matching.py::TestLeftoverRoundsRequireEqualMaturity`, 3 tests; file
120 passed). v4: leftover edges 1,164 -> 795 (100% maturity-equal by construction, principal
within 50% still only 23-44%, so they stay a separately labelled tier for the fleet to
score), total flag-on edges 190,835, singleton share 14.8%. Gold A/B v4 is identical to v3
(WRONG 29, CONFIRMED 622, MISSED 30): the tightening removed only unscored edges.
`mg4_contested` was rebuilt from the v4 run: **265 packets** (225 tier_random, 40
interior_singleton; 254 with cached filings), containing SUPP_B2_contested_name_key in 176
packets, SUPP_B1b_unique_position_key 47, SUPP_B2_contested_leftover 41, B2_leftover_round
40, plus A 80 / B1b 104 / B2 32 / D 12 / E 17 / C 14 edges in the same chains.

**7. First production rebuild found a dedup collapse; fixed and rebuilt.** The gate ran
clean (101 + 39 staging tests passed; the conftest output backstop tripped only because the
mg4 packet build wrote under `data/output` concurrently). The first `--unified` rebuild
(780,392 rows, 37 min) then showed 63 rows only in the baseline: 62 Trinity ($83.3M FV
across 2023Q2-2026Q1) and 1 BlackRock DLC. Mechanism, verified row by row: Trinity reports
several draws on one company as separate rows that differ only by `Investment Date`; the
new wrapper had reduced the instrument to `Secured Loan`, so pairs with identical FV / cost /
principal collapsed under the filing-level affiliation-axis and dimension-path dedup keys
(issuer + instrument + FV + cost + principal), which the raw identifier had kept apart.
Same class of effect as the Trinity chain collapse in section 3: the raw identifier was
carrying tranche identity that the parsed fields must now carry explicitly. Fix, test-first
(`test_trinity_instrument_keeps_investment_date_so_equal_draws_survive_dedup`): Trinity's
instrument keeps `Investment Date ...` and warrants get their `Series ...` tail via
`hierarchy_trailing_re`, which also restores the `preferred` keyword that 661 warrant rows
had lost (PREFERRED_EQUITY -> COMMON_EQUITY churn in the first rebuild). Other
classification moves in that rebuild were correct or immaterial: Trinity `Real Estate
Technology` companies leaving DIRECT_REAL_ESTATE (153 rows), Silver Point `TH Liquidating
Trust` interests COMMON_EQUITY -> UNCLASSIFIED ($5.8M, arguably more honest), Delos Living
warrants DIRECT_REAL_ESTATE -> COMMON_EQUITY. One Silver Point row (2024Q2 TH Liquidating
Trust, no `Instrument` keyword) now has a null issuer_name -- residual. The key pass
restructured chains broadly: 127,751 rows changed chain-mates versus the baseline, mostly
at unwrapped CIKs, which is the production-side counterpart of the +19K gold-CIK edges.
Second rebuild launched 00:20 with the Trinity instrument fix; result below.

**8. Production result (rebuild 2, 2026-09-07 00:07-01:04).** `--unified` 780,452 rows
(38 min) -> `--returns` 475,049 position rows / 233 index rows -> `diff_outputs.py --semantic`
-> `--export-frontend` (28 JSON files). Row-level check against the baseline by `row_id`:

| check | result |
|---|---|
| rows only in baseline / only in current | 3 / 0 (two Trinity NextCar lots suffixed `One`, one BlackRock Streamland lot suffixed `Two`; $1.6M FV; the duplicate-lot suffix left the parsed fields, so identical-FV siblings collapse -- residual, see below) |
| fair_value / principal changes | 0 / 1 row (Silver Point principal) |
| cohort 2026-03-31 FV, all classes | 562.012B -> 562.012B |
| issuer_name changed | 14,495 rows: Trinity 5,059, GSBD 3,959, BlackRock DLC 3,023, Silver Point 1,562, Fidelity PCCF 892 |
| index_classification changed | 226 rows: Trinity `Real Estate Technology` companies out of DIRECT_REAL_ESTATE (162, into preferred / common equity), 43 Trinity warrant rows PREFERRED -> COMMON where the series is common stock, Silver Point TH Liquidating Trust 9 rows -> UNCLASSIFIED ($5.8M), 2 Trinity + 2 Fidelity DIRECT_LENDING -> UNCLASSIFIED |
| rows whose chain-mates changed | 127,679 (the key pass; largest at unwrapped CIKs 0001476765 8,820, 0001913724 6,450, BCRED 4,939) |
| production edges | 467,691 -> 505,772 (`SUPP_B1b_unique_position_key` 39,869 new; D_fuzzy 14,329 -> 11,572; B2 47,695 -> 50,155; SUPP name 119,456 -> 118,540; A 40,612 -> 40,000) |
| BDC singleton share (all history) | 27.6% -> 20.4% |
| GSBD edge mix | D_fuzzy 2,045 -> 42, B2 593 -> 2,585 |

Semantic diff: holdings 7 delta rows (row count -3, class FV moves above), matches 6,
position_returns 6, index_returns 5, fund_financials 0. The acceptance artifacts still
differ from the baseline for the pre-existing reason noted on 2026-09-06 (baseline holds
the 2025-12-31 quarter_acceptance). Baseline NOT refreshed; nothing committed. Residuals
to carry: the 3 duplicate-lot rows (keep the `One` / `Two` suffix in the instrument for
Trinity / BlackRock DLC -- Trinity's single `hierarchy_trailing_re` slot is taken by
`Series`), the null-issuer Silver Point 2024Q2 row, and the frontend now shows the new
names for five funds (28 JSON files rewritten, uncommitted).

## 2026-09-07 - Match-gold batch mg4_contested: promotion gate for the contested-assignment flag

**Question:** are the ~25K edges the `contested_assignment` flag adds precise enough to
ship? mg3 A/B on old gold showed WRONG 58->29 but MISSED 0->30, with the new edges
uncovered.

**Batch:** 265 packets built from the flag-on v4 scratch run (225 tier_random on
flag-on edges, 40 interior_singleton), dispatched 12:43-20:12 from an elevated shell
(MaxParallel 2, MaxAttempts 3): 265/265 OK, 0 invalid, 0 missing. Analysis
`scripts/match_gold/chain_experiments/mg4_analysis.py` (sub-codes via name_key /
entity_id agreement as in E1).

### Per-tier precision, tier_random, UNCERTAIN excluded

| tier | n | precision | wrong | of which tranche hop |
|---|---|---|---|---|
| E_entity_fingerprint | 18 | 1.00 | 0 | 0 |
| B1b_position_key | 238 | 0.99 | 2 | 2 |
| **SUPP_B2_contested_name_key** | **499** | **0.98** | 10 | 10 |
| D_fuzzy | 13 | 0.92 | 1 | 0 (1 borrower) |
| A_within_filing | 109 | 0.91 | 10 | 10 |
| SUPP_B1b_unique_position_key | 54 | 0.89 | 6 | 6 |
| B2_exact_name | 44 | 0.84 | 7 | 7 |
| C_normalized_name | 16 | 0.75 | 4 | 4 |
| **SUPP_B2_contested_leftover** | **41** | **0.71** | 12 | 12 |
| **B2_leftover_round** | **39** | **0.56** | 17 | 17 |
| ALL | 1071 | 0.936 | 69 | 68 |

Excluding the two leftover tiers: 991 edges, 40 wrong, **0.960**. Tranche-hop rate on
the flag-on build 6.3% (mg3 production 6.1%), wrong-borrower 0.1%.

### Findings

1. **The contested name-key tier is the best name-based tier measured so far:** 0.98
   on 499 edges, above B2_exact_name (0.84 here, 0.94 in mg3) and SUPP_B2 (0.95 in mg3).
   Its 10 wrong edges are all tranche hops and all separable: 2 maturity, 4 spread, 5
   principal >25% -- i.e. the E5 veto (maturity with amendment escape) plus exact spread
   as a cost would remove most of them. Wrongs are spread across 8 CIKs (0001834543 3/8,
   the rest 1 each).
2. **The leftover rounds fail the gate.** 0.56 and 0.71. Their wrong edges are pairs
   with principal off by orders of magnitude (4,600 vs 68,747,000; 10,804 vs
   10,227,000 -- thousands-vs-units scale defects in the source) and spread mismatches
   (9.0 vs 9.5, 5.0 vs 4.75). The leftover pass pairs whatever the greedy pass left,
   after the equal-maturity guard, and maturity alone is not enough (0 of 29 leftover
   wrongs differ on maturity). They add 80 of the 1,071 flag-on edges and 29 of the 69
   wrongs.
3. **Recall on the flag-on build:** interior_singleton stratum 20 MISSED_LINK / 12
   CONFIRMED-singleton / 8 insufficient = 62.5% of interior singletons still misses
   (mg3 production: 76%, 26/34). Directionally better, n too small to claim more; mg5
   (100 random interior singletons on production) is running for the real estimate.

### Decision

Promote the contested name-key contest (SUPP_B2_contested_name_key) and keep the
leftover rounds OFF (`CONTESTED_MAX_ROUNDS = 0` or a separate switch). Then apply the
E5/E10 rules inside the contest: maturity veto with amendment escape first, exact
spread and cost as tie-breaks before the principal band, rank pairing inside
static-identical blocks. Re-run `replay_verdicts.py` on mg3 + mg4 (both are pair
verdicts and replayable) before the production rebuild, and gate the rebuild on
`diff_outputs.py --semantic` plus twin-build.

**Caveats:** single adjudicator; the flag-on edges were sampled from a scratch build so
16 of 1,138 edges no longer join to production rows; leftover-tier n is 39-41.

### Addendum 2026-09-07 evening: promotion implemented, gold A/B of the new code

Code (`pipeline/position_matching.py`): `CONTESTED_ASSIGNMENT_DEFAULT = True` wired
into `scripts/rebuild_outputs.py --returns` and `pipeline.main --returns`; leftover
rounds off (`CONTESTED_LEFTOVER_ROUNDS = 0`, re-enable per call via
`contested_leftover_rounds`); maturity veto with amendment escape
(`_maturity_veto_sql`, principal within 2% and spread within 1bp) on the contested B2
contest and the supplementary contested pass. Tests: `TestContestedPromotion` (8) +
one existing leftover test now opts in explicitly; `tests/test_position_matching.py` +
`tests/test_replay_verdicts.py` 128 passed.

Per-CIK gold A/B (`scripts/match_gold/ab_gold_percik.py`, 59 CIKs, 1,866 pairs from
mg3 + mg4_contested; A = flag off = prior production, B = new code flag on):

| batch | kind | n | linked A | linked B |
|---|---|---|---|---|
| mg3 (production-sampled) | WRONG | 67 | 52 | **24** |
| mg3 | CONFIRMED | 676 | 669 | 660 |
| mg3 | MISSED | 40 | 27 | **36** |
| mg4 (flag-on-sampled) | WRONG | 69 | 33 | 49 |
| mg4 | CONFIRMED | 986 | 826 | 962 |
| mg4 | MISSED | 28 | 0 | 0 |

On the unbiased mg3 view: precision proxy 0.928 -> 0.965, recall proxy unchanged (9
confirmed lost, 9 missed recovered). mg4's B column is favoured by construction (its
edges were sampled from a flag-on build); its 49 still-linked WRONG include 12
leftover-labelled pairs that another path now links and 16 `A_within_filing` hops
the change does not touch. Net over all 1,866 pairs: WRONG linked 85 -> 73, CONFIRMED
1,495 -> 1,622, MISSED recovered 27 -> 36. Consistent with the 2026-09-06 v4 A/B
(WRONG 58 -> 29) and slightly better on WRONG with the maturity veto.
