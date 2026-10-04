# Evidence informing the plan

Evidence date: 2026-10-03. The authoritative detailed record is
[agent campaign investigations](../investigations/agent_campaigns.md).
These were development experiments, not production routing or human-audited gold.

## What was actually tested

| Experiment | Distinct items and scope | Calls | Main result |
|---|---|---:|---|
| First automatic builder pilot | 14 natural flags, three funds | 0 | 10 marked ready; four blocked |
| Initial classifier test | Those 10 ready flags plus four synthetic variants | 28 | Natural labels agreed in 20/20 calls; synthetic errors detected in 5/8. One natural clearance had no selected source. |
| Expanded builder test | 27 natural flags across seven funds; eight targeted, one without matching flags | 0 | 23 blocked; four ready TCW packets all had source-cost normalisation problems |
| Expanded source-reviewed arm | 12 of those 27: four real errors, seven false alarms, one ambiguous identity | 24 | 11/12 distinct reference dispositions matched in both orders; ambiguity cleared twice |
| Expanded automatic arm | The same four TCW cases, with the original automatic packets | 8 | 8/8 real_error labels, despite bad source-cost evidence |

The expanded test therefore contains **27 builder tests, 12 distinct classification
cases and 32 calls**. The 12 manually reviewed cases comprise the four automatic
packets and eight blocked cases. The other 15 were not submitted to Jev. Neither
reversal nor the second preparation arm creates additional independent cases.

The 12 reviewed cases cover six funds. The four natural errors all come from TCW
in one quarter with one FV scale mechanism. This cannot establish broad error
recall. Manual source selection/normalisation is not automatic bundle coverage.

Earlier manually curated smoke tests and historical B1 replay are documented in
the investigations file. They are not additional validated natural-case coverage
for this prototype. Replayed historical packets sometimes lacked exact position
identity or the disputed FV, so their agreement rates do not isolate model quality.

## Required regression examples

| Example | Observed failure or correct behaviour | Required protection |
|---|---|---|
| AmSpec / ACP Falcon synthetic C107 errors | Jev selected the correct source yet cleared a wrong cost in three calls; decision confidence 0.38, 0.41, 0.50 | Deterministic monetary mismatch veto; confidence alone is insufficient |
| Seres warrant | false_alarm confidence 0.71 alongside insufficient source evidence | Source selection and disposition must be mutually consistent |
| TCW HOP Energy, Red Robin, Black Rock Coffee, Resco | Current FV is 1/1,000 of displayed source FV. Automatic builder additionally inflated source costs using conflicting inline scale=3 | Cross-check displayed amounts/units and inline tags; correct final label is not proof of correct evidence |
| Ares Amerivet, 2024-12-31 | Visible Class C row has the output amounts, but output and source context c-187 say Class A. Jev cleared twice at 0.68/0.66 decision confidence and 0.71/0.82 source confidence | Visible class versus dimension/identity check; amount agreement and context equality are insufficient |
| Onex IMB, 2023-09-30 | Current cost $3.4m and FV $29,750 agree with source. Old B1 cited FV $2,974,150 from a 2022-12-31 context | Correct period; independently audit B1 references. Old actual output FV was not preserved, so historical final-label correctness remains unknown. |
| Fortress Xponential, 2026-03-31 | Current cost -$29,000 matches source; historical B1 concerned -$39,000 | Recheck current inputs; do not inherit a verdict across builds |
| Carlyle/Varagon/Onex/Senior Credit/Ares layouts | Header, date, continuation, note, numeric-cell or currency gaps caused rejection | Reusable layout support and explicit unresolved outcomes, with independent source validation |

The Amerivet clearance would pass a numeric-agreement check. It would be escalated
by a 0.75 decision cutoff in this sample, but that does not validate the cutoff on
future cases. The natural false alarms had decision confidence ranging from 0.33
to 0.88, so a high cutoff can also consume much of the hoped-for B1 saving.

## Existing artifacts and implementation

- [Bundle code](../../pipeline/jev_bundles.py),
  [bounded CLI](../../scripts/build_jev_bundles.py),
  [tests](../../tests/test_jev_bundles.py): experimental only; 24 focused tests passed
  when the prototype was built. No production screening integration exists.
- Initial frozen packets: `scratch/2026-10-03_jev_builder/final/`.
- First classifier run: `scratch/2026-10-03_jev_bundle_experiment/`.
- Expanded run: `scratch/2026-10-03_jev_real_cases/`; includes selection, original
  packets, source windows, frozen requests/responses, summary, verification and audit.
- Expanded offline checks covered 27 packet hashes, 12 source-file hashes, 32
  requests/responses, 16 reversal pairs and 96 field comparisons. Passing arithmetic
  against wrongly normalised evidence was explicitly not an evidence-quality pass.

The first classifier run used 323,950 input tokens; the expanded run used 609,836.
Estimated inference costs at the rate recorded on the experiment date were about
$0.0136 and $0.0256 respectively. Manual preparation, investigation and maintenance
were not priced; these figures do not establish end-to-end savings.

Scratch is disposable. Preserve the necessary manifests, references and receipts
in the durable evaluation corpus before relying on these experiments for rollout.

## Consumed development filers

The following nine CIKs have now contributed to builder development or these
current-case experiments: 0001702510, 0001742313, 0001784700, 0001825265,
0001860424, 0001872371, 0001918712, 0001959568 and 0002012139. Onex overlaps both
samples; the programme has not tested ten distinct filers.

Carlyle and Ares Strategic Income appeared in the older B1 benchmark's reserved
filer split. They are no longer untouched filers for this work. Check the earlier
benchmark corpus too when selecting genuinely unused holdouts. Ares Core
Infrastructure was targeted in selection but produced no current flags; it is not
an additional evaluated filer.

All completed current-case tests concern BDCs. No result establishes support for
other vehicle types or for a source format not actually exercised.

## 2026-10-04: bounded recheck of historical B1 group coverage

Within the existing 16-fund reservation, the earlier ens2_rest_r3 inventory contains 40 historical review items for these families: C107 14, C104 14, X08 12. These are grouped historical references, not 40 additional current natural flags. Three C107 items have known partial coverage and initial issue excerpts smaller than their groups:

| Historical review ID | Fund / period | Group issues | Initial issue excerpt |
|---|---|---:|---:|
| RVQ_REV_ccd366f14e46 | Senior Credit, 2024-09-30 | 89 | 25 |
| RVQ_REV_6d7c7704ecee | Oaktree, 2024-03-31 | 42 | 25 |
| RVQ_REV_0a39a3b68c74 | Oaktree, 2023-12-31 | 40 | 25 |

Re-read the three original trace bundles and final messages, verifying all trace/verdict hashes against the frozen inventory. Their finals explicitly describe representative or sampled source support. Initial excerpt size alone cannot measure all later investigation, but these stated caveats prevent treating the verdict as independently verified truth for every group member. The other 37 inventory entries have no detected partial-coverage marker; that is not proof of complete investigation.

This matters to the proposed hybrid: complete per-member accounting could improve coverage compared with representative B1 review, even before it saves time. That potential benefit is not yet a measured improvement in defect discovery. Each source-backed member needs a snapshot-specific reference; do not spread a group false_alarm label across uninspected rows or transfer it into current holdings. The historical Senior Credit group has 89 issues versus 88 in the current corresponding group, another reason to preserve snapshot identity.

Artifact: historical_coverage_d8419f2cf0af2bf7.json. No new funds, current flags, classifier calls or production changes. The script reads only the three known partial traces after filtering the historical inventory to the reserved funds.

## 2026-10-04: historical error candidates do not transfer to current flags

A read-only recheck of three historical error groups within the existing fund reservation found no justified new current-error label:

| Historical reference | Current snapshot observation | Consequence |
|---|---|---|
| TCW C104, Q3-2025, RVQ_REV_d01fc72414cb | Three old issues versus two current flags: HOP Energy Term Loan B and Superior common stock. The old verdict identified a third blank subtotal as the error and explicitly described the other two zeros as legitimate. | Do not spread the group error label across the two surviving named flags. Count reduction alone does not prove which remediation removed a row. |
| TCW C104, Q3-2024, RVQ_REV_2b5ab0f83dc7 | Current HydroSource warrant FV is 210,328, matching the amount cited by historical B1; the sole current C104 flag is HOP Energy Term Loan B. | The old ordinal cannot identify today's flagged position. Current amount agreement with a historical citation is not a fresh source audit. |
| Ares Strategic investigation reference RVQ_REV_cfa56935ad94 (X08, Q4-2025) | No current X08 flag in that fund/period. Alcresta's revolving-loan cost/FV are 73,700/73,500, matching the historical cited amounts. | This is not a present error-bearing classifier case. The data-change mechanism was not investigated. |

The original issue excerpts retain only row_key ordinals, not durable position identities. The diagnostic never joined those ordinals to current holdings; it separately located current flags and name-based candidate positions, preserving distinct instruments. It verified original trace/verdict hashes and current input hashes before/after. Neither historical group labels nor apparent amount corrections were promoted to gold.

Artifact: historical_error_candidates_00ddb8e888a19fd3.json; initial flag-only report historical_error_candidates_bbe7200d66f9741a.json. No new builder cases, API calls, funds or production changes. The frozen experiment remains 67 cases with four reviewed natural numeric errors. A reusable error corpus needs the original full output row, original source bytes/context, rule semantics and a position-specific adjudication, rather than a historical queue verdict plus a current CSV.
