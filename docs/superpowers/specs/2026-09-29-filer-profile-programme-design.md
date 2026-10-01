# Filer-profile programme: design

Date: 2026-09-29. Status: approved in session by the owner (sections 1-6), pending written review.
Amended 2026-09-30 after written review: five gaps resolved as decisions D-families through
D-floor plus three smaller rulings (section 2.1); sections 3, 4, 5, 7, 8 and 10 carry the changes.
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

### 2.1 Decisions from the written review (2026-09-30)

| # | Gap found | Decision |
|---|---|---|
| D-families | Section 7's inventory counts CIK-keyed override files and grammars as per-filer knowledge, but section 4 gave the document slots only for the wrapper and B2 corrections. The 8 filers touch 6 to 12 override files each across nine families | Every override family gets a disposition class (section 7.1): knowledge families are the SOURCE of inception entries on their axis and are deleted per filer once the family's consumer switch lands; executable families go into the wrapper section as versioned blocks; process artifacts are excluded from the inventory by rule with the reason recorded |
| D-precedence | The wrapper stays executable and an entry can describe the same field (e.g. a rescale factor vs a scale entry); nothing said which wins | Entries are authoritative on MEANING, the wrapper only on PROCEDURE. A consistency contract (section 4.1) requires every wrapper key with a semantic counterpart to have an accepted entry that agrees with it; disagreement blocks the filer's build |
| D-corrections | Criterion 5 said corrections are "re-evaluated each quarter", but a B2 correction is keyed by `row_id` = hash(accession, context), which cannot exist in the next quarter's filing; `position_id` renumbers per rebuild | Corrections split into ONE-OFF (valid for one report date; re-evaluation = pre-image check on any rebuild of that quarter) and RECURRING (same mechanism, same filer, 2+ quarters; promoted to a partition-predicate entry with its own contract). Cross-quarter position continuity is used only by the row-continuity detector, via the registry natural key, opt-in (section 4.2) |
| D-base-build | D-seq rides twelve V13 matching repairs into the first profile-era build; criterion 2 requires the twin build to be identical except for accepted entries, and re-attestation would see matching and profile deltas together | A MATCHING-ONLY BASE BUILD lands first (sub-project 0b): cached rebuild with the repairs and no profile, semantic diff, re-attestation of Q4-2025 and Q1-2026, matching delta recorded on its own. Every profile twin build compares against that base |
| D-floor | Criterion 3 required reporting recall per kind with no minimum; measured value-range recall is 0 of 8, fill-rate 1 of 4, and a pure x100 scale flip abstains on every filer | Criterion 3 is split by kind with floors (section 3); independent totals is promoted from an experiment to a REQUIRED contract kind (section 5); sub-project 3 freezes only kinds that have reported, others are provisional |
| D-convention | The rate family switch touches all-in vs spread meaning while AGENTS.md requires the storage convention and income formula to flip atomically | The switch changes WHERE the convention is read from, not what production stores. Cash-leg storage stays until the atomic migration decided 2026-07-12 (section 7) |
| D-q2-order | The paused published-basis gate (v3) also names Q2-2026 as its calibration quarter | Order fixed: v4 gate calibration on Q2 actuals first; the drift stage runs in shadow beside it; no profile-driven value change enters the Q2 pass until sub-project 8 (section 8) |
| D-winner | Sub-project 2 had no rule for a "winner" and sub-project 3 did not depend on it | Pre-registered adoption rule (section 5.1); sub-project 3 depends on 2 for the kinds it freezes |

## 3. Exit criteria (all required)

1. **Coverage.** Every field of every one of the 8 filers has a dated, evidenced entry or an
   explicit insufficient-evidence stub; stubs are listed with the evidence that would close them.
2. **Production reads the profile.** A twin build of the Q1-2026 filings for the 8 filers is
   identical to the MATCHING-ONLY BASE BUILD (D-base-build) except for rows touched by accepted
   entries that were meant to change them, each listed with its evidence.
3. **Drift runs in the quarter pass**, with floors per kind (D-floor):
   - Structural kinds (source concept set, fill rate, format grammar, zero-position rule):
     recall >= 90% on the q1p3 adjudicated set at a false-alarm rate <= the band version's
     stated rate (currently ~2%).
   - Independent totals (section 5): detects a seeded pure scale flip (x100, x0.01) on every
     filer with a reconciling total; abstains only where no total exists, and each abstention is
     listed.
   - Semantic kinds (value range, scale via declared unit, composition, income yield): each
     either meets a floor won under the section 5.1 adoption rule or carries the label
     `detection_not_claimed` in the profile, meaning the kind is caught only by its witness at
     admission. The label is public in the validation artifacts.
   - The Q4-to-Q1 replay reports recall and false-alarm rate per kind against the q1p3
     findings; Q2-2026 runs in shadow and produces the adjudication queue the fleet works.
4. **No per-filer knowledge in code** for the 8 filers: the code-path inventory (section 7)
   has no open rows, and every override family has a disposition (section 7.1).
5. **Corrections persist** (D-corrections). Every existing B2 correction for the 8 is either a
   one-off entry whose pre-image check passes on the rebuilt quarter, or a recurring entry with
   a partition predicate and a contract that held on the latest quarter; failures and
   retractions listed with reason.

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
- **Corrections section.** Every B2 correction for the filer as an entry of one of the two
  kinds in section 4.2, with mechanism, evidence and dates.

Each document carries a version, a schema version and an event log. Readers call
`profile.resolve(cik, field, report_date, row)` and receive exactly one accepted entry or an
explicit ambiguity error (the Stage A resolver). Nothing in the document is executable except
the wrapper section.

Lifecycle, all entry kinds: supersede (genuine change: new `valid_from`; correction: back to the
old `valid_from`), retract (failed confirmation or contradicted witness), end (`valid_to`).
Nothing is physically deleted. Global rules in pipeline code stay outside the document with
their existing lifecycle; the inventory (section 7) is the only link.

Inception entries are not written from scratch. For each knowledge family in section 7.1 the
existing override file for the filer is the input: its value becomes the entry value, its
citations become the evidence references, its date becomes `valid_from`, and the file's content
hash is recorded as the entry's pre-image. A filer with no file on an axis gets a census-derived
entry or an insufficient-evidence stub.

### 4.1 Precedence between entries and the wrapper section (D-precedence)

Entries are authoritative on meaning. The wrapper section is authoritative only on procedure
(how staging executes). A wrapper key that has a semantic counterpart (rescale factors and
declared units, delimiter and prefix rules, aggregate markers, source fields, rate convention)
MUST have an accepted entry on that axis, and a **consistency contract** asserts that the
wrapper key's value and the entry's value agree at every report date the wrapper block is valid
for. The Task 7 translate adapter is the comparator. A breach blocks the filer's build; it is
resolved by superseding whichever side is wrong, with evidence, never by editing the other to
match. For the five key families the census already derives (cik, entity_name, delimiter,
aggregate_markers, fair-value source_field), the wrapper key is generated from the entry at
load time once the family's consumer switch lands, so those keys stop existing as independent
data. No other wrapper key is derived.

### 4.2 Two kinds of correction (D-corrections)

- **One-off correction.** Keyed by `row_id` (hash of accession and context). `valid_from` equals
  `valid_to` equals the report date. It records the pre-image (the extracted value before the
  correction, and the row's source fact hash). Re-evaluation runs on any rebuild of that quarter
  and means: the `row_id` still exists and the pre-image still matches. If the row is gone or the
  pre-image changed (the extraction was fixed upstream), the entry is retracted with that reason
  and the retraction is a ledger event. A one-off correction is never carried to another quarter.
- **Recurring correction.** The same mechanism on the same filer in two or more quarters (e.g.
  `all_pik_normalization` where a PIK fact is present and the cash rate is null). It is promoted
  to a partition-predicate entry: `applies_to` is the structural predicate that selected those
  rows, the value is the rule, and its contract tests the predicate's population each quarter
  (fill and concept-set on the partition). Promotion is a column-meaning admission (owner
  sign-off) because it changes rows the original review never saw.
- **Position continuity.** Cross-quarter identity of a position is needed only by the
  row-continuity detector (section 5.1). It reads the registry natural key
  (`cik | source | rawid | principal | shares`, report date removed) as an opt-in input. The
  registry stays off the production path; no correction is keyed on `position_id`.

## 5. Contracts and the drift stage

A contract is a testable expectation attached to an accepted entry. Kinds: source concept set,
fill rate, scale, format grammar, value range, rate composition (floating-share and
fixed-coupon-share criteria; dispersion recorded as evidence only, ruling R39), text agreement
(evidence only, R40), income yield (redesigned: each proof step is its own entry and contract;
reconciliation runs only where the proofs hold), and **independent totals** (D-floor): per
filer and report date, fair-value conservation against the filed total, pct-of-net-assets sum,
and income reconciliation, each as a monetary-scale contract. Independent totals is a required
kind, not an experiment, because it is the only kind that cannot abstain on a pure scale flip:
a x100 change in a rate or amount column moves the total by two orders of magnitude whatever
the per-row band says. The reconciliation code already exists in the shadow engines; the
contract wraps it. It abstains only where the filing carries no reconciling total, and every
abstention is listed against criterion 3.

Contracts frozen into inception entries before sub-project 2 reports on their kind carry
`status_basis = provisional` and are re-versioned, not edited, when the experiment lands.

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

**Adoption rule (D-winner), pre-registered before any experiment runs.** A candidate detector
is adopted as a contract kind when, on the three yardsticks, it (a) reaches recall on the
Q4-to-Q1 replay at least equal to the existing kind for the same drift class, or >= 50% where no
kind exists; (b) stays within the current band version's stated false-alarm rate on the
all-quarter quiet pairs; and (c) detects its own seeded perturbation at a fraction <= 0.20 of
rows on at least 6 of 8 filers. A candidate that fails (c) but passes (a) and (b) is recorded
as evidence-only. Winners land as a NEW tolerances version with the three measurements; the
current version is never edited. Losers are recorded with their numbers so the experiment is
not re-run.

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

**Base build (D-base-build).** Before any twin build, sub-project 0b lands the matching-only
base: a cached rebuild with the twelve V13 matching repairs and no profile consumer, followed by
`scripts/diff_outputs.py --semantic` and `scripts/reattest_quarters.py check` for Q4-2025 and
Q1-2026. The matching delta is recorded in the changelog on its own. If re-attestation regresses
from the repairs alone, that is a stop-and-report event found in isolation, before any profile
delta exists. Every twin build in sub-projects 4 and 6 compares against this base, never against
the pre-V13 wrapper build.

**Rate convention storage (D-convention).** The rate family switch changes where the filer's
stated convention (cash leg vs all-in) is read from: the `rate_convention` entry replaces the
`data/overrides/rate_convention/` file for that filer. It does NOT change what production
stores: `interest_rate` remains the cash leg and `pik_rate` separate until the storage
convention and the `index_returns` income formula migrate atomically, per the 2026-07-12
decision. That migration is outside this programme and is listed as an inventory exception.

Two production defects resolve here, not by code: the identifier-spread override (21 text
spreads; gated off 2026-09-29 in commit e379e8a) is retired in favour of accepted entries or
nothing; BCRED's coupon type comes from its fixed-rate entry, not from spread presence.

### 7.1 Override family disposition (D-families)

Measured 2026-09-30 on the 8 pilot filers (`grep -rl <cik> data/overrides`):

| Family | Pilot filers | Class | Disposition |
|---|---|---|---|
| `rate_convention/` | 2 | knowledge | Source of the rate-meaning inception entry (convention, column semantics, citations); file deleted per filer after the rate family switch |
| `identifier_rate_grammars/` | 5 | knowledge | Source of the identifier format and dialect entry; deleted after the format family switch |
| `identifier_anchors/` | 5 | knowledge | Source of the anchor-dialect entry (same axis); deleted with the grammars |
| `bdc_aggregate_row_overrides.json` | 2 | knowledge | Source of partition-structure entries (subtotal exclusions as `applies_to` predicates); the filer's records deleted after the identity family switch |
| `bdc_xbrl_oracle_exceptions.json` | 1 | knowledge | Source of a reconciliation-scope entry with the exception's evidence; the filer's record deleted after the identity family switch |
| `identifier_spread_corrections.json` | 0 of 8 (Crescent, Antares) | knowledge | Already gated off; retired per section 7 when those filers enter the cohort |
| `agent_b2_corrections/` | 3 | knowledge | Section 4.2 entries; directory entries for the filer deleted once criterion 5 holds |
| `bdc_xbrl_wrappers/` | 8 | executable | Wrapper section (D-consolidate); file deleted per filer at consolidation, loader redirected |
| `agent_investigate_rules/` | 6 | executable | Promoted per-CIK rules become a second versioned block in the wrapper section, same lifecycle; rules that are expressible as entries are converted and the block entry retired |
| `agent_anchor/` | 8 | process artifact | Excluded from the inventory: fleet output, regenerated per pass, not knowledge |
| `wrapper_cohorts/` | 8 | process artifact | Excluded: cohort membership manifest, not per-filer semantics |
| `position_id_registry/` | 1 | process artifact | Excluded: opt-in matching state, read only by the row-continuity detector |
| `enforcement_registry/`, `bdc_xbrl_html_section_bridges/`, `fund_highlights_wrappers/`, `row_corrections.csv`, `entity_overrides.json` | 0 of 8 | n/a | No pilot filer present; classified when a filer that uses them enters the cohort |

The inventory script (below) reads this table: a knowledge-family file for a migrated filer
that still exists is an open row; a process-artifact family never produces a row. A family
added later without a class here fails the CI check.

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
| 0b | Matching-only base build (D-base-build): cached rebuild with the V13 repairs, semantic diff, re-attestation of Q4-2025 and Q1-2026 | 0 | both quarters re-attest; matching delta recorded alone in the changelog |
| 1 | Drift replay Q4-to-Q1 against q1p3 findings, shadow; independent-totals kind added (section 5). DONE 2026-10-01: replay sp1-replay-full2-20261001t0100z; structural kinds NO_POSITIVES on the pair (FA upper fill 0.0217, concept 0.0054), format_grammar FAIL, totals NOT MET (1/8 measurable) (census not on the published basis for 7 filers), others NOT_CLAIMED; see changelog 2026-10-01 | pilot as built | recall and false-alarm rate per kind against the adjudicated set; scale-flip detection listed per filer |
| 2 | Detector experiments (5.1) under the pre-registered adoption rule | 1 | each candidate measured on the three yardsticks; winners and losers versioned with their numbers |
| 3 | Profile document: schema, family disposition applied (7.1), wrapper consolidation, consistency contract (4.1), inception entries for the 8 on Q4-2025 from the existing override files | 1; 2 for any kind it freezes as non-provisional | criterion 1; resolver answers every field; consistency contract holds on all 8 |
| 4 | Rate family live: consumers switched, twin build vs base, defects retired, `rate_convention` files deleted for the 8 | 0b, 3 | twin build clean vs base build on signed-off Q1-2026; re-attestation passes |
| 5 | Fleet loop: B1, B2, two-tier admission, calibration | 1, 3 | one full loop on the Q4-to-Q1 queue with entries admitted and one retracted |
| 6 | Remaining families: format, monetary scale, identity; corrections migrated as section 4.2 kinds; knowledge files deleted per family | 4, 5 | twin build per family vs base; criterion 5 |
| 7 | Inventory and CI check, reading the 7.1 table | 6 | criterion 4 |
| 8 | Q2-2026 live, after the v4 gate calibration on Q2 actuals (D-q2-order) | 4-7, filings fetched (owner go), gate v4 recorded | first out-of-sample quarter through the full loop |

Sub-projects 0b, 1 and 2 can start now; 0b takes the lease and runs alone (R36). Each
sub-project gets its own spec and plan (brainstorming, writing-plans, subagent-driven
development with Opus 5.5 subagents, reviewer per task, ledger).

Q2-2026 ordering (D-q2-order): the published-basis gate's v4 calibration on Q2 actuals runs in
the normal quarter pass first; the drift stage runs in shadow beside it in the same pass; no
profile-driven value change enters production for Q2 until sub-project 8 opens. The two
programmes share the quarter but not the numbers.

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
- **V13 retirement** leaves the twelve matching repairs unpublished until the base build
  (sub-project 0b). Accepted by the owner (D-seq); attribution risk removed by D-base-build.
- **Inception from existing override files** (D-families) inherits any error those files carry.
  Mitigation: each inherited entry records the file's content hash as its pre-image and gets its
  contract evaluated on Q4-2025 before acceptance; an entry whose contract breaches at inception
  is admitted as candidate only.
- **Consistency contract false positives** (D-precedence): a wrapper key and an entry can differ
  legitimately in representation (substring markers vs observed labels, per the frozen M1
  semantics). Mitigation: the comparator uses the Task 7 translate semantics, and a representation
  mismatch is `insufficient_evidence`, not breach, until the key family is derivable.
- **Recurring-correction promotion widens scope** (D-corrections): a predicate can select rows
  the original review never saw. Mitigation: promotion is owner sign-off tier and the twin build
  lists every newly touched row.
- **Floors are set before the detectors exist** (D-floor). The 90% structural floor and the
  6-of-8 seeded rule are chosen from Stage B2 measurements, not validated out of sample.
  Mitigation: floors live in the tolerances file, versioned like bands; Q2-2026 is the first
  out-of-sample check of the floors themselves.
