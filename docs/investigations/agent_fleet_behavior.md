# Agent Fleet Behavior

Behavioral analyses of the B1 adjudication and B2 investigation fleets: verdict
quality, calibration, grounding, escalation quality, process discipline.

## 2026-09-02 - B1/B2 q1p3 fleet behavior analysis (verdicts, calibration, escalations, process)

**Question:** What can be learned from agent behavior in the q1p3_20260831 pass --
verdict calibration, grounding quality, ambiguity anatomy, rule-authoring style,
escalation quality, process discipline? (Two read-only analysis agents; scripts
kept in scratch/2026-09-02_b1_behavior_analysis/ and _b2_behavior_analysis/.)

### B1 (743 verdicts, batch q1p3b1_20260831 + r1-r7 retries; 676 rollout logs)

- Verdicts: 347 FA (46.7%) / 302 real (40.6%) / 94 ambiguous (12.7%). Routing
  deterministic and clean.
- **Confidence is effectively binary**: decided verdicts span only 0.88-0.99
  (real mean 0.980, FA 0.975; modal 0.99). No gradation within decided. Worse,
  ambiguous/source_unavailable is semantically inverted across workers: 26x
  conf=0.0 vs 7x conf=0.99/1.0 for the SAME unusable-environment condition.
  The confidence field needs a rubric or should be dropped from downstream use.
- **Grounding discipline is excellent**: 301/302 real_errors carry culprit
  citations; 86% carry observed+anchor values; 10-rationale sample all specific
  (quoted rows, indices, arithmetic); 1 citation spot-checked against the raw
  cached filing and confirmed. No confabulation found in sample.
- **Ambiguity anatomy**: of 60 source_checked, 28 (47%) are the row_key mapping
  gap (internal row_key unmappable to a filing row; one row_key fanned into 3
  ambiguous verdicts). Fixed 2026-09-02 (row context on issue rows). Of 34
  source_unavailable, **15 (44%) are environment failures (1326 logon race)
  that leaked into final verdicts** -- the retry mechanism only catches MISSING
  verdicts, not env-poisoned ones. Re-dispatching those 15 would cut the
  ambiguous pool ~16%.
- **Per-rule FA profiles (demotion candidates)**: X06 12/12 decided FA,
  F16 5/5, agentA_subtotal_candidate 6/6, E07 90.8%, C107 89.1% (negative cost
  = legitimate unfunded-commitment columns), pct identity 85.7%, B02 83.9%
  (distinct same-terms lots != duplicates). **Keepers**: agentA_maturity_vs_xbrl
  19/19 real (year truncation), agentA_spread_vs_xbrl 95%, C206 11/11, FX02 5/5.
  Cross-pass stable (q4t4 vs q1p3) except **nonaccrual_flag flipped 0.11 -> 0.72
  FA** -- investigate rule or cohort change.
- **Process**: median 10 commands/verdict; 100% contract adherence proxies
  (contract read, roam, totals, validator in all 676 rollouts); zero forbidden
  commands; zero writes outside the verdict path. Heavy rollouts correlate with
  hard bundles, not flailing. Retried workers were MORE decisive than the
  population (59% FA / 35% real / 6% amb), not lower quality.
- anchor_used is free-text chaos (90+ spellings) -- normalize to an enum.

### B2 (134 promoted + 79 staged rules, 41 escalations, 60 gate JSONs, 4 traces)

- Rule types: row_exclusion 54%, row_add 30%. **Predicates anchor on
  bdc_dimensions_raw (63) >> issuer_name (21) >> row_id (only 3)** -- workers
  organically prefer dimension strings; 51 exact-string predicates are fragile
  to filer re-formatting. Confidence compressed high (median 0.96) but
  escalations appropriately lower (0.76-0.87).
- Impact: median $66M/rule, max $13.38B (1504619 issuer-axis duplicate,
  best-in-class evidence). **measured_impact units are inconsistent (fractions
  vs dollars)** -- audit hazard for programmatic checks.
- **Convergence**: 51/94 CIK loops hit max-5 iterations, dominantly the
  loop-controller defect (no success path for zero-rule investigations; fixed
  2026-09-02 as PASS_NOOP). Four escalations explicitly diagnosed the harness
  ("the remaining defect is loop state rather than holdings data").
- **Gate caught delete-to-balance live**: b3_gate.1838126 FAIL "value_sum pushed
  BELOW anchor... -29,630,000". Promote refused 1715933/1772704 (no residual
  improvement). One FV-neutral invalid rule (1869453 position_key dedup) passed
  a residual-already-zero gate -- closed by the promote() audit guard.
- **Escalations (41 files, ~25 findings)**: missing-position/dropped-before-
  staging 18 (8 CIKs, uniformly exact-arithmetic evidence), anchor-plausibility
  5, missing-anchor 5, stale-loop 4, rounding-tolerance 3, overbroad-prior-rule
  3. ~40% are within-CIK iteration re-statements (dedupe at intake). The 4
  anchor-band escalations (1918712/2031750/1902649/1954360) are correlated
  instrument readings with INDEPENDENT evidence and divergent stances -- genuine
  convergence, not copy-paste; the cross-CIK pattern was recognized at the
  operator layer, not by workers.
- **Honest-refusal signature**: escalators treat the anchor as a SIGNAL
  (exact-arithmetic bridge, then decline: "that is numerical balancing, not a
  data-quality mechanism"); gate-refused workers treated it as a TARGET.
- **Evidence-thin flags for human spot-audit**: 18 rules >= $100M with only 2
  evidence quotes; worst 1544206/exclude_credit_fund_lookthrough ($1.98B on 2
  query quotes, no filing citation, residual improved not reconciled). Also
  1646614/02 dedup on (report_date, fair_value) equality alone.
- **Provenance mutability**: retries overwrite per-CIK dirs and batch gate JSONs
  (1715933's batch gate reads PASS/anchor 657M while its manifest shows anchor
  1,239M residual -18.25% from a later run) -- 5th instance of the overwrite
  defect family; run-stamp all artifacts like the manifests.

## 2026-09-02 - Escalation deep-dive: all 41 files read; they collapse to 7 system defects, not vocabulary gaps

**Question:** What do the B2 escalations actually ask for, deduped and quantified?

41 files -> ~25 distinct findings -> **7 root causes**. ZERO are "data errors the
vocabulary cannot express" in the intended sense; every one points at a
surrounding layer:

1. **Staging drops cash-equivalent/short-term/undimensioned schedule rows**
   (6 CIKs, 17 files, ~$886M): 1899996 State Street $26.9M, 1916608 First
   American $5.3M, 1920453 State Street+Fidelity $196.4M, 1950976 Dreyfus
   $36.9M, 1715933 cash+Treasury $582.2M, 1930087 equity schedule $84.7M.
   All present AFTER "Total Portfolio Investments" in the printed schedule;
   workers cite exact filing table/row + Level-1 hierarchy corroboration and
   independently converge on the same proposed applier (filing-coordinates
   row_add). ONE extraction fix (ingest undimensioned short-term/cash sections
   into staging) heals the class; the vocab extension is the fallback, not the
   fix. 2008748 is the extreme case: staging contains ONLY aggregates, zero
   position rows ($1.4B).
2. **Anchor plausibility band lifetime-median FPs on ramp-up funds** (4 CIKs,
   5 files, ~$28B FV): 1918712/2031750/1902649/1954360; holdings==companyfacts
   exactly; band rejects on lifetime median. Workers propose QoQ-continuity
   band + fund_financials FV/cost double-corroboration.
3. **Missing/unreliable anchors needing adjudication** (4 CIKs, 5 files):
   1377936 (no independent candidate), 1495584 (0.21x likely mis-extracted),
   1743415 (companyfacts series captures a subtotal), 1930679 (+ snapshot
   circularity: tier NONE -> quarter absent from trial snapshots -> gate
   cannot evaluate). The anchor-adjudicator lane already solves these
   (1772704 precedent) but escalations do not route to it.
4. **Loop no-success-path for clean quarters** (4 CIKs): 1633858, 1849894,
   1911066, 2049733 -- each burned 5 iterations then diagnosed the harness.
   FIXED 2026-09-02 (PASS_NOOP).
5. **Gate exactness vs engine band** (3 CIKs, $1K-$7K): 1487918/2052153/
   2037804 -- CODE-VERIFIED: gate_correction anchor_undershoot_tol defaults
   0.0 while the engine band is 0.5%; a valid dedup leaving -0.0002% fails as
   delete-to-balance.
6. **Evidence starvation** (1975736, 3 files, conf 0.76-0.87 -- honest): no
   filing bundle in cache + staging lacks table-role/section/hierarchy lineage
   to separate look-through collateral from real ABS/ABF positions; worker
   explicitly refused numerical balancing.
7. **Conservation-eligibility scope mismatch** (1905824, 2 files, $38.8M):
   FHLB discount notes classified CASH and excluded from the conservation set
   while the filer's printed Total Investments includes them; asks for
   reclassify vocab or per-CIK eligibility scope.

Behavioral notes: 18/41 files are within-CIK iteration re-statements (loop
re-authors the same escalation under a new filename -- needs idempotent
naming); escalation confidences are the best-calibrated in the system;
category field (anchor/vocab/other) exists but nothing consumes it.

### Cross-cutting lessons

1. The grounding invariant (citation-or-anchor-proof, enforced by the screen)
   demonstrably shaped behavior -- near-total citation compliance, no observed
   confabulation. Deterministic validation of agent OUTPUT works.
2. Confidence-as-a-number failed in both fleets (compressed, inconsistent
   semantics). The informative signals are verdict category, escalation, and
   evidence quality.
3. Infra state leaks into semantic space: env-poisoned "ambiguous" verdicts and
   conf=1.0 escalation requests. Keep infrastructure failure OUT of the verdict
   channel (screen should reject env-failure rationales and route to retry).
4. Best escalations diagnosed the HARNESS, not the data (loop state, band FP,
   vocabulary gaps) -- agents are effective instrumentation for the system
   itself; the operator layer is where cross-CIK patterns get recognized.
