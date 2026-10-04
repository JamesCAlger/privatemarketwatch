# Paired zero-value error control

Date: 2026-10-04. The final two calls under the 100-call experiment cap.

C104 is a plausible wider-screening target: the reserved funds have 448 recorded
Q1-2026 zero-FV issues marked track-only. Its earlier two natural calls had no
real-error reference. This pair tests a specific missing-value error without
adding a fund or presenting a synthetic error as naturally observed.

## Frozen design

Parent: Specialized Dental Holdings II, LLC, CIK 1784700, Q1 2026,
`ROW-51aff32e293b8795`, source table 21 row 10. The cached filing discloses a dash
with an explicit `fixed-zero` inline transform, USD currency and scale 3. Output
FV is zero. This is one of the existing 67 natural flags.

Two synthetic child records use the latest frozen builder:

- Disclosed zero: original source evidence, unchanged output values.
- Missed positive FV: copied source changes that one FV fact from an explicit
  zero dash to numeric `1` in thousands, using `num-dot-decimal`; output stays zero.

References were frozen before submission: false alarm and real error respectively,
both selecting `t21r10`. The complete candidate comparison verifies unchanged
identity, period, notes, headers, siblings and unrelated cells. Only the FV cell,
its duplicate in surrounding context, normalized FV and arithmetic comparison
change. The original cached filing is unchanged. Synthetic IDs and provenance
hashes differ, so this is not an exact-request replication.

## Results

| Control | Jev answer | Decision confidence | Source confidence | Source correct | Route |
|---|---|---:|---:|---|---|
| Disclosed zero | false_alarm | 0.72 | 0.56 | Yes | B1: low confidence |
| Missed $1,000 | real_error | 0.77 | 0.42 | Yes | B1: suspected error |

Both labels and source choices match the frozen references. Neither is a
confidence-only clearance candidate. The deterministic context-anchor comparator
also resolves both correctly; this pair does not establish incremental model
value or a natural missed-error rate. A single source candidate does not itself
produce high model source confidence.

The two calls used 19,741 provider input tokens. Cumulative totals are now
**100 calls, 1,580,960 input tokens, approximately $0.0664 at the verified published
input-token rate**. All 100 response contracts validate. There are still 42 unique
natural flags called, 67 selected natural flags, 11 represented funds and 16
funds reserved across the programme. Synthetic controls now total 30 calls:
24 earlier numeric controls, four source-note controls and these two zero controls.

No further API calls will be made under this capped experiment. Offline work
continues under the owner's instruction. No independent audits, clearances,
production changes or B1 suppression were added.

## Artifacts

Under `data/pilot/jev_screening/20261003_shadow/`:

- `zero_control_design_44.json`, `zero_control_references_44.json` and
  `zero_control_verified_44.json`: pre-call design, references and mutation check.
- `zero_control_packets_44/`, `zero_control_sources_44/`: synthetic packets and
  copied source; original cache remains unchanged.
- `zero_control_model_01/`: frozen requests, responses via the attempt ledger,
  analysis and shadow routing receipts.
- `observation_ledger_926ba1f7437719b0.json`: complete 100-call accounting across
  seven distinct observation categories.

Isolated scripts: `build_jev_zero_controls.py`, `verify_jev_zero_controls.py` and
the existing bounded runner. C104 used the opt-in weak-probe policy; synthetic
provenance is explicit and ledger accounting keeps these out of natural cases.
