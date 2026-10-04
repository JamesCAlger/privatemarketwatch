# Implementation, experiments and rollout

Status: execution active in an isolated worktree; see the [run log](05_run_log.md).
The stages below remain the acceptance plan, not a claim they all passed.
Success means more
confirmed data defects found at a fixed investigation budget, with controlled
incorrect clearances and an evidence trail. Model agreement alone is insufficient.

## Scope

Keep the initial implementation to C107/X08 and BDC cached filings. Use explicit
CIK/quarter/flag manifests, never an unrestricted universe scan or queue dispatch.

Proposed limits: at most 16 distinct BDCs cumulatively in this programme, counting
the nine previously tested filers. Confirm that this cap remains strictly below
the canonical v1 cohort size. The next holdout tranche is at most four previously
untested funds, two periods per fund where available, 40 natural flags and 100 Jev
calls. Unfilled strata are reported; do not silently expand scope to fill them.
These are experiment limits, not production coverage commitments.

Current data, wrappers and source artifacts remain unchanged during the pilot.
Other vehicle types, HTML-only and N-PORT support require separate validation
before becoming eligible; they do not expand the BDC-only public product.

The current layout inventory profiles 67 natural flags from 11 funds and 26
filing/period combinations. It records 25 observed header/grid shapes, including
within-table cell-merge variants; these are not 25 independently validated filer
templates. Twelve flags have no retrieved candidates and remain explicitly
uncovered. Sampled shape-set differences across periods are review triggers, not
proof of template changes. Identical shapes do not certify unchanged note scope,
units, ownership or candidate recall. Validate those evidence mechanisms too.

## Work packages and exit evidence

| Stage | Work | Exit evidence |
|---|---|---|
| 0. Freeze the evaluation contract | Preserve current examples; define case IDs, labels, routing configuration, risk budgets, sampling and untouched splits | Versioned manifest; no reused development filer represented as untouched |
| 1. Repair bundle correctness | Strengthen units, visible identity, periods, headers/continuations and notes, with explicit rejection | Focused regression tests and independently reviewed source evidence |
| 2. Implement routing in shadow mode | Build bounded runner, receipts, candidate-clearance projection, escalation reasons and accounting | Every input flag accounted for; no B1 work suppressed or ledger verdict overwritten |
| 3. Run blind calibration and holdout | Measure natural cases across filers/quarters/layouts; choose thresholds on calibration only | Coverage, unsafe clearances, uncertainty and workload report on frozen holdout |
| 4. Shadow a normal B1 cycle | Compare the proposed routing with independent B1 investigation on the same frozen inputs | Incremental defects, audit disagreement resolution and measured B1 effort |
| 5. Enable a narrow canary | Eligible rule/layout modes only, with B1 escalations and audits of clearances | Predeclared risk/economic criteria pass; replay, invalidation and rollback verified |
| 6. Add weak-rule families | Rank by useful error discovery and investigation burden; add one evidence contract at a time | Each new family passes its own tests/calibration/holdout before clearance |

Stages 0-4 grant no production clearance. Stage 5 remains disabled when risk
budgets, economic targets or calibration evidence are missing. Document numeric
acceptance targets before inspecting holdout outcomes; do not select them to make
observed results pass. More evidence may be required while staying within the fund
cap. A small pilot can establish feasibility without establishing a safe error rate.

## Stage 1 priorities

Implement general mechanisms supported by source evidence, then measure coverage.

1. **Conflicting units/scales:** reproduce TCW's displayed-dollar versus inline
   scale conflict. Reject unsupported normalisation; use independently supported
   displayed units only where the mechanism is established.
2. **Identity contradictions:** reproduce Ares's visible Class C versus XBRL Class
   A conflict. The check must fail even when both monetary fields match.
3. **Source periods:** reproduce Onex's current/comparative schedules. Use explicit
   period evidence and detect unresolved continuation headings.
4. **Common geometry and headers:** handle documented issuer-header variants,
   split sign/parenthesis cells and continuation rows without merging tranches.
5. **Notes and output units:** attach required notes to the correct schedule and
   retain genuine unknown output currencies as unresolved.

Do not resolve a source conflict by quietly trusting whichever representation
makes the current output agree. Keep unfamiliar layouts unresolved. Record each
layout/config exception and its maintenance cost; a large collection of bespoke
filer fixes can eliminate the expected operational benefit.

## Proposed code boundaries

| Responsibility | Existing or proposed home |
|---|---|
| Cache-only retrieval and rule-specific evidence | Extend existing `pipeline/jev_bundles.py` and `scripts/build_jev_bundles.py` |
| Evidence eligibility, threshold routing and member accounting | Proposed `pipeline/jev_screening.py`, separate from model transport |
| Bounded API execution and immutable run artifacts | Proposed `scripts/run_jev_screening.py`; reuse tested experiment handling where suitable |
| Rule/routing versions, threshold and bypass configuration | Proposed schema-validated configuration under `data/reference/`; default disabled |
| B1 queue projection | Adapter to `pipeline/review_queue.py` and `scripts/agent_b/run_review.py`; preserve group membership and locks |
| Regression coverage | Existing `tests/test_jev_bundles.py` plus proposed focused routing/receipt tests |

These proposed files do not yet exist. Avoid a broad workflow-engine refactor for
this pilot. Reuse the repository's evidence/verdict patterns while keeping Jev
screening receipts distinct from accepted B1 verdicts.

Pilot evidence needs a durable home before it authorises routing changes. Preserve
small manifests, audited references, request/response hashes and source pointers
under a dedicated evaluation location such as `data/pilot/jev_screening/<run_id>/`.
Document retention/access; session scratch alone is disposable and insufficient
as the only audit record. Never store API secrets in the corpus or receipts.

## Reference labels and test splits

- Freeze the exact output snapshot, flags and cached filing bytes. Historical
  labels with missing disputed fields or unresolved row joins stay unscored.
- Independently review source identity, date, scope and amounts before scoring.
  Keep `real_error`, `false_alarm`, `ambiguous` and `unscorable` distinct. Ambiguity
  cleared by Jev is unsafe even if no numeric defect has yet been established.
- Reuse existing experiments as development/regression evidence. Previously tested
  filers, including Carlyle and Ares from the older reserved split, are consumed.
- Hold out whole new filers and later periods. Include observed layout changes,
  parent/JV scopes, debt/equity/commitment structures, units and continuation rows.
  Record source-type coverage separately; do not infer one type from another.
- Include natural errors from multiple filers and mechanisms. Keep synthetic
  defects as labelled controls with separate results, never as natural-error recall.
- During calibration/holdout, B1 investigates without seeing Jev's verdict, and can
  access the cached source independently of Jev's bundle. Resolve disagreements
  against source evidence; neither model is automatically the ground truth.
- Freeze prompts, builder, thresholds, manifests and references before holdout calls.
  Fixes prompted by failures consume that holdout and require fresh validation.

## Comparisons that establish Jev's contribution

Score three routing policies on the same frozen cases and independently reviewed
references: the existing B1 workflow, deterministic bundle checks alone, and those
same checks plus Jev with B1 escalation. Use the same evidence requirements and
clearance-risk target. Count bundle development, maintenance and clearance audits
in the workload comparison.

If deterministic source matching and arithmetic can safely resolve a rule, prefer
that simpler route. Jev should earn its place through additional safe coverage or
better prioritisation. Initially measure coverage and effort on C107/X08; test the
larger claim of additional defect discovery only when new weak rules are included
in a later bounded experiment at the same B1 budget.

## Metrics and denominators

Publish a complete funnel: selected flags -> exact joins -> builder-ready ->
independently valid evidence -> Jev calls -> candidate clearances -> B1 routes ->
audited outcomes. Report distinct flags, positions, filers, filing periods and API
calls separately. Reversed options and repeated requests are not independent cases.

| Metric | Definition/use |
|---|---|
| Valid bundle coverage | Independently correct and complete automatic bundles / all selected eligible flags; manual repair excluded |
| False readiness | Builder-ready packets with a substantive evidence defect / independently audited ready packets |
| Unsafe clearance rate | Source-confirmed errors or unresolved identity/evidence conflicts in candidate clearances / audited candidate clearances |
| Escalation capture | Audited genuine errors routed to B1 / all audited genuine errors in the sample |
| Safe clearance yield | Verified false alarms eligible for automated clearance / all selected flags |
| Incremental discovery | Additional confirmed error mechanisms/affected positions found through newly screened weak rules at the same B1 budget |
| Operational burden | B1 investigations and active review time, bundle preparation/maintenance time, retries, API spend and backlog age |
| Drift | Changes in valid coverage, failure reasons, confidence and audited clearance quality by rule/filer/period/layout |

Show both count-based and materiality-based results. For materiality, deduplicate
positions affected by multiple rules within a quarter and report the valuation
basis; flagged FV is exposure, not an estimate of economic loss. Do not combine
different quarters into a current portfolio total or alter official FV numerators.

Report confidence bands and uncertainty, accounting for clustered examples within
a filing. Four loans with the same scale defect are four affected positions and
one observed mechanism. Samples enriched for errors cannot establish production
prevalence without recording selection probabilities and suitable weighting.

## Audit and acceptance policy

During development and the small shadow tranche, independently inspect every
would-be clearance. For a later canary, predeclare a random audit sample of
clearances, stratified by rule, filer/layout, period, confidence and materiality.
Include the highest-confidence band; auditing only low-confidence cases cannot
measure unsafe automated clearance. Retain sampling probabilities and outcomes.

Mandatory conditions before any canary:

- No unresolved known unsafe-clearance mechanism in an enabled rule/layout mode.
- Independent bundle checks pass; no source-identity/unit/period conflict can be
  overridden by confidence or agreement between agents.
- The predeclared clearance-risk bound is supported by the holdout and audit
  sample, not merely by observing zero mistakes in a handful of cases.
- Useful workload reduction remains after B1 clearance audits and bundle upkeep,
  and strong/high-error investigations have not been displaced by the added queue.
- Changed inputs invalidate decisions; every flag/group member is accounted for;
  provider failures remain visible; rollback can requeue affected clearances.
- Existing data-quality gates and correction verification remain intact.

Run Jev after an eligible frozen build; run B1 on escalations and scheduled audits
within existing operator cycles. Add weak rules only as investigation capacity and
measured benefit allow. A discovered unsafe clearance disables the affected mode,
triggers retrospective review and prevents expansion until the mechanism is fixed
and independently retested. Agreement alone cannot close that incident.

## Verification expected during implementation

Run focused bundle/routing tests first. Cover false readiness, a false-positive
counterexample, exact identity conflicts, unit disagreements, changed periods,
partial group coverage, stale cache reuse, threshold boundaries, malformed/API
failures and replay/rollback. Tests must use fixtures or temporary directories.

Follow repository test and artifact-protection rules. In this isolated session,
the owner's no-production-write instruction prevents the standard semantic-diff
command because it writes a production report. Use the runtime write guard and
bounded read-only metadata comparison, and report that semantic parity was not
tested. If a proposed check exceeds the owner's bounded scope, record the
limitation and do not claim it passed. A documentation-only change requires no
pytest, rebuild, export or network calls.

## Replay integrity implementation

The isolated replay reader now checks exact declared flag membership, packet filenames, rule identity, builder/holdings versions, readiness/reasons and aggregate readiness counts. Newly written enriched replays include a full packet fingerprint in every summary entry; the reader validates it when declared. Rebuilds use the same checked parent loader.

Historical summaries remain unchanged. Those without packet fingerprints receive identity/status/version checks but cannot establish full content immutability by themselves. Frozen model-request manifests and prepared review-input bindings provide separate content hashes; do not imply that adding a new hash retrospectively proves an older packet was unchanged.

Seven negative fixtures failed before the repair; all nine focused replay tests now pass, including two compatible summary formats. The original/consumed holdout pair and current 100-call ledger still validate with unchanged counts. A targeted reader/consumer regression set passes 22 tests. No bundle-builder change, source reparse or model call was required.

## Audit sample planning: illustrative bounds, not acceptance targets

For independent, randomly sampled candidate clearances with zero unsafe outcomes, the exact one-sided 95% binomial upper bound is `1 - 0.05^(1/n)`. The corresponding zero-error sample sizes are:

| Illustrative upper unsafe-clearance rate | Independent audited clearances needed |
|---|---:|
| 5% | 59 |
| 2% | 149 |
| 1% | 299 |
| 0.5% | 598 |
| 0.1% | 2,995 |

Calculated as `ceil(log(0.05) / log(1 - target_rate))`. These numbers assume zero unsafe outcomes, independent observations and representative random sampling. Multiple rows sharing one filing/layout defect violate the independence assumption. A stratified or clustered design needs its own analysis; repeated requests, synthetic siblings and consumed development cases cannot inflate this denominator. No risk target is selected by this table.

The current pilot has zero independently audited candidate clearances, so none of these bounds can be claimed from the 42 correct natural labels. Error-enriched controls instead test escalation mechanisms; they do not estimate traffic prevalence. A future experiment should preserve both a representative clearance audit sample and a separately reported natural-error challenge set, within the approved fund scope.

Full B1 source review of every candidate is appropriate for calibration but cannot demonstrate the intended recurring workload saving. Any later sampled-audit operating mode also needs independently validated automatic evidence checks, supported-layout limits, drift detection and requeue capability. The current router requires per-packet independent review and does not implement such a production mode. Do not silently replace that requirement with a model confidence threshold or a reusable human checkmark.
