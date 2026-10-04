# Confidence cutoff sensitivity

Date: 2026-10-04. Offline analysis of the existing 98 successful calls.
No threshold, model request or production route changed.

## Observed coverage sensitivity

Counts below require a `false_alarm` answer, an actual source selection, and both
decision and source confidence at least the stated cutoff. They are confidence
candidates, not independently audited clearances.

| Observation group | Calls | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 | 0.90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| First natural calls | 42 | 27 | 23 | 17 | 7 | 1 | 0 |
| Later builder rechecks | 12 | 10 | 9 | 6 | 5 | 1 | 0 |
| Presentation variants | 8 | 8 | 6 | 3 | 3 | 1 | 0 |
| Exact-request repeats | 8 | 8 | 7 | 4 | 3 | 0 | 0 |
| Synthetic numeric controls | 24 | 6 | 6 | 4 | 3 | 0 | 0 |
| Synthetic source-note controls | 4 | 0 | 0 | 0 | 0 | 0 | 0 |

Do not pool these groups: rechecks, presentations and synthetic controls reuse
natural parents. The rechecks used the then-current builder, before the latest
repairs. No historical response automatically revalidates a changed request.

All 42 first natural calls and all 12 rechecks have false-alarm references.
Consequently, their agreement cannot estimate the missed-error rate at any
cutoff. Raising the cutoff reduces apparent coverage; this sample does not
establish the corresponding safety improvement. Lowering it to regain coverage
would also be unjustified. Keep 0.75 as the frozen experimental threshold.

## What happened on disagreements

The one natural source disagreement was an `insufficient_evidence` selection:
decision confidence 0.68, source confidence 0.02. It cannot become a confidence
candidate even with numeric cutoffs set to zero.

Four synthetic numeric errors did not receive `real_error` labels:

| Answer | Decision confidence | Source confidence | Source agrees with reference |
|---|---:|---:|---|
| ambiguous | 0.51 | 0.39 | No |
| false_alarm | 0.13 | 0.72 | Yes |
| ambiguous | 0.19 | 0.34 | No |
| ambiguous | 0.44 | 0.41 | No |

Ambiguous answers always remain B1 work, regardless of confidence. The false-alarm
answer passes neither the 0.75 decision threshold nor the joint threshold. If
both numeric cutoffs were removed, that synthetic error would become a
confidence candidate, though independent evidence/routing vetoes would still
apply. This is a useful regression case, not a calibrated safety result.

Correctly detected errors can also have low confidence. All four source-note
stress controls returned `real_error`, with decision confidence 0.20-0.54, and
remain B1 investigations. Low confidence means escalate; it does not mean the
suspected error is unlikely enough to ignore.

## Reproduction and remaining evidence

The isolated `scripts/analyze_jev_thresholds.py` checks ledger fingerprints,
packet/request/receipt bindings and frozen reference hashes. It separates all
six observation categories and also reports source-threshold sensitivity with
decision confidence fixed at 0.75. Four focused tests pass for boundaries,
abstention, false negatives/wrong sources and repeated-call accounting.

Artifact: `data/pilot/jev_screening/20261003_shadow/threshold_sensitivity_03d8ecf1b45aaec8.json`.
Input ledger: `observation_ledger_7f374e22e11694ca.json` in the same directory.

Choosing a production cutoff still requires an independent error-bearing sample,
frozen presentation and builder, measured review costs, and a held-out evaluation.
Confidence is the provider's score, not an established probability of correctness.
No new API calls, natural cases or audited clearances were added.
