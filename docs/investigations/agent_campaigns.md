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
