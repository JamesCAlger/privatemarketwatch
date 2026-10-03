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
