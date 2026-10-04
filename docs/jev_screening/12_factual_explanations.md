# Factual explanations without a model narrative

The isolated pilot can now generate short investigation summaries from frozen
routing receipts. It reports the recorded answer/confidences, routing reasons,
selected source coordinates and notes, and recomputed field comparisons. It does
not ask Jev to invent a rationale or claim why the extraction failed.

Every explanation binds to the bundle and routing-receipt fingerprints. The
report includes the provider-receipt hash, source/holdings hashes and full routing
receipt. An altered receipt or different bundle is rejected. A missing, ambiguous
or unbound source choice cannot produce an invented numeric comparison. Production
clearance and B1 suppression remain disabled.

## Real frozen examples

These are historical experiment observations, not classifications of the latest
builder revision. They do not confer independent audit status.

| Example | Recorded facts | Why B1 remains |
|---|---|---|
| Fortress Exemplis, C107 | Output and model-selected source cost both -$195,000. Jev false_alarm; decision/source confidence 0.88/0.74. | Source confidence falls below the trial 0.75 cutoff. Numeric agreement does not settle source selection. |
| Onex VTC, C107 | Output and selected source cost both -$23,855. Jev false_alarm; confidence 0.89/0.85. | No independent source-review certificate. Passing both confidence cutoffs is insufficient. |

A separate **synthetic** Monroe Premier scale control shows what an error summary
can preserve: cost $2,465,000 agrees; altered output FV $1 differs from selected
source FV $1,000. Jev returned real_error with decision/source confidence 0.53/0.91.
It goes to B1 because every suspected error does, irrespective of confidence.
This is an injected test error, not another naturally observed pipeline defect.

## Limits and artifacts

`pipeline/jev_explanation.py` and `scripts/explain_jev_observations.py` live only
in the isolated worktree. The CLI reads frozen experiment records, makes no API
calls and writes fingerprinted reports under the pilot run. Reports were generated
for 12 current-development records (eight observations plus four blocked controls)
and eight scale-control records. These are 20 explanations, not 20 new flags or
model calls. They were generated at 98 calls; the programme now has 100 calls / 42 unique natural flags, including the later zero-value controls.

The explanation recovers *what was observed and why it was routed*. It does not
replace B1's source investigation, causal diagnosis, repair proposal or independent
validation. Neither investigation-time savings nor user comprehension has been
measured. The formatter has focused checks for changed inputs, missing sources,
contradictory arithmetic, unavailable currencies and pending observations.
