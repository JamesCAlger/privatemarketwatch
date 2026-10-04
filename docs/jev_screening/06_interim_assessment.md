# Interim assessment: useful screening requires validated evidence

Updated 2026-10-04. Work continues in the isolated pilot; this is not a production
approval or the final experiment report. Exact versions and limitations are in
the [run log](05_run_log.md).

## What the evidence currently supports

Improving bundle construction supports the proposed Jev/B1 workflow. The most
useful improvements so far are reusable source checks: displayed versus tagged
units, current versus comparative periods, share-class identity, inherited notes,
note tables and explicit rate legends. They also improve evidence available to
B1. None requires changing production holdings.

The main unresolved cost is proving that a bundle contains the necessary evidence.
A model can return the correct label while notes or scope are missing. This
happened in source review of both development and temporal packets. High model
confidence cannot compensate for that omission.

Field provenance is another necessary boundary. Five of the remaining C107 cases
use intentional first-observed-FV cost proxies, not current reported cost. A
current-SOI comparison cannot adjudicate those proxies. Bundle v4 now preserves
the pathway and retains these cases for donor-lineage review. The other remaining
cases yielded four matching negative costs and one term-loan/revolver ambiguity;
this did not add another confirmed natural numeric-error mechanism.

## Results and their limits

| Observation | What it means |
|---|---|
| 11 funds represented by 67 natural flags; 42 natural Jev calls | Cumulative programme reservation is 16 funds, including prior research. Both are below the 70-fund v1 cohort; this is not a representative population sample. |
| 42/42 natural label agreement; 41/42 source agreement | All called natural references are false alarms. Four reviewed natural errors were blocked before submission. This does not estimate missed-error risk. |
| Original two-fund holdout: 0/20 bundles ready | Initial layout transfer failed. Repairs consumed this holdout; subsequent scores are development results. |
| Two new-accession temporal cases: 2/2 label/source agreement | Within familiar filers, not unseen-filer validation. Later review found missing context in one packet, so this is not 2/2 complete-evidence validation. |
| 24 separate synthetic controls | Include rounding, sibling-cost substitutions and FV scale errors. One substituted-cost error was called a false alarm at 0.13 decision confidence; it stayed with B1. |
| 17 historical confidence-only candidates | Not audited clearances. Later bundle versions invalidate reuse of old scores. Two newly called Fortress cases pass both trial cutoffs after grouped-header repair. |
| Eight presentation calls on four revised X08 cases | Labels/sources remain correct, but three flags change confidence eligibility between orders; none passes both cutoffs in both orders. One call per order does not isolate provider variability. |
| Eight exact-request repeats of that presentation experiment | All labels/sources remain correct. No complete answer distribution is identical; one unchanged request crosses the cutoff. Two between-presentation eligibility differences persist on repetition. This confirms some provider variability, without quantifying its population rate. |
| 12 current-builder rechecks plus four blocked natural-error controls | Jev and the raw-preserving comparator both match all 12 called labels/sources. Six pass both confidence cutoffs; four eligibility results differ from older bundles. All 16 route to B1. This is development evidence, not a fresh holdout. |
| Four source-note stress calls | Two synthetic cost errors, each with and without misleading instructions in a copied note: 4/4 correct source/error decisions, all B1. Not a general robustness result. |
| 98 total calls, 1,561,219 provider input tokens | About $0.0656 inference cost at the verified published rate; not an invoice or end-to-end cost. Includes repeats and rechecks. No B1 time savings established. See [sizing and cost](08_context_size_and_cost.md). |
| Zero certified clearances; all B1 work retained | No production safety or savings claim |

The deterministic exact-context comparator resolved 39/42 model-scored natural
cases with reviewed-source agreement. The remaining three differ only by an
affiliation prefix removed by the pipeline; the exact original dimension remains
in `bdc_dimensions_raw`. A separate development comparator validates that raw
dimension and the narrow prefix normalization, resolving all 42 with 42/42 label
and source agreement. Its extra-axis, tranche and visible-identity vetoes remain.
The original exact comparator and its results are preserved.

This is a material limit on the case for Jev: its incremental contribution has
not been demonstrated on the tested natural cases. These comparators share
builder inputs and historical evidence omissions, so 42/42 is not independent
certification or a production clearance claim. Harder identity/interpretation
cases and an error-bearing holdout would be needed to establish model value.
The common-builder recheck reproduces this finding on 12 current packets, so it
is not solely an artefact of the older mixed-version comparison.

Latest supplemental source review accounts for all 67 flags: 49 false alarms,
four known errors, two identity ambiguities and 12 unscorable cases. These are
review dispositions, not independently certified clearances. Frozen model-scoring
references are preserved separately. Latest full replay currency_namespace_v4_37 has
34 ready and 33 blocked: C107 21/23, X08 11/8, C104 2/2. Readiness is not audited
completeness. Thirteen of 17 historical confidence-only candidates remain ready;
none has an unchanged current request, so old scores are not transferred.

Synthetic changes to three real filings confirm some structural fallback
behaviour, but deeper probes found that missing monetary context definitions,
dates or entities were not blocking readiness. Explicit checks now reject those
cases. The repaired replay changes neither the 34/33 readiness split nor candidate
sets. This is a corrected synthetic failure mechanism, not an additional observed
production error. The 12 most recent recheck payloads now differ only in bundle
ID; even those are preserved as old-version observations, not newly scored calls.

## Implications for the proposed workflow

Separate existing review work from additional screening:

| Frozen flag action | Flags | Current ready / blocked | Interpretation |
|---|---:|---:|---|
| C107 REVIEW | 44 | 21 / 23 | Potential reduction of review-action flags, subject to audits; these are not 44 measured B1 jobs. |
| X08 TRACK_ONLY | 19 | 11 / 8 | Added screening coverage, with B1 investigation capacity needed for escalations. |
| C104 TRACK_ONLY | 4 | 2 / 2 | Exploratory extra coverage; no clearance eligibility promoted. |

In the 12-call current-builder recheck, only two of seven C107 cases passed both
confidence cutoffs. Four of five called X08 cases passed, while four additional
known-error X08 controls were blocked before calling. None was independently
cleared. Pooling all six confidence candidates as avoided B1 jobs would therefore
overstate the benefit. The sampled cases cannot establish population workload.

- Keep low-confidence, difficult-bundle, suspected-error and known-high-error
  cases with B1. Keep independently sampled review even for future clearances.
- Treat 0.75 as a trial cutoff on the provider's confidence scale. It is not a
  calibrated probability of correctness or permission to waive evidence checks.
  Freeze presentation order too; do not select whichever ordering produces the
  higher confidence. Presentation stability is an additional validation need.
- Improve reusable evidence mechanisms before adding filer-specific patches.
  Explicit fallback is preferable when schedule scope cannot be established.
- Distinguish wider weak-rule review from B1 cost reduction. X08/C104 are currently
  track-only weak rules; screening them adds coverage rather than removing an
  existing B1 job. That opportunity needs measured incremental error discovery.
- Make the next decision by rule and supported layout, including builder and
  review effort. Overall label agreement alone is insufficient.
- Keep a deterministic-first alternative in the shadow comparison. For supported
  value checks, source matching plus arithmetic may cover the work without Jev;
  it must meet the same independent evidence requirements before any clearance.

## Remaining experiments

1. Measure the current builder's readiness and independently review its apparent
   successes, including notes inherited across page boundaries.
2. Compare deterministic checks and Jev on the same evidence. Do not count a
   cheap arithmetic check as a uniquely model-enabled saving.
3. Rescore only justified revised packets, preserving old observations and the
   100-call session cap. Add no funds beyond the reserved 16.
4. Preserve unresolved mechanisms as regression cases and B1 fallbacks. Fresh
   independent B1 timing and a representative error-bearing holdout remain future
   requirements; neither has been completed in this isolated session.

Production code, data, queues, gates and baselines remain unchanged. The isolated
checkpoints are local only; no merge or push has been performed.


