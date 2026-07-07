# Weak-Rule Remediation Architecture (Design for Review)

**Status:** DRAFT for review, rev 2 — not implemented. Branch context: `ensemble-fp-experiment`.
**Date:** 2026-07-07 (rev 2 same day, after cross-checking the draft against the
implementations in `scripts/agent_investigate/`, `scripts/agent_b2/`, `pipeline/agent_rule.py`,
and `scripts/shadow_conservation_engine.py`)
**Inputs:** ens2 calibration results (934 adjudications, `data/output/ensemble/ens2/`),
the B1->B2->anchor->B2 conservation-remediation chain, AGENTS.md agentic data-quality
principles.

---

## 1. Problem

The ens2 experiment produced a calibrated per-rule false-positive table for the weak
review-lane rules and rejected the co-firing ensemble hypothesis. One-shot deterministic
scope fixes were applied where a separable predicate existed (FX02/FX03, X01, X07, C103,
PCT01). What remains is an architecture question: how do weak-rule flags — tens of
thousands of firings, FP rates from ~0% to ~80% — get converted into fixes and a
publishable quality statement, without (a) routing every flag through an expensive agent,
(b) publishing fields with a known material error rate, or (c) building a validation
layer the fixing agent can game?

This document specifies that architecture. It generalizes the existing fv_conservation
chain (B1 adjudicator -> B2 investigator -> anchor adjudicator -> B3 held-out gate)
into a multi-lane remediation system driven by mechanism clustering, per-rule-family
gates, and acceptance sampling.

## 2. Design principles (inherited, non-negotiable)

1. **Agents are subroutines inside a deterministic pipeline.** Agents author config
   (rules, overrides, citations); only the deterministic rebuild produces data.
2. **No agent grades its own homework.** Every fix is validated by a check that is
   independent of the author: a deterministic comparison against source, or an
   independently sampled adjudication.
3. **Escalation is a first-class outcome.** "No mechanism found after bounded attempts,
   hypotheses documented, rows quarantined" is a valid terminal state.
4. **Unverified flagged data is never published as clean.** Queue position affects
   coverage, never correctness of what is shown.

## 3. Roles and the handoff contract

### 3.1 Existing agents (roles unchanged; modules named)

"B2" is overloaded in this repo — two modules carry the name with different contracts.
This spec names both and keeps both:

- **B1 (adjudicator)** — `scripts/agent_b/run_review.py`. real_error vs false_alarm
  per flag group. Reliable on real/false; its mechanism guess is a hint, never a
  contract.
- **B2 (investigator)** — `scripts/agent_investigate/run_investigation.py`.
  Investigates one CIK-quarter target with read-only data-query and filing-evidence
  tools; authors auditable rules (row_exclusion / dedup / value_rescale /
  value_expression / row_add) scoped per CIK; self-verifies non-no-op; escalates with
  category anchor|vocab|other. Where this document says "B2" it means this agent.
- **Bounded-template lane (the original `scripts/agent_b2/`)** —
  `run_remediation.py` + `dispatch_preflight.py`. The first implementation: B1 verdict
  -> (cik, fix_class) packet -> worker fills a bounded template (the fix_class is
  binding; the worker does not re-decide the mechanism) -> B3. It works well in its
  scope: strong-rule conservation targets where the mechanism is already certain and
  false positives are absent. Its durable role is the low-cost executor when the
  mechanism is known in advance — which makes it the natural applier for
  mechanism-library instantiations (section 6.4): a library hit arrives with the
  mechanism decided, so it needs a template fill plus a sample verify, not an
  investigation.
- **Anchor Adjudicator** — `scripts/agent_anchor/run_anchor.py`. Finds the filer's
  printed grand total when companyfacts FV is an incomplete subtotal; verified by
  deterministic balance-sheet closure.
- **B3 (held-out gate)** — `pipeline/agent_rule.gate_rules` over
  `pipeline/agent_b_held_out.gate_correction`. Un-gameable held-out conservation gate:
  target cleared, no new flags in any quarter, FV-at-risk non-increasing, anchor
  validation, over-addition and delete-to-balance guards.

### 3.2 The worklist is the contract, not B1

B2 consumes a target queue. B1 is one producer among several. Each queue row carries a
`realness_basis` so B2's prompt and the audit trail know how confident the routing was:

| Producer            | realness_basis     | Example                                    |
|---------------------|--------------------|--------------------------------------------|
| B1 verdicts         | `b1_real_error`    | fv_conservation lane (existing `discover`) |
| Calibrated priors   | `calibrated_prior` | low-FP weak rules routed direct            |
| Promoted overrides  | `promoted_override`| canary stage-3 re-fix (existing precedent) |
| Anchor screens      | `anchor_screen`    | incomplete_anchor_screen (existing)        |
| Printed-cell screens| `gate_screen`      | C107/X08 rows whose quote-at-location      |
|                     |                    | mismatches the extracted value (section 4) |
| Mechanism library   | `library_match`    | cross-CIK reuse hits (new, section 6)      |

The handoff stays deliberately thin — (cik, target_quarter, rule context, review_ids) —
because B1's row-level and mechanism-level detail is unreliable ("real_error" often
means 1 real row of 10; B2 must scope rows itself regardless).

Worklist schema — since the worklist IS the contract, it is written down. The current
implementation carries only (cik, target_quarter, n_verdicts, review_ids) and must be
extended:

| column          | meaning                                                          |
|-----------------|------------------------------------------------------------------|
| cik             | target filer                                                     |
| target_quarter  | report_date under investigation                                  |
| rule_name       | rule family that produced the target (fv_conservation, C107, ..) |
| realness_basis  | producer class (table above)                                     |
| review_ids      | supporting adjudication/citation ids (may be empty for           |
|                 | calibrated_prior and library_match rows)                         |
| priority_score  | section 7 ranking (per-CIK flagged-FV share x rule prior)        |

### 3.3 Required B2 change: a `no_defect` exit

B2 currently has no false-alarm exit ("a no-op is a failure, not an answer"), which is
correct only when realness was established upstream. Before any `calibrated_prior`
targets are dispatched, B2 needs a first-class `no_defect` terminal state with the same
evidence bar as a fix: cite the filing location that confirms the extracted value.

`no_defect` verification and the printed-cell gate (section 4) are the same build
artifact. A no_defect verdict IS a citation whose quote-at-location matches the
extracted value — so once the printed-cell checker exists, every no_defect verdict is
verified deterministically at 100%; the citation is the verdict input, not an agent
assertion. Sampled spot-checks (10-20%) are only a bridge until the primitive ships;
open question 1 dissolves after that.

Relatedly: `scripts/agent_b2/reviewed_workflow.py` exists specifically to prevent the
operator from dispatching remediation directly from raw residual rows — everything must
pass through B1 today. The `calibrated_prior` lane consciously relaxes that guard. That
is consistent with this spec's logic (no_defect is the prerequisite that makes it safe),
but the relaxation must be recorded as an explicit decision when the lane is enabled,
not left to drift.

## 4. Per-rule-family gates

Row-local data cannot discriminate real from false for the residual high-FP rules
(proven by the C107 retro-test: sign/keyword cuts lose adjudicated reals faster than
false alarms). Every gate therefore has the same skeleton:

> **independent anchor + deterministic comparison; the agent only locates, never judges.**

The agent's output is a citation — file, table, row anchor, quoted cell text. A
deterministic checker re-reads that location and computes the verdict. The verdict is
computed from the quote-at-location, not asserted, which is what makes it un-gameable.

Three anchor classes, mapped to the current residual rules:

| Gate class | Anchor | Rules | Verdict logic |
|---|---|---|---|
| **Printed-cell reconciliation** | the cell as printed in the cached SOI HTML | C107 (cost<0), X08 (FV/cost<5%), future rate-scale checks | Printed parenthetical `(1,234)` matching extracted negative -> false alarm (source-faithful). Printed dash/blank extracted as negative -> real. For X08: printed FV and cost matching extracted -> genuine impairment (FA); mismatch -> scale error, and the fix is gated on new-extracted == printed. |
| **Structured source attributes** | iXBRL unit/scale refs, N-PORT fields | FX01 (non-USD principal on DIRECT_LENDING) | Fully deterministic; likely needs no agent. USD alias (FX02/FX03 precedent) -> scope fix; genuine EUR loan -> FA. |
| **Aggregate closure** | companyfacts totals + balance-sheet closure | PP01 (subtotal candidates) | No new gate. Route into the existing B2 conservation loop: excluding a real subtotal moves the sum toward the anchor; excluding a real position breaks it. |

The printed-cell gate is the productized form of the shared cached-filing search
primitive already identified as a need (full-filing-search-adjudication). Build it once;
it serves C107, X08, rate-scale checks, the acceptance-sampling step (section 6.3), and
deterministic no_defect verification (section 3.3).

Citation schema: extend the existing B1 `culprit_citations` shape rather than invent a
third format — `{source_file, table_index, row_index, column, quoted_text}`. The first
three fields already flow through `dispatch_preflight`; the `column` field and the
normalization rules (quoted cell text -> comparable number: strip footnote markers,
thousands separators, dollar-split cells, parenthetical sign) are the new parts the
deterministic checker needs.

## 5. Routing and B1's durable role

- **Low-FP rules** (nonaccrual_flag ~0%, A07 10%, X02 16%, C04 17%): direct to B2 with
  `calibrated_prior` basis. B1 adds little when the prior already says "probably real".
- **Deterministically gated rules** (FX01): the gate replaces adjudication entirely.
- **Residual high-FP rules** (C107 80%, X08 55%, PP01 53%, FX01 49%): behind their gate
  (section 4). Until a rule's gate exists, it stays behind B1.
- **B1 as sampled calibrator, never inline triage.** Inline B1 does not scale (sandbox
  fleet is ~2-wide serial; weak rules fire in the tens of thousands) and priors decay:
  applying fixes removes reals from the firing pool, so surviving firings drift FA-heavy
  and last pass's real-rate overstates this pass's. Re-sample a rule (30-50 flags for a
  usable Wilson CI) when its firing count or flagged-FV share moves materially since its
  last calibration — triggered, not calendar; sampled, never census. B1's independence
  is what makes the calibration trustworthy: the rule-family gates must not grade their
  own calibration.

## 6. Mechanism clustering

Extraction errors are not i.i.d. — they are generated by per-filer template quirks
meeting the extractor. B2's cost scales with distinct mechanisms, not flags. Clusters
are **dispatch hypotheses, not ground truth**; acceptance sampling is the sole authority
on cluster validity.

### 6.1 Fingerprint first (deterministic)

Signature = `(rule_id, cik)`, optionally split by source engine and filing-format
family. Refinement features when a CIK shows mixed mechanisms: dimension path,
sign/magnitude pattern (power-of-10 offset vs peers), null-pattern of adjacent columns,
10-K vs 10-Q, HTML template id. This mirrors industry failure-bucketing practice
(crash-report fingerprinting a la Windows Error Reporting / Sentry): deterministic
hierarchical fingerprints first, similarity clustering only for the residual.

### 6.2 The authored rule defines the true cluster

B2 investigates one representative per cluster (ranked per section 7). The promoted
rule's `predicate_sql` IS the mechanism boundary — rows it matches are the true
cluster; the fingerprint was only routing. This is a variant of cluster-based active
learning (cf. Raha/Baran error-detection literature: label representatives, propagate
within clusters).

### 6.3 Acceptance sampling validates the cluster

After the mass fix, draw a random sample of N rows from the rule's matched set and run
the printed-cell gate on each. Sample passes (Wilson bound above threshold) -> cluster
promoted. Sample fails -> the one-mechanism assumption was wrong: split on whatever
feature separates passing from failing sampled rows, re-dispatch the remainder. The
sample is drawn independently of the fix, preserving principle 2.

### 6.4 Cross-CIK mechanism library

Every promoted rule becomes a library entry (mechanism description + signature +
predicate template). Deterministically screen other CIKs for the same signature; where
it matches, instantiate a per-CIK rule and verify by sample — no new investigation.
This is how small CIKs get fixed below any investigation budget. An agent MAY propose
semantic matches between mechanism descriptions across CIKs (recall); the sample gate
decides (precision). No agent validates cluster quality directly — that would be an
internal-only anomaly score, i.e. a weak check.

### 6.5 Statistical refinement (optional, only if under-splitting observed)

If `(rule_id, cik)` under-splits in practice, use embeddings of flag context +
HDBSCAN — density-based, no k, and noise points fall out as singletons for individual
dispatch rather than contaminating a mechanism group. k-means is explicitly rejected:
the features are categorical/structural, not Euclidean, and k is unknown.

## 7. Materiality: rank, don't cut

- **Priority score per cluster:** flagged FV as a share of THAT CIK's total FV
  (per-CIK relative materiality), optionally weighted by the rule's calibrated
  real-rate prior. A $60M fund with 30% of its FV flagged outranks a $5B fund with
  0.2% flagged — systematic small-fund defects surface early.
- **No materiality cutoff exists.** FV ordering schedules the queue; it never
  terminates it. The queue is persistent and residual-driven; low priority means
  later, never never.
- **Only three terminal states short of "fixed":**
  1. *Sub-rounding residual* — defined by measurement precision, not cost. NOTE: the
     implementation currently carries TWO numbers (the worker prompt says 0.5%; the
     driver's `loop_decision` stop and the conservation flag threshold are both 1.0%).
     Reviewer decision: pin ONE terminal tolerance and reconcile driver + prompt to it.
     Recommendation: terminal state = the flag threshold — a target is done when its
     flag can no longer fire — with the prompt's 0.5% language aligned to it.
  2. *No defect* — the printed-cell check confirms the extracted value matches the
     filing (section 3.3); the flag was a false alarm, recorded with its citation.
  3. *Escalated* — B2 found no mechanism after bounded attempts; hypotheses documented,
     rows quarantined with the escalation file as audit trail.
- **The publish gate protects correctness while the queue drains:** flagged-unverified
  fields are tiered or withheld (quality tiers, section 10.2), so a CIK waiting in the
  queue can never surface wrong data — only reduced coverage.
- **Field-level, not row-level, suppression:** a suspect `cost` is nulled/tiered
  without touching the position's verified `fair_value`. Error rates apply per-field
  on the flagged subset, not to the datapoint.

## 8. Lane ordering (topological: rows -> values -> fields -> derived)

1. **Population + FV scale** — the existing B1->B2->anchor->B2 conservation lane.
   Row existence and value scale are upstream of everything: leaked subtotals generate
   weak-rule false firings; missing investees corrupt denominators; mis-scaled FV
   directly changes ratio rules (X07/X08 are FV/cost ratios). PP01 folds in here.
2. **Re-run the deterministic battery on the corrected holdings.** Mandatory, not an
   optimization: flags on rows a conservation fix deletes are wasted work; rules
   authored against the pre-fix row set can mis-target; row_add fixes can introduce
   new firings.
3. **Field-faithfulness rules** (C107, X08, rate scale) via printed-cell gates, which
   presuppose the row corresponds to a real printed position (established by stage 1).
4. **Derived identities last** (pct_of_net_assets vs FV/net-assets identity, portfolio
   yield vs fund income closure) — numerator and denominator must be settled first.

### 8.1 The prerequisite in detail: gap 1 — wiring promoted config into production

**What it is.** Three families of validated fixes each have a store, an applier, and a
promotion step — and none has a production consumer (verified 2026-07-07):

1. **Bounded-template correction leaves.** `promote_passes` copies gate-PASS leaves to
   `data/overrides/agent_b2_corrections/`; nothing in `pipeline/` reads it.
2. **Investigator rules.** `promote` copies gate-PASS rules to
   `data/overrides/agent_investigate_rules/`; no consumer (the directory does not
   exist yet).
3. **Anchor overrides.** `data/overrides/agent_anchor/` is git-tracked but read only by
   the investigation driver's own gate and prompt. The shadow conservation engine that
   produces `conservation_gate_results.csv` — the source of the review queue and every
   residual measurement — never sees the adjudicated grand totals.

The only place fixes apply today is `scripts/rebuild_unified_cik_trial.py`, which is by
its own docstring "an iteration artifact, NOT a production rebuild." Consequences: the
public dataset never improves no matter how many fixes pass B3; every pass re-measures
the same dirty data (and the `-Fresh` runbooks reset even the per-target working
state); quarters with adjudicated anchors keep regenerating already-resolved targets;
and stage-3 rules fire on rows that promoted stage-1 exclusions would delete — exactly
the mis-targeting step 2 above exists to prevent.

**The fix: give each store a production consumer at the layer where its fix
semantically applies.** The pattern already exists — `data/overrides/bdc_xbrl_wrappers/`
is a git-tracked, agent-augmented config store that production staging actually reads.

- **Layer A — wrapper patches (subtotal_filter):** promote the PATCHED WRAPPER into
  `data/overrides/bdc_xbrl_wrappers/` (with provenance fields), not the correction
  leaf into a dead directory. Zero new pipeline code; staging picks it up on the next
  rebuild. Cheapest slice, and it covers the fix class with the largest adjudicated FV
  mass.
- **Layer B — raw-staging corrections (comparative_period_filter):** load and apply
  inside `build_unified_holdings()` before the BDC CTEs, so `pipeline/main.py`,
  `rebuild_outputs.py`, and the trial script share one code path — trial/production
  parity by construction, not discipline.
- **Layer C — post-unified agent rules (investigator rules + post-staging fix
  classes):** apply at the tail of `build_unified_holdings()`, after classification,
  before the output write. The predicates reference unified-frame columns
  (`bdc_dimensions_raw`, `asset_category`) so they cannot run earlier; applying before
  the write means validation, position matching, position ids, and frontend export all
  see corrected data with no forked views. Applying instead in `validate_holdings` or
  export is rejected: it forks the dataset.
- **Layer D — anchor overrides into the shadow conservation engine:** add a
  `verified_override` anchor kind at top priority in the engine's priority-ordered
  anchor list (a clean insertion point — the engine already COALESCEs anchors in
  priority order). Residuals are then measured against adjudicated grand totals and
  resolved quarters stop flagging.

**Application requirements (non-negotiable):**

- Deterministic order and scoping: per CIK, ordered by (stage, rule_id), scoped to the
  rule's source + cik — a predicate authored against one filer's dimension strings must
  not touch N-PORT rows or another CIK. One DuckDB pass over the frame; no per-rule
  Python loops (the >10K-row contract).
- A rebuild-time audit artifact (per-rule matched-row counts and FV deltas, every
  rebuild), diffed against the rule's authoring-time `measured_impact`. A promoted rule
  that suddenly matches 0 rows or 10x the rows means upstream extraction shifted under
  it: WARN and route to re-validation (this feeds the section 5 recalibration
  triggers). Never apply silently.
- Test isolation: the override loader must be injectable (explicit dir parameter
  defaulting to the config path) so fixture-based tests pass an empty store; otherwise
  real promoted rules leak into fixtures that use real CIKs. Focused tests for
  ordering, no-op detection, and cross-CIK scoping.

**Governance is already built — exercise it:** commit the override wave (one commit) ->
`rebuild_outputs.py --unified` -> `diff_outputs.py --semantic` -> battery re-run (a
four-curves data point) -> baseline refresh recording the override-store commit hash ->
frontend export. The semantic diff doubles as the acceptance check for the wiring
itself: on the first wired rebuild, every changed row must be attributable to a
specific promoted rule or anchor override — anything else moving fails the wiring.

**Operational changes:** retire `-Fresh` as the runbook default (a new pass starts FROM
the promoted store; `-Fresh` remains only for re-investigating a target whose promoted
fix was reverted). Before the first wave, inventory the un-promoted gate-PASS rules
under `data/output/agent_investigate/*/rules/` (the overnight 41-CIK run) — that is the
first wave's size and the coverage of the parity check below.

**Sequencing:** Layer D first (smallest change; stops the queue regenerating resolved
targets, and re-measurement means nothing without it). Then Layer A (no pipeline code,
largest FV mass). Then Layers B/C with the audit artifact and a per-CIK parity check —
for each gate-PASS CIK, the trial's corrected output must equal the production
rebuild's output for that CIK before the wave commits. Then the first full battery pass
on corrected holdings: the first real four-curves data point, and the point where
sections 5-7 become buildable rather than theoretical.

## 9. Iteration, convergence, and the four curves

Per pass:
- Deterministic battery: re-runs on everything (cheap).
- B2: dispatched only on residual/new clusters.
- B1: triggered recalibration sampling only (section 5).

**Four curves per pass, per lane** (also per-CIK where meaningful):
1. firing count
2. cluster count
3. flagged-FV share (per-CIK and cohort)
4. sampled real-rate (Wilson CI)

**Rule retirement:** when a fresh calibration sample shows a rule's real-rate at ~0
within CI, its remaining firings are irreducible false alarms — scope-fix or demote to
INFO/TRACK_ONLY (the C104/C404 precedent). A lane is done when every rule is retired
or its residual clusters are all escalated-and-quarantined.

The four curves are the public data-quality contract: they show error mass shrinking,
measured by an adjudicator (B1 sampling) independent of the fixer (B2 rules).

## 10. Staging, promotion, and versioned rollback

### 10.1 Isolation (already structural)

Agents never write the dataset. B2 writes rule files; trial applications land under
`data/output/agent_investigate/`; promoted config lives in `data/overrides/` (git-
tracked). Production `unified_holdings` is produced only by the deterministic rebuild
from cached inputs + the override store. Existing guardrails: pytest write-block on
production outputs, baseline snapshot governance, `scripts/diff_outputs.py --semantic`.

### 10.2 Promotion path

```
override store (append-only, git-tracked)
  -> staged rebuild from cached inputs
  -> semantic diff vs active baseline
  -> validation gates + four-curves check
  -> baseline refresh (prior baseline preserved)
  -> frontend export with quality tiers
```

A baseline refresh is approved when the four curves moved in the right direction and no
gate regressed. The same numbers flow to the frontend as the quality contract.

### 10.3 Versioning and rollback (proposed protocol)

Current state: `data/overrides/` is git-tracked (anchor overrides are committed), so
rollback-by-git already exists. `data/overrides/agent_investigate_rules/` does not yet
exist in the tracked store — its promotion protocol is defined here:

1. **One commit per promotion wave.** All rules/overrides promoted from a single
   validated batch land in one commit whose message names the batch id and gate
   results. `git log data/overrides/` is the audit trail.
2. **Provenance inside every rule file:** batch id, authoring agent + session,
   gate verdict, acceptance-sample stats (n, pass rate, Wilson bound), timestamp,
   evidence citations. A rule is self-describing; rollback decisions never require
   external context. Authorship split: the authoring agent writes only evidence,
   rationale, confidence, and measured_impact; the gate verdict and acceptance-sample
   stats are STAMPED BY THE PROMOTION MACHINERY at promote time — an agent never
   asserts its own validation results (principle 2). This is a schema change to
   `validate_rule`'s required fields.
3. **Rollback = revert config + rebuild.** Data is never rolled back directly. Revert
   the offending commit (surgical: one wave; or one file within it), re-run the staged
   rebuild, semantic-diff, refresh baseline. Because the rebuild is deterministic from
   cached inputs, config state fully determines data state.
4. **Supersede, don't silently delete.** A rule found wrong after promotion is retired
   by a commit that removes/replaces it with a note referencing the evidence; the git
   history preserves what was live when.
5. **Baseline pairing.** Each baseline snapshot records the override-store commit hash
   it was built from, so any published dataset maps to an exact config state.
6. **Cross-wave composition and re-validation.** A CIK's rules from multiple waves
   compose; they apply in deterministic order (stage, then rule_id) scoped to
   source + cik. A rule's `measured_impact` was recorded against the baseline it was
   authored on, and later waves change that baseline — so the rebuild-time audit
   (section 8.1) diffs matched-row counts against authoring-time values on every
   rebuild; material drift WARNs and routes the rule to re-validation rather than
   silent application.

## 11. Open questions for review

1. `no_defect` spot-check sampling rate for B2 (section 3.3) — 10-20%? Bridge-only:
   once the printed-cell primitive ships, no_defect verdicts verify deterministically
   at 100% and this question dissolves.
2. Acceptance-sample size N and pass threshold per cluster (section 6.3). Grounding
   arithmetic: an ALL-PASS sample needs n>=25 (one-sided 95% Wilson) or n>=35
   (two-sided) to clear a 90% lower bound; a single failure at those n drops below it
   (-> split the cluster or enlarge the sample). Larger n for high-FV clusters?
3. Which field-faithfulness gates to build first — proposal: printed-cell primitive,
   then C107 (highest FP mass), then X08.
4. Recalibration trigger thresholds (firing count / flagged-FV share delta) for B1
   sampling (section 5).
5. Where the mechanism library lives — proposal: `data/overrides/mechanism_library/`
   with the same provenance schema as rules.
6. Whether the four curves publish per-lane only or also per-CIK on the frontend.
7. The terminal tolerance (section 7): pin 0.5% vs 1.0% and reconcile the driver's
   `loop_decision` stop, the conservation flag threshold, and the worker prompt to the
   one number.
8. Drift thresholds for the rebuild-time audit (section 8.1 / 10.3.6): how much
   matched-row-count movement vs authoring-time `measured_impact` triggers
   re-validation?

## 12. Explicitly rejected alternatives

- **B1.5 cluster-validation agent** — an agent verdict on cluster coherence is an
  internal-only anomaly score (weak check) and adds a gameable layer; acceptance
  sampling already validates clusters un-gameably.
- **k-means clustering** — features are categorical/structural, k unknown; wrong tool.
- **Inline B1 triage on all weak-rule flags** — does not scale (2-wide serial fleet vs
  tens of thousands of firings) and adds little at either FP extreme.
- **Materiality cutoff** — creates the "small CIK never investigated" failure mode;
  replaced by rank-don't-cut + publish-gate (section 7).
- **Snorkel-style co-firing accuracy estimation** — ens2 measured co-firing directly
  and found it uninformative; adjudicated labels are strictly better.

## 13. Worked example: one C107 cluster end to end

Illustrative numbers. The mechanism is modeled on the ens2 C103 known-loss case (a
footnote-marker mis-parse inside a legitimate-negatives group), transplanted to C107.

1. **Battery (pass N, on gap-1-wired holdings).** C107 (cost < 0) fires on 41 rows of
   cik 0001234567 ("Example Capital BDC"), 2025-09-30. Flagged FV $310M of the CIK's
   $900M total -> per-CIK flagged share 34% -> near the top of the queue (section 7)
   despite the fund's small absolute size.
2. **Fingerprint (6.1).** Signature (C107, 0001234567). Refinement features split
   nothing: all 41 rows share one trait — the raw investment identifier ends in a
   footnote marker like "(4)".
3. **Printed-cell gate (4).** An agent locates each flagged cell in the cached SOI HTML
   and returns citations; the deterministic checker re-reads each quote-at-location:
   - 33 rows: printed cost is `12,500(4)` — a positive number with a footnote marker;
     extracted cost is -12,500. Mismatch -> REAL (the parser read the trailing marker
     as a negative parenthetical).
   - 8 rows: printed cost is `(3,750)` — a true parenthetical (unfunded commitment);
     extracted -3,750 matches -> `no_defect`, recorded with the citation as evidence.
     These rows stay published; nothing routes to B2 for them.
   The intra-CIK 33/8 split is exactly why row-local cuts failed the C107 retro-test:
   no holdings-column predicate separates the groups. The printed cell does.
4. **Dispatch (3.2).** One worklist row: (0001234567, 2025-09-30, rule_name=C107,
   realness_basis=gate_screen, review_ids=the 33 citations). B2 investigates, confirms
   the mechanism boundary, and authors ONE rule:

   ```json
   {"cik": "1234567", "rule_id": "examplecap-footnote-cost-signflip",
    "rule_type": "value_rescale", "action": "rescale",
    "field": "cost", "factor": -1.0,
    "predicate_sql": "cost < 0 AND regexp_matches(bdc_investment_identifier, '\\(\\d\\)\\s*$')",
    "scope": {"quarters": ["all"]},
    "evidence": [{"source": "filing", "quote": "12,500(4)  [t3/r117, column=cost]"}],
    "rationale": "Parser treats the trailing footnote marker as a negative parenthetical; printed costs are positive.",
    "measured_impact": {"2025-09-30": {"rows": 33, "fv": 310000000}},
    "confidence": 0.95}
   ```

   The predicate is the mechanism boundary (6.2): across all quarters it matches 214
   rows — THAT set, not the fingerprint, is the cluster. It matches rows C107 never
   flagged in quarters the battery has not yet run on; that is the point.
5. **Trial + gates.** Trial application flips 214 cost signs. Per-row printed-cell
   re-check on changed rows: corrected 12,500 == printed `12,500(4)` — the fix is
   gated on new-extracted == printed (section 4). Held-out gate: no new flags in any
   quarter, FV-at-risk non-increasing. C107 firings for the CIK drop 41 -> 8; the 8
   survivors are the confirmed legitimate negatives.
6. **Acceptance sample (6.3).** n=25 rows drawn at random from the 214-row matched
   set, independent of authoring. 25/25 pass the printed-cell check -> one-sided 95%
   Wilson lower bound ~0.90 -> cluster promoted. (Had even 1 failed, the bound drops
   below 0.90: split on whatever separates the failing row, re-dispatch the split.)
7. **Library (6.4).** Entry: mechanism "trailing footnote marker parsed as negative
   parenthetical", signature (C107 + the identifier regex), predicate template. The
   deterministic screen finds 3 more CIKs whose C107 firings match the signature.
   Because a library hit arrives with the mechanism pre-decided, instantiation routes
   through the BOUNDED-TEMPLATE lane (3.1), not a fresh investigation: per-CIK rule
   instantiated, n=25 sample each. Two pass -> promoted below any investigation
   budget. One fails 13/25 -> not the same mechanism -> falls back to the investigator
   queue as its own target.
8. **Promotion wave (8.1, 10).** The promotion machinery stamps gate verdict + sample
   stats into the three rule files; one commit (batch id + gate results in the
   message) -> `rebuild_outputs.py --unified` applies them at the Layer-C hook ->
   `diff_outputs.py --semantic` shows exactly the matched rows' cost changed and
   nothing else -> battery re-run: C107 firing count and flagged-FV share drop, and
   the fresh sampled real-rate updates the calibration table (the four curves move) ->
   baseline refresh records the override-store commit hash -> frontend export moves
   the three CIKs' `cost` field from "under review" to "verified" tier.
9. **Pass N+1.** The rebuild audit shows the rule matched 214 rows again — no drift,
   no WARN. The 8 legitimate-negative rows still fire C107: the irreducible residual.
   When a fresh calibration sample shows the surviving C107 pool's real-rate at ~0
   within CI, C107's residual is scope-fixed (exclude printed-parenthetical-confirmed
   rows) or demoted to INFO/TRACK_ONLY (section 9), and the lane retires.
