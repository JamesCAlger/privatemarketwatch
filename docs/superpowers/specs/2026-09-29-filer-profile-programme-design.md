# Filer-profile programme: design

Date: 2026-09-29. Status: approved in session by the owner (sections 1-6), pending written review.
Branch: `filer-profile-pilot` (worktree). Supersedes the pilot's Stage C and D as planned in
`docs/superpowers/plans/2026-09-28-filer-profile-pilot.md`; the pilot spec v4.2 remains the
authority for the census, envelope and contract mechanics it defines.

## 1. Objective

Every filer's XBRL is interpreted through one dated, evidence-backed record of what that
filer's tags mean, so that production numbers come from stated rules instead of scattered
code, and a change in a filer's tagging is caught the quarter it happens.

Three parts, set by the owner on 2026-09-29:

1. **Observability.** "Which rule produces this field for this filer" is one lookup.
2. **Semantics at inception, then maintained.** Per field, per filer: what the values mean,
   recorded when the filer enters the cohort as dated entries that can be corrected without
   losing history.
3. **Persistence.** The record and the existing corrections survive quarter over quarter, and
   drift in a filer's tagging is detected automatically.

Not objectives: replacing the wrapper's executable knowledge by derivation, matching the
wrapper key for key (the pilot's M1), parity as a metric (M4), half-life as a metric (M5).
Parity survives only as the migration safety net (section 5).

## 2. Decisions taken in session (2026-09-29)

| # | Decision | Owner's choice |
|---|---|---|
| D-scope | What "done" covers | The 8-filer pilot cohort, proven end to end; scaling to the ~70-filer cohort is a follow-on programme |
| D-live | How far into production | Live for the 8: production staging reads the profile for them and the wrapper files for the other ~60; the wrapper is consolidated INTO the profile as a section |
| D-consolidate | Wrapper vs profile | The profile is a new document with a lifecycle; the wrapper's content becomes one section of it, unchanged in shape, under the same versioning and evidence rules. Not a rename, not an extension |
| D-amend | Can B2 change a column's meaning | Yes, as a proposed entry admitted through contract, witness, dated boundary and sign-off tier (section 6) |
| D-seq | Sequencing vs V13 | Option A: the programme proceeds on the current branch; V13 is RETIRED (not deferred): no V14, the refactor build cadence ends, its matching repairs ride into production with the first profile-era build |
| D-quarters | Build and test quarters | Build on Q4-2025; prove consumers by twin build against signed-off Q1-2026; replay Q4-to-Q1 drift against the q1p3 adjudicated findings; Q2-2026 is the first live quarter when its filings are fetched for the normal pass (not a programme dependency) |
| D-agents | Who adjudicates, who admits | Codex fleets adjudicate (B1 verdicts, B2 proposals); the owner admits column-meaning entries; row-level entries auto-admit on confirmation |
| D-done | Exit criteria | All five in section 3 |
| D-experiments | Detector breadth | A detector-experiments sub-project over a wide variety of tests; event triggers excluded for now |

Verified facts behind D-consolidate and D-amend: the census derives 13 of 699 wrapper keys
exactly (Stage B M1); a profile-generated wrapper drives ~4% of staging (Stage B translate);
identifier text is the wrong side in 30 of 32 adjudicated spread packets and 453 vs 69 in the
deterministic reconciliation, so text is a weak witness (ledger ruling R40); no deterministic
instrument-type signal exists on BCRED's bond contexts (ruling R41).

## 3. Exit criteria (all required)

1. **Coverage.** Every field of every one of the 8 filers has a dated, evidenced entry or an
   explicit insufficient-evidence stub; stubs are listed with the evidence that would close them.
2. **Production reads the profile.** A twin build of the Q1-2026 filings for the 8 filers is
   identical to the wrapper build except for rows touched by accepted entries that were meant to
   change them, each listed with its evidence.
3. **Drift runs in the quarter pass.** The Q4-to-Q1 replay reports recall and false-alarm rate
   per contract kind against the q1p3 adjudicated findings; Q2-2026 runs live and produces the
   adjudication queue the fleet works.
4. **No per-filer knowledge in code** for the 8 filers: the code-path inventory (section 7)
   has no open rows.
5. **Corrections persist.** Every existing B2 correction for the 8 is an entry, re-evaluated
   each quarter, with failures listed.

## 4. The profile document

One document per filer at `data/profiles/{cik}.json`, in git, replacing the wrapper file for
the 8 filers. Four parts:

- **Entries.** The Stage A envelope as built: field, partition predicate (`applies_to`
  structural predicates; row position is never a predicate), value, `valid_from` / `valid_to`
  report dates, `recorded_at` / `recorded_until` wall clocks, evidence references, provenance
  (derived by census, authored by person, proposed by fleet), confidence, status in
  {candidate, accepted, superseded, retracted}. Entries are immutable; change is a new entry
  plus a supersession event with kind (correction or genuine change) and reason.
- **Semantic axes per field**, each an entry type: source concept set; scale and unit
  convention; meaning (all-in vs spread, cash vs all-in, fixed-vs-floating rule); identifier
  format and dialect; partition structure; income proofs (principal currency, rate units,
  duration, estimated-income calibration).
- **Wrapper section.** The filer's wrapper content in its executable shape, one versioned
  block with validity dates, hash and evidence (the sign-off it was attested under).
  Production's wrapper loader reads it from here for the 8 filers. Edits are supersessions.
- **Corrections section.** Every B2 correction for the filer as an entry with mechanism, keyed
  rows, evidence and dates, re-evaluated each quarter by the contracts.

Each document carries a version, a schema version and an event log. Readers call
`profile.resolve(cik, field, report_date, row)` and receive exactly one accepted entry or an
explicit ambiguity error (the Stage A resolver). Nothing in the document is executable except
the wrapper section.

Lifecycle, all entry kinds: supersede (genuine change: new `valid_from`; correction: back to the
old `valid_from`), retract (failed confirmation or contradicted witness), end (`valid_to`).
Nothing is physically deleted. Global rules in pipeline code stay outside the document with
their existing lifecycle; the inventory (section 7) is the only link.

## 5. Contracts and the drift stage

A contract is a testable expectation attached to an accepted entry. Kinds: source concept set,
fill rate, scale, format grammar, value range, rate composition (floating-share and
fixed-coupon-share criteria; dispersion recorded as evidence only, ruling R39), text agreement
(evidence only, R40), income yield (redesigned: each proof step is its own entry and contract;
reconciliation runs only where the proofs hold).

Statuses: holds, breach, insufficient_evidence, holds_with_form_type. Two rules added from the
Stage B2 measurements: `newly_abstained` is reported as an event whenever a contract that held
becomes unevaluable; a quarter with zero recognised positions but position-like facts is a
BREACH of every fill and concept contract, never an abstention.

Bands live in a versioned tolerances file; a band changes only by a new version with the
reason and prior results preserved; the file records which quarters each version has seen.
Calibration set: the Q4-to-Q1 replay and the q1p3 findings ledger. Q2-2026 is the first
out-of-sample quarter. Measured error rates at the start of the programme (rolling pairs,
2022-2026, 8 filers): structural kinds ~2% false alarms; concept-set 13 of 15 recorded events
caught once the zero-position rule applies (one on the wrong field); fill-rate 1 of 4; value
range 0 of 8 under the v2 band; composition and text kinds have no trustworthy rate yet.

The drift stage is the first stage of `scripts/run_quarter_pass.py`, before rebuild: census the
new filing once under the existing bounds; evaluate every accepted entry's contract; write the
queue (breaches and newly-abstained events, ranked by fair value at risk, with violating source
rows) in the findings-ledger shape. Learning happens only when an entry is admitted, not every
quarter. Shadow mode writes the queue beside the existing one and nothing downstream reads it.

### 5.1 Detector experiments (D-experiments)

A sub-project measures, with the three yardsticks (seeded drift, Q4-to-Q1 replay against q1p3,
all-quarter quiet pairs), each of: cohort-relative comparison at the same report date;
independent totals (fair-value conservation, pct-of-net-assets sum, income reconciliation) as
per-filer monetary-scale detectors; row continuity (matched positions whose field changed while
the identifier text did not; the opt-in position registry is the hook); taxonomy and linkbase
diff between filings; presentation-header change in the inline XBRL; distribution tests (PSI or
KS) replacing the min-max value-range band; change-point detection over the filer's series.
Winners are versioned into the tolerances file as contract kinds. Event triggers (amendments,
auditor changes, namespace bumps) are excluded from this programme.

## 6. The fleet and admission loop

The queue is dispatched in the existing bundle shape: breach, violating rows, raw
current-period facts, the accepted entry tested, the filer's profile.

- **B1 adjudicates**: verdict real change / false alarm / needs human. No proposals.
  (Measured verdict stability 94%.)
- **B2 proposes**, only on real-change verdicts, in analyst mode with the cached filing: a
  proposed entry (field, partition, value, `valid_from`, evidence, confidence, mechanism).
  Workers never write the profile. (Measured mechanism stability 64%, hence candidates.)

Admission, two tiers:

- **Row-level and structural entries** (concept moved, format changed, keyed corrections,
  delimiter and marker changes): admitted as `candidate` when the proposing quarter's contract
  holds on them and no witness contradicts; `accepted` when the next quarter's contract
  confirms; retracted with reason on failure.
- **Column-meaning entries** (scale, all-in vs spread, fixed-vs-floating rule, income proofs,
  identity rules, invariants): `candidate` until the owner signs off, presented with the
  contract result, the witness and the twin-build delta. Production never reads a candidate.

Witnesses are fixed per entry type and outside the worker's control: income reconciliation for
rate meaning; declared unit or a reconciling total for scale; the filing's own schedule text for
instrument type; the iXBRL presentation for format. A proposal with no witness never
auto-accepts.

Calibration: an adjudicated false alarm is recorded against the band that fired; the tolerances
file re-versions only when a quarter's false alarms exceed the version's stated rate. A
confirmed change re-learns the affected contracts from the admitted entry's `valid_from`.

Every step (proposal, verdict, admission, confirmation, retraction) is a ledger event with
worker identity, model and session.

## 7. Production consumption, twin builds, inventory

Production reads the profile only through `profile.resolve`. Consumers switch one field family
at a time: rates (spread source and scale, coupon type, rate convention) first, then identifier
format and delimiter, then monetary scale, then identity rules. Each switch replaces a heuristic
or per-CIK branch and DELETES it. Each switch is gated by a twin build of the Q1-2026 filings
(with and without), compared on accession and source context per the pilot's D1-D3 boundaries:
identical except for rows touched by accepted entries meant to change them. The rebuild runs
from cached inputs and the acceptance gate re-attests Q4-2025 and Q1-2026.

Two production defects resolve here, not by code: the identifier-spread override (21 text
spreads; gated off 2026-09-29 in commit e379e8a) is retired in favour of accepted entries or
nothing; BCRED's coupon type comes from its fixed-rate entry, not from spread presence.

The frontend does not change; profile coverage and drift status appear in the validation
artifacts the site already reads once the loop is live.

**Code-path inventory**: a script scans `pipeline/` and `scripts/` for every branch keyed on
one of the 8 CIKs (literals, per-CIK dicts, CIK-keyed override files, wrapper lookups, explicit
contexts, grammars) and emits file, line, CIK, purpose, disposition in {migrated (entry id +
twin build), exception (reason + owner), open}. Runs in CI and fails on a new per-CIK branch for
a migrated filer without an exception record. The programme is not done while any row is open.

## 8. Sub-projects and exit tests

| # | Sub-project | Depends on | Exit test |
|---|---|---|---|
| 0 | Frame: retire V13 in the closeout rubric and memory; Ares 2022-12-31 amendment scan under the lease; re-cut Stage C/D of the pilot plan to this design | none | rubric ruling written; every cohort filer has an evaluation quarter |
| 1 | Drift replay Q4-to-Q1 against q1p3 findings, shadow | pilot as built | recall and false-alarm rate per kind against the adjudicated set |
| 2 | Detector experiments (5.1) | 1 | each candidate measured on the three yardsticks; winners versioned |
| 3 | Profile document: schema, wrapper consolidation, inception entries for the 8 on Q4-2025 | 1 | criterion 1; resolver answers every field |
| 4 | Rate family live: consumers switched, twin build, defects retired | 3 | twin build clean vs signed-off Q1-2026; re-attestation passes |
| 5 | Fleet loop: B1, B2, two-tier admission, calibration | 1, 3 | one full loop on the Q4-to-Q1 queue with entries admitted and one retracted |
| 6 | Remaining families: format, monetary scale, identity; corrections migrated | 4, 5 | twin build per family; criterion 5 |
| 7 | Inventory and CI check | 6 | criterion 4 |
| 8 | Q2-2026 live | 4-7, filings fetched (owner go) | first out-of-sample quarter through the full loop |

Sub-projects 1 and 2 can start now. Each gets its own spec and plan (brainstorming,
writing-plans, subagent-driven development with Opus 5.5 subagents, reviewer per task, ledger).

## 9. Constraints carried forward

Pilot constraints remain binding: no unrequested network; write-once run roots; heavy work
only under the shared lease and never concurrent with a pytest-running task (ruling R36); no
edits under `data/output` or `frontend/public/data` from any stage; commit before real runs;
ASCII only; no inline Python; proportional test selection; semantic-diff backstop after cache
tests. New for the programme: production code changes go through twin builds and re-attestation
(section 7); the profile document is the only writable per-filer store; workers never write it.

## 10. Risks

- **Twin builds change production numbers on purpose** (sub-projects 4 and 6). Mitigation: no
  entry moves a value without evidence; every intended delta listed; re-attestation gate.
- **In-sample bands** until Q2-2026. Mitigation: tolerances versioning records seen quarters;
  Q2 is the first out-of-sample test; detector experiments widen the candidate set.
- **Unmarked filers** (BCRED, Fidelity): instrument type is agentic and value-screened.
  Mitigation: witness = schedule text; sign-off tier.
- **Fleet capacity**: two sandbox accounts, MaxParallel 2. Mitigation: ring-then-wave
  pipelining; queue ranked by fair value.
- **V13 retirement** leaves the twelve matching repairs unpublished until the first
  profile-era build. Accepted by the owner (D-seq).
