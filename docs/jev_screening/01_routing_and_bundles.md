# Routing and evidence contract

Status: target contract with an isolated shadow implementation in
`.claude/worktrees/jev-screening-pilot`. Production routing is not implemented.
The pilot covers C107/X08 and an opt-in C104 probe; see the [run log](05_run_log.md)
for current gaps, frozen results and tests. Independent source-audit requirements
are deliberately not satisfied by builder readiness or model confidence alone.

## Routing precedence

Apply these rules in order. A later confidence score cannot override an earlier
evidence or risk failure.

| Condition | Proposed outcome |
|---|---|
| Strong/source-blocking check or rule configured as known high true-error | Existing investigation lane/B1; bypass Jev |
| Rule/source type has no validated bundle contract | B1: unsupported evidence family |
| Exact row cannot be resolved, source missing, evidence incomplete, conflicting units/identity/period/scope, or size limit exceeded | B1 with explicit bundle failure reasons |
| Provider error, malformed response, unsupported model version, missing confidence or unrecognised source choice | B1; retain the failed attempt |
| Jev returns real_error or ambiguous | B1 regardless of confidence |
| Decision confidence below the configured cutoff, or source confidence below its separately calibrated cutoff | B1 |
| Selected row contradicts visible identity, period, scope or required comparisons | B1 regardless of confidence |
| High-confidence false_alarm, supported rule and all independent checks pass | Candidate automated clearance for this flag/version only |

For the initial shadow simulation, use decision confidence >= 0.75. Evaluate a
separate source-confidence cutoff; 0.75 can be the initial trial value for that
score too, but the two scores are not interchangeable. Missing source confidence
cannot count as passing when Jev performs source selection. A deterministic,
independently verified source match may be evaluated as a separate routing mode.

Both thresholds and rule eligibility are versioned configuration. Choose them
using development/calibration data, then freeze them before holdout scoring.
Do not interpret 0.75 as an established 75% probability of correctness.

High-error-rate routing needs audited counts, sample size, uncertainty, dates and
the relevant rule/filer/layout scope. Historical B1 labels are a starting point
for investigation, not sufficient proof of the rate. Unknown rates do not qualify
a rule for automatic clearance. Any broader materiality bypass remains explicit
configuration rather than an undocumented judgement in the runner.

## What a clearance means

A clearance states that one named weak-rule suspicion is source-supported for one
position in one frozen build. Other flags on that position remain independent.
Positive corrections and confirmed errors still enter the existing B1/B2 and
independent verification process. Jev does not author a correction or promote it.

Do not overwrite B1 verdict files with Jev outputs or turn a screening label into
verified fair value. Source reconciliation, conservation, quarter acceptance and
published-data semantics remain unchanged. An unresolved or unprocessed item stays
visible in the queue; capacity limits cannot silently turn it into a clearance.

## Shared bundle envelope

Use a common envelope plus a small, versioned evidence specification per rule.
Avoid separate complete builders for every filer. Where supported layouts need
configuration, make it explicit, evidence-backed and regression tested.

| Component | Required content/check |
|---|---|
| Flag and rule | Exact predicate, disputed fields, rule version, current flag record and parent review ID |
| Output position | Unique join within the frozen holdings snapshot; issuer, tranche/share class, dates, currency, values, dimensions, parent/JV/subsidiary scope |
| Provenance | Flag/holdings hashes, filing accession and raw-source hash, builder/parser version, model/prompt/routing versions |
| Source candidates | Relevant issuer and sibling positions, source coordinates, original cells, headers/spans, period, owner context and applicable notes |
| Identity evidence | Visible issuer/instrument/class/maturity/acquisition data, source dimensions/context and agreement/conflict checks |
| Monetary evidence | Printed values and signs, displayed units, inline tags/units/scales and any disagreement between them |
| Deterministic comparisons | Normalised values, differences and tolerance derived from display precision; original values retained |
| Completeness | Required fields present, retrieval scope/limits, missing evidence and unresolved conflicts; distinguish completeness from correctness |
| Status | Explicit eligibility result and reasons; never manufacture a normalised value to obtain readiness |

Every tagged monetary fact must resolve to a declared context with a nonempty
reporting instant and entity identifier. A visible schedule heading cannot replace
missing tagged context. Conflicting definitions or disagreement with the filing's
period/entity remain blocking. This readiness check does not certify that the
context names the correct sibling position; independent identity review still applies.

Resolve row IDs only in the snapshot where they were generated. Raw production
position IDs are not stable across rebuilds. Cross-build reuse requires a fresh
identity/provenance match and revalidation of the affected inputs.

## Rule-specific requirements

| Rule | Current trigger | Evidence needed |
|---|---|---|
| C107 | cost < 0 | Exact source position and cost column; sign, units, scope and applicable commitment/fee notes. A disclosed negative cost is not itself an error. |
| X08 | cost > 0, FV > 0, FV/cost < 0.05 | Exact source position, both cost and FV, their independent units and applicable impairment/instrument context. Do not broaden the existing predicate to zero FV in this work. |
| Future rule | Defined before implementation | Required fields, source relationships, permitted deterministic checks, ambiguity conditions, examples and independent tests |

Rate, PIK, NAV-denominator, aggregate or cross-quarter rules need their own
evidence contracts. C107/X08 support does not establish support for these families.
Preserve separate loans, share classes and other positions; an issuer-level match
cannot clear a position-level flag.

Cost-dependent bundles must preserve `cost_source` and `cost_reported`. The
published `cost` can be an intentional first-observed-FV proxy rather than a
current filing's reported cost. The v4 pilot contract accepts reported cost only:
its retained reported value must equal published cost, and the pathway must be
known. `derived_proxy` and `first_observed_fv_proxy` require a different contract
covering donor observation, donor source, period, position chain and the proxy
policy. They stay with B1; a current-SOI mismatch does not establish proxy error.
C104 depends on fair value alone and does not require a reported-cost basis.

The [proxy-cost investigation](07_proxy_cost_evidence.md) documents six real
examples and a B1-only lineage packet. Internal donor-policy agreement does not
certify source truth, position continuity or suitability of the proxy policy.

## Independent checks before clearance

1. Recheck the output join and current flag predicate against the frozen inputs.
2. Establish source period and accounting scope. Filing date is not the reporting
   period, and a filing may contain current and comparative schedules.
3. Check visible position identity against dimensions and output identity. Exact
   context-ID equality does not resolve a visible Class A/Class C contradiction.
   Disputed values cannot be the sole identity-selection criterion.
4. Validate signs and units against the displayed schedule. Conflicting inline
   scale and displayed amounts require corroboration or escalation; applying the
   inline scale mechanically is insufficient.
5. Verify every required numeric comparison independently of Jev's disposition.
   A mismatch prevents clearance; rounding tolerance comes from the source.
6. Confirm relevant notes and sibling/continuation context were retained. Unknown
   candidate recall, truncation or an unresolved layout prevents clearance.

These checks must inspect preserved source evidence; validating a model's own
answer or recomputing arithmetic on a wrongly normalised amount is insufficient.
Jev can propose a source match. The independent checks can reject it, never infer
that identity is correct merely because amounts agree.

## Bounded construction and execution

- Read cached filings only. This work does not authorise SEC downloads.
- Retrieve by identity and structure, retain plausible siblings, then calculate
  comparisons. Do not search by the disputed amount to manufacture a match.
- Keep original source snippets/coordinates and compact repeated headers/notes.
  Oversized evidence routes to B1; do not truncate required evidence to fit.
- The existing 26,000 cl100k_base estimate is a proxy, not Jev's tokenizer or a
  certified context-limit check. Validate limits for the pinned provider/model.
- Pin the model, questions, rule contract and routing configuration per run.
  Record provider token usage, latency, cost basis and failed attempts.
- Cache only by complete input/version fingerprints. An evidence, holdings, rule,
  model or policy change invalidates a cached routing decision.
- Persist request/attempt IDs before submission. Bound timeouts, retries and spend;
  unknown submission outcomes are not silently retried. Never log credentials.

## Integration and accounting

The authoritative flag queue remains [pipeline/review_queue.py](../../pipeline/review_queue.py).
Implement a screening sidecar keyed to its review IDs and the exact member flags.
Start as a read-only projection. Only after validation should it filter eligible
weak items from the B1 worklist consumed by
[scripts/agent_b/run_review.py](../../scripts/agent_b/run_review.py).

A grouped review item may cover many positions. Track every member: partial Jev
coverage cannot clear the parent group. Retain unsupported, pending and sampled
members in the B1 projection. Preserve existing priority and lock semantics;
deduplicate investigations without hiding distinct flags or positions.

Each decision receipt should include flag/member IDs, all input hashes, selected
evidence, model outputs and both confidence scores, independent check results,
route/reasons, timestamps, versions, usage, audit-sampling status and any later B1
resolution. Generate a short explanation from these recorded facts; never invent
a model rationale. Store source citations and the decisive comparisons so the
absence of a Jev narrative does not remove the audit trail.

Keep raw observations separate from final resolutions. Expired evidence reopens
eligibility. A confirmed unsafe clearance disables the affected rule/layout mode
and requeues affected clearances since the last valid checkpoint, without deleting
history. Do not automatically refresh official baselines or alter gate thresholds.

### Source-context omission veto

Inventory monetary rows sharing the output's declared source context separately
from issuer-name retrieval. If any such row is omitted, block the bundle with
`source_context_anchor_not_retrieved`; do not silently choose a remaining sibling.
In unsupported tables, only explicit known monetary concepts count as anchors.
Absence of an anchor is not proof of complete recall. Independent candidate-recall
review remains required, and pipeline context identifiers remain claims to verify.
