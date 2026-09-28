# Filer Profile Pilot: census-derived, bitemporal per-CIK knowledge store

Status: v4, implementation-contract corrections requested 2026-09-28.
The v3 approval and seven owner scope rulings (section 14) remain in force;
this revision corrects measurement and execution requirements, not scope.
Supersedes nothing; extends
`docs/oxford_ledge_review/2026-09-17_oxford_ledge_comparison_and_remediation_loop.md`
sections 13-14 (which remain NOT FINALISED) with a bounded, measured pilot.

Revision v2 (2026-09-28, same day): six review comments accepted by the owner
and folded in; see section 13 for the list and where each landed. The
material changes are: parity is measured at three pinned pipeline boundaries
instead of one (6.4); census output is tagged `inherited` vs `derived` and the
census needs new collectors (6.1); the entry envelope gains a transaction-time
end so retrospective corrections and real convention changes are distinct
(6.2); every detector and the graduation test have an explicit
`insufficient_evidence` outcome (6.2, 6.5); metrics are reported against fixed
denominators with censoring (9); and the pilot runs in a separate worktree
because the V13 closeout rubric freezes `scripts/` and `tests/` (2, 10).

Revision v4 (2026-09-28): implements the second review. The plan is an
acceptance-driven implementation sequence rather than untested source-code
templates. Complete fact collection, executable partition contracts,
source-backed graduation, connected parity, historical as-of semantics,
literal metric definitions and protection of the real data roots are required.
Neither the pilot nor its tests have run as part of this document revision.

Revision v4.1 (2026-09-28): four integration corrections verified against the
repo after the v4 review: the shared lease is `heavy_lock(candidate)` and
needs a pilot pseudo-candidate directory (2, 10); D1 is a pinning boundary
because the production parser takes no profile parameters (6.4); decimal
exactness is defined after a stated canonicalisation (6.4); the amendment
selection policy lives in `scripts/run_context_census.py`, not the pipeline
(6.4). Adds staged go/no-go checkpoints (8) and two open questions (12).

## 1. Problem

Per-CIK knowledge is spread across thirteen override layers plus 124 CIK
literals in `pipeline/*.py`. None of the 78 wrappers, 70 rate grammars or 42
rate-convention files carries a date. Corrections that are really filer
semantics (16 of 38 live B2 leaves are `comparative_period_filter`; 73 of 154
investigate rules are `row_exclusion`) are written as quarter-scoped rows
because there is no dated place to declare them, so they expire and re-fire
(TCW DL VII, Q1-2026, +54% re-escalation). Wrappers are authored by an agent
from a hand-read profile, freeze at version 1 and drift.

The name "wrapper" is wrong: the object does not wrap or parse HTML. It records
how to interpret one filer's XBRL. This spec calls it a **filer profile**.

Measured against the literature (Compustat-style per-filer mapping, DQC
rules-as-data with a precision bar, holistic evidence accumulation, weak
supervision with abstain, LLM generate-filter with a generalisability test,
bitemporal modelling, data contracts), the repo is at or past the bar on
provenance, reconciliation and the acceptance gate, and below it on the
knowledge store: no census stored, no two-clock entries, no column contracts,
no generalisability filter. This pilot measures how much of that store can be
derived rather than authored, and how much of it survives from one quarter to
the next.

## 2. Classification and scope

Architectural direction, executed as a **measurement pilot**. Shadow only.

- Branch `filer-profile-pilot` off `ensemble-fp-experiment`. Build on that
  base now; rebase onto `main` after the V13 merge (the pilot only adds new
  files, so conflict risk is low). No edits under `pipeline/`.
- **Start ruling (owner, 2026-09-28).** The pilot starts now, in the
  worktree, under the heavy-job restriction. The V13 build in flight is the
  LAST refactor rebuild before the pilot's heavy stages. If that run does not
  finalise V13, the refactor programme PAUSES rather than starting another
  build; the pilot takes the heavy lock. This ruling is recorded here and in
  the changelog; the closeout rubric lives on the sealed branch and is not
  edited from the pilot worktree.
- Pilot artifacts live under `data/pilot/` (git-ignored, added to
  `.gitignore` in this commit), not `scratch/`, so profiles and results
  outlive the session-scratch convention and can feed the migration spec.
- **Isolation from the V13 closeout.** Avoiding `pipeline/` is not enough.
  The closeout rubric
  (`docs/production_stack/2026-09-28_v13_closeout_rubric.md`, rule 1) freezes
  `pipeline/`, `scripts/`, `tests/`, `schemas/`, `data/overrides/` and
  `data/reference/` in the sealed checkout until the handoff is written; any
  edit there voids the seal and restarts the full suite. The pilot adds files
  under `scripts/` and `tests/`, so it MUST run in a separate git worktree
  (`.claude/worktrees/filer-profile-pilot`, created 2026-09-28) or start only
  after the V13 handoff. The sealed checkout is never touched by pilot work,
  including branch switches. The rubric's heavy-job lock still applies across
  worktrees (section 10).
- Code under `scripts/profile_pilot/`; tests under
  `tests/test_profile_pilot_*.py`. Pipeline modules are imported read-only
  (`context_inventory`, `bdc_xbrl_wrapper`, `config`, cache readers).
- Reads: cached XBRL instances, `data/output/bdc_holdings.csv`,
  `data/output/private_markets_holdings.csv`, `data/overrides/**`.
- Measurement writes: `<data_root>/pilot/filer_profile/<run_id>/` only.
  Artifact paths below are relative to that resolved per-run root. Two
  coordination writes outside it are permitted and nothing else: the
  existing shared programme lock file (`data/programme/heavy.lock` in the
  main checkout) and the pilot pseudo-candidate directory
  `data/programme/candidates/pilot-filer-profile-<run_id>/` that
  `pipeline.programme.runner.heavy_lock(candidate)` requires (section 10).
  No `data/output/`, `frontend/public/data/`, baseline, threshold, registry
  or wrapper change.
- No network. No model calls on any path. Residuals are recorded as packet
  stubs, not dispatched.

Output is five numbers and a recommendation (section 9), not production code.

## 3. Goals

1. Measure **derivation rate**: how much of each hand-authored wrapper the
   deterministic census reproduces from filing structure alone, with anything
   the census inherits from existing per-CIK code or authored files counted
   separately (6.1).
2. Measure **quarter-over-quarter re-use**: a profile derived from a filer's
   first quarter applied to its second quarter; which sections carry unchanged,
   which carry with a form-type qualifier, which must be rewritten.
3. Measure **graduation yield**: how many existing B2 leaves and investigate
   rules for the pilot CIKs would pass a generalisability test and become dated
   profile declarations.
4. Establish **compatibility parity**: profile-driven interpretation
   reproduces production rows and FV for the pilot fund-quarters at each of
   three pinned pipeline boundaries (6.4). Parity measures compatibility with
   what production does today; it is not evidence that production is correct.
5. Produce a **profile schema v0** (entry envelope with two clocks) that the
   later migration can adopt or reject on evidence.

## 4. Non-goals

- Change detection on real convention transitions. The known dated events
  (BCRED 2025-12-31 identifier suffix, Stepstone 2025q4 scale, TCW 2026-Q1
  affiliation axis) fall outside the pilot fund-quarters. The all-quarter
  extension (section 6.6) records where a Q1-derived profile first breaks, but
  the pilot does not build detectors 2-3 as gating machinery.
- Withholding in the public export.
- Position registry on the production path.
- All-in rate storage migration.
- Migrating any CIK literal out of `pipeline/*.py`.
- Replacing wrappers for the eight CIKs, even if parity holds.

## 5. Pilot cohort

Eight CIKs chosen to span the repo's own format diversity (22 delimiter x
staging-strategy combinations, 12 grammar signatures, cash-leg vs all-in).
Fund-quarters are each filer's first two with current-period rows in
`bdc_holdings.csv` (queried 2026-09-28).

| CIK | Filer | Q1 | Q2 | Rows Q1 / Q2 | Q1->Q2 form | Stresses |
|---|---|---|---|---|---|---|
| 0001287750 | Ares Capital | 2022-09-30 | 2022-12-31 | 1,037 / 1,059 | 10-Q -> 10-K | comma format; subtotal leak; comparative periods; 2 B2 + 3 inv |
| 0001803498 | Blackstone Private Credit (BCRED) | 2022-09-30 | 2022-12-31 | 1,099 / 1,354 | 10-Q -> 10-K | no delimiter; `source_encodings`; JV scope; 6 inv |
| 0001901037 | Stellus Private Credit | 2022-09-30 | 2022-12-31 | 62 / 70 | 10-Q -> 10-K | **control**: wrapper only, zero corrections |
| 0001715933 | TCW Direct Lending VII | 2023-03-31 | 2023-06-30 | 89 / 84 | 10-Q -> 10-Q | affiliation-axis views; cash scope; 4 inv |
| 0001920453 | Fidelity Private Credit | 2023-03-31 | 2023-06-30 | 26 / 59 | 10-Q -> 10-Q | `hierarchy_leaf_guard`; 5 override layers; ramp-up noise |
| 0001860424 | Onex Falcon Direct Lending | 2023-06-30 | 2023-09-30 | 80 / 80 | 10-Q -> 10-Q | all-in rate convention; explicit-member rule; 5 layers |
| 0001950803 | Stepstone Private Credit | 2023-09-30 | 2023-12-31 | 158 / 282 | 10-Q -> 10-K | pipe + `prefix_strip`; only `segment_assertions` in fleet; rescale as code |
| 0001588272 | NexPoint Capital | 2023-09-30 | 2023-12-31 | 57 / 54 | 10-Q -> 10-K | position identity as typed member on another axis (`explicit_contexts.py`) |

Form types are inferred from report-date month and must be confirmed from the
cached accession's form type during census; record the actual value.

Five of eight Q1->Q2 pairs cross a 10-Q -> 10-K boundary. That is the harshest
re-use test available and is intentional; results are split by form type
(section 9) so annual-format differences are not read as drift.

Alternate control if Stellus proves unusable: 0001377936 Saratoga
(`issuer_bridge` strategy, wrapper only, first quarter 2024-11-30).

**Quarter count (owner ruling).** Primary M2/M4 measurement uses the two
quarters per CIK tabled above. M1 additionally uses the authoring quarter;
M3 checks available out-of-scope quarters and M5 observes the fixed Q1
profile over later quarters. These observational scans do not add primary
training/evaluation pairs. A follow-on extends the primary experiment to
three, then four quarters to validate time-constancy.

**Same-era derivation (owner ruling).** In addition to the Q1 profile, a
second profile is derived from each wrapper's own authoring quarter (the
quarter the hand-authored wrapper was written against, read from the wrapper
file or its git history). Pin the wrapper version and the source accession
it was authored against. A first-commit date alone is not proof of the
authoring quarter; if evidence is missing, label that comparison unavailable.
Do not compare a revised wrapper to the first version's authoring quarter
and call that same-era. M1 is reported for both, so a low Q1 derivation
rate can be attributed to three years of filer drift or to the census, not
left ambiguous. Roughly eight extra census runs.

Evidence check (2026-09-28): wrapper v3 JSON carries `version` and
`source: bdc_xbrl` but no target accession or quarter; `known_edge_cases[*]
.first_seen_quarter` names an edge case, not the authoring instance. Under the
rule above, same-era M1 is expected to be `unavailable` for most or all eight
CIKs. Section 12 question 4 asks the owner whether "latest cached filing whose
filing_date precedes the wrapper's last version-bump commit" may be admitted
as a labelled lower evidence tier, or whether same-era M1 is dropped.

## 6. Pilot architecture

```
cached instance (Q1)                      cached instance (Q2)
      |                                          |
      v                                          v
 [A] census ------------------------------> [A] census
      |                                          |
      v                                          |
 [B] derive profile v0 (dated valid_from=Q1)     |
      |                                          |
      +-- compare vs hand-authored wrapper -----> derivation rate
      |                                          |
      v                                          v
 [C] contracts (expectations from Q1) -----> evaluate on Q2 -----> re-use / breaks
      |                                          |
      v                                          v
 [D] interpret Q1 and Q2 rows via profile --> compare at three pinned
     boundaries (extraction / staging / unified) --> compatibility parity
      |
      v
 [E] graduation test over existing B2 leaves + investigate rules --> yield
      |
      v
 [F] all-quarter extension: apply Q1 profile read-only to every later quarter,
     record first-break quarter per section --> re-use half-life
```

Each box is one module in `scripts/profile_pilot/` with its own tests and its
own JSON output. No box calls a model.

### 6.1 [A] Census (`census.py`)

Deterministic structural fingerprint of one cached instance, stored as
`census/{cik}/{report_date}.json` under the per-run root.

Content, per instance:

- accession, form type, period, whether an amendment supersedes it.
- axes present; member counts per axis; typed vs explicit members.
- per canonical field (issuer, instrument, fair_value, cost, principal,
  interest_rate, basis_spread, pik_rate, maturity, industry, affiliation,
  non-accrual): which concepts carry it, fill rate per concept, extension vs
  standard namespace.
- identifier-string signature: delimiter candidates with prevalence, segment
  count distribution, prefix vocabulary, trailing-ordinal prevalence.
- contexts whose value equals the sum of other contexts under one axis
  (subtotal candidates), with the axis.
- context groups with identical fact values under different axes
  (presentation-view candidates).
- comparative-period contexts (period != report_date) and how they are
  distinguished.
- where non-accrual / PIK / pledged status appears: footnote marker, dimension
  member, text, or absent.
- fund-level totals present (total investments FV, total assets, net assets,
  interest income) and their concepts.

The new collector reads the complete cached instance once using bounded,
network-disabled XML parsing. It enumerates every context's instant or
duration dates; `DocumentPeriodEndDate` identifies the filing, not its
comparative periods. Retain fact QName, context, raw value, nil/invalid
status, unit/currency, decimals, duration, dimensions and source identity.
Capture rates, dates, text/status facts, footnote resources and their links,
and fund-level facts in addition to monetary facts. Use the pipeline's
canonical field names (`principal_amount`, `maturity_date`, `shares_held`)
consistently. A collector failure, unsupported text channel or unmapped
concept is explicit missing evidence, never evidence of non-disclosure.

Imported context roles and concept mappings are inherited interpretations.
Keep raw facts independently of whether the existing classifier recognises
them; an unresolved source context cannot vanish from the census. Record
dependencies at entry level so an inherited selector cannot silently become
unaided derivation. Source-role conflicts and conflicting same-field facts
remain unresolved rather than taking the first fact in document order.

Reuses `pipeline/context_inventory.py` for context classification and the
existing cache readers.

**What is inherited, and what must be newly collected.** Two corrections to
the original "nothing here is new analysis" claim:

- `context_inventory.py` imports `explicit_member_dimensions` from
  `pipeline/explicit_contexts.py`, which is per-CIK authored identity code
  (NexPoint, Onex). Any census field that depends on it is knowledge the
  pilot inherits, not derives. The same holds for
  `identifier_rate_grammars/*.json` (authored by the identifier-grammar
  skill) when used inside contracts. Every census and profile entry carries a
  `provenance` in {`derived`, `inherited`}, with `inherited_from` naming the
  module or file. Inherited entries are reported separately in M1 and never
  counted toward derivation.
- `context_inventory.scan_instance` keeps only facts whose context period
  equals the target quarter (`if ctx["period"] != quarter: continue`) and only
  the monetary/position concepts in its field map. It therefore does not
  supply the comparative-period contexts, rate and spread facts, footnote and
  status markers, or fund-level income concepts listed above. Those need new
  collectors in `census.py`. This is real collection work and is priced as
  such in section 8; it is not a wrapper of the existing scan.

**Detector outcomes.** Every structural detector emits one of `candidate`,
`resolved`, or `insufficient_evidence`, never a bare assertion:

- Equal fact values under different axes do NOT establish duplicate
  positions; two tranches can carry identical balances. A presentation-view
  group stays `candidate` until source evidence establishes the same
  position/tranche, economic date, currency and accounting scope, and the
  differing dimension is an alternate presentation. Equal borrower text,
  instrument type and maturity alone are insufficient. Never choose the
  canonical view by context-ID order or fewest dimensions.
- Sum equality does NOT establish a subtotal. A sum-of-others context stays
  `candidate` until the identifier text or member label also reads as a
  heading/total, or the wrapper's aggregate markers agree (that agreement is
  then `inherited`). The children must also have a demonstrated structural
  relationship on the same entity/date/currency/scope basis. Arbitrary
  subset-sum searches are not evidence of that relationship.
- A missing concept does NOT establish non-disclosure. Absence may be
  recorded only as `not_observed_in_complete_instance` after the supported
  concept, identifier, text and footnote channels have been inspected.
  It is not a statement about the full filing or HTML schedule. If any
  relevant channel is unsupported or incomplete, `non_disclosure` is
  `insufficient_evidence`; a failed regex match is not a completeness proof.

Unresolved candidates are recorded as packet stubs, not promoted to profile
entries.

### 6.2 [B] Profile derivation (`profile.py`)

Builds a profile v0 from a census. Sections follow the oxford-ledge doc 13.4
plus two added in the 2026-09-28 discussion (`non_disclosure`,
`fund_level_concepts`); the entry envelope adds author, status, transaction
time and a regression pin to the doc's three properties:

| Section | Derived from census | Pilot status |
|---|---|---|
| identifier_format | delimiter / segment signature | derived |
| subtotals_and_headings | sum-of-others contexts + prefix vocabulary | derived |
| presentation_views | identical-values-under-different-axes groups | derived |
| comparative_periods | period != report_date contexts | derived |
| column_contract | concept -> field with fill rates | derived |
| footnote_conventions | non-accrual / PIK location | derived |
| position_identity | axis carrying the position member | derived |
| non_disclosure | complete-instance absence with an explicit evidence boundary | derived or insufficient_evidence |
| fund_level_concepts | fund-total concepts | derived |
| accounting_scope | -- | stub (structure cannot settle; packet) |
| anchors | -- | copied from `agent_anchor` if present, else stub |
| lifecycle | -- | stub |

Every entry uses one envelope:

```json
{
  "entry_id": "0001901037:identifier_format.delimiter:v1",
  "key": "identifier_format.delimiter",
  "value": " | ",
  "form_type": null,
  "applies_to": null,
  "valid_from": "2022-09-30",
  "valid_to": null,
  "recorded_at": "2026-09-28T14:02:11Z",
  "recorded_until": null,
  "supersedes": null,
  "supersession_kind": null,
  "author": "census",
  "status": "derived",
  "provenance": "derived",
  "inherited_from": null,
  "support": {"kind": "prevalence", "numerator": 61, "denominator": 62},
  "evidence": [{"kind": "context_ids", "accession": "...", "ids": ["c-12", "c-13"]}],
  "regression_pin": null
}
```

- `author` in {census, agent, human}. `status` in {derived, proposed,
  verified, promoted, retired}. Pilot only writes `census` / `derived`.
- `form_type` null means all forms; a non-null value narrows the entry.
- **`applies_to` (partition predicate).** Null means every row of the
  filing. A non-null value is a structural predicate naming the sub-population
  the entry governs: an axis member, a concept carrying the field, a segment
  count, a prefix vocabulary, or the grammar dialect that parses the row.
  This is how one filing that uses format A for part of a schedule and
  format B for the rest is represented: two entries with the same `key`,
  disjoint `applies_to`, same valid range. Rules:
  - Row position in the instance is never a predicate. XBRL contexts are
    unordered and instance order is tooling-dependent.
  - The census emits a multi-modal signature (for example two delimiter
    candidates each above 20% prevalence) as a **partition candidate** and
    searches the structural discriminators above. If none separates the
    modes, the result is `insufficient_evidence` and a packet stub, never a
    row list.
  - Three problems, three mechanisms: change across quarters uses
    `valid_from`; change across filing types uses `form_type`; mixed format
    within one filing uses `applies_to`.
  - Evaluate predicates against source rows, not by JSON equality. Resolve
    matching partition-specific entries before the null-partition fallback;
    within that tier prefer the exact form over the all-form fallback.
    Valid-time and transaction-time intervals must both match. The null
    partition/form entries are explicit fallbacks, not conflicts with their
    more specific entries. Two equally specific applicable entries are an
    error, including different predicate objects that select the same rows.
    Unsupported or unprovably disjoint predicates remain unresolved.
- **Two clocks, kept apart.** `valid_from` / `valid_to` are report dates
  (valid time: when the filer's behaviour held). `recorded_at` /
  `recorded_until` are wall clock (transaction time: when we believed the
  entry). Use half-open intervals on both clocks (`from <= query < to`),
  with null ends meaning unbounded. Assertion bodies and source evidence
  are immutable. Append assertion/retraction events with a transaction
  timestamp; interval end fields in JSON are materialized views of that
  history, not in-place rewrites of the original assertion. Two events:
  - **Retrospective correction** ("we were wrong about this filer all
    along"): retract the old assertion at transaction time T and append its
    replacement covering the same valid interval, with fresh evidence and
    `supersession_kind = "correction"`. A query before T still sees the
    original assertion.
  - **Genuine convention change** ("the filer changed in quarter Q"): the old
    open-ended assertion is retracted at transaction time T. Append a
    replacement for its historical interval ending at Q (exclusive), and
    an assertion for the new value starting at Q, both recorded at T. The
    original unbounded assertion remains visible to queries before T.
    Preserve any pre-existing finite end and require Q to be inside the
    affected interval. Do not compute `Q-1` as a day or quarter.
  - Validate unique version IDs, evidence references, ordered clock bounds
    and unambiguous resolution for every historical transaction slice,
    including form and partition applicability. Do not validate only the
    currently live entries.
  - The schema supports an as-of query ("what did we believe about report
    date R at wall-clock time T"), and the pilot ships synthetic tests for
    both events, their exact boundaries, and a correction after a change.
    A small pure resolver supports validation, contracts and translation;
    a database query service is out of scope.
- `confidence` is replaced by `support`, a measured quantity with a named
  estimator (prevalence numerator/denominator, or a context count). Census
  entries carry no unmeasured score.
- `regression_pin` is null in the pilot and documented as the slot for the
  later migration's per-entry regression test reference; it is not populated.
- Profile JSON is written to `profiles/{cik}/{era}.json` under the per-run
  root, with separate `q1` and `same_era` artifacts. Schema at
  `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`.

**Derivation-rate comparison**: for each key in the hand-authored wrapper
(`dispatch.*`, `identifier_format.*`, `staging.strategy`, `source_encodings.*`,
`archetypes`, `invariants`, `segment_assertions`), classify the census
proposal as exactly one of:

- `exact` (independently derived value and executable meaning equal the
  wrapper value under a predeclared canonical representation),
- `partial` (same shape, different value or subset),
- `inherited` (census reproduces the key only via inherited code or files,
  section 6.1),
- `unresolved` (detector returned `candidate` or `insufficient_evidence`),
- `miss` (census proposes nothing or something contradictory),
- `not_derivable` (wrapper key has no structural counterpart, e.g.
  `known_edge_cases` prose).

The denominator is fixed as all wrapper keys for that CIK, listed once in
`inventories/wrapper_key_inventory.json` before any census runs. Report per CIK
and per section.

Prefix presence is not an exact prefix-to-family mapping; observing a fund
total is not derivation of its reconciliation field, basis or tolerance.
Do not look at the comparison wrapper while generating a derived value.
Freeze supported key comparisons before measurement. Keys not implemented
by this pilot are `unresolved` with reason `not_implemented`, not inherently
`not_derivable`. Same-era and Q1 results have separate artifact keys and
cannot overwrite each other in the summary.

### 6.3 [C] Contracts (`contracts.py`)

Per filer, per canonical field, **per partition** (`applies_to`, section
6.2), expectations learned from Q1 census + profile: source concept(s),
fill-rate band, format grammar (from the existing rate grammar if present),
scale, value range, form_type. Evaluated on the Q2 census and Q2 interpreted
rows. Output per (cik, field, partition): `holds`, `holds_with_form_type`,
`breach` or `insufficient_evidence`, with expected vs observed. Without the
partition dimension a filing
that is half format A and half format B would read as a 50% grammar breach
when both halves are regular.

Learn partitions and their predicates from Q1 only, freeze them, then apply
those predicates to Q2 rows before computing every expectation. A mixed
format without an evidenced discriminator is unresolved, not a default
whole-filing contract. Numerical scale must describe the field's units and
deterministic conversion to its canonical unit; standard versus extension
namespace does not identify scale. Ambiguous unit/scale evidence is
`insufficient_evidence`. Format contracts name the field and dialect and
retain violating source-row keys; delimiter/segment-count compatibility alone
does not prove a rate grammar.

**Minimal suite (owner ruling: minimal now, extend if the pilot works).**
The pilot ships exactly these contract kinds:

| Contract | What it catches | Exists today? |
|---|---|---|
| source concept set | field moved to a different concept | no per-filer form; `CONCEPT_MAP` is global |
| fill rate band | field silently stopped being tagged | no |
| scale | percent vs decimal vs bps for the whole partition | partly: `F12` in `oracle_checks.py` is a global median test for rates > 100; rate grammars coerce a `bps` field type |
| **format grammar per row** | "this field is expected as XX.XX% but this row reads as base + XXX bps" (or the reverse); any row whose text does not parse under the partition's declared dialect is flagged, and a cluster of such rows is a partition candidate | partly: `identifier_rate.apply_grammar` + `evaluate_invariants` parse per row and compare to the XBRL twin, but only for CIKs with an authored grammar and never as a declared per-filer expectation. No production check today says "declared format for this filer is A, this row is B" |
| value range | rate/spread outside the filer's own history | partly: `C05` global max-rate cap |
| **fund-income yield** | rate semantics (cash leg vs all-in) drifting: portfolio yield implied by the rates vs interest income from `bdc_fund_income` | yes as a signal (`rate_convention` S2), reused not rebuilt |

Deferred, listed as unchecked in section 11: non-accrual count against
filing text; footnote-location contracts; position-identity contracts.

Fund-income yield reuses the existing S2 calculation and its evidence limits
with explicit pinned inputs. It must align duration, currency, accounting
scope and rated-book coverage, and use the declared cash/all-in convention
without adding PIK twice. A new simplified formula is not a substitute.
Unknown semantics or insufficient coverage produce `insufficient_evidence`.
Any form-type qualifier must be evidenced before evaluating Q2: an observed
form change does not grant an extra tolerance allowance after a breach.

Pilot does not gate or withhold anything; it records. Tolerances are fixed
before any Q2 evaluation and written to `inventories/contract_tolerances.json`:

| Expectation | Tolerance (Q1 >= 50 positions) | Tolerance (Q1 < 50 positions, `low_history`) |
|---|---|---|
| source concept set | identical set | identical set |
| fill rate | +/- 10 percentage points | +/- 25 percentage points |
| scale | identical | identical |
| value range (rates, spreads) | Q2 p5-p95 inside Q1 min-max widened by 25% | same, widened by 50% |
| format grammar | every Q2 identifier parses | >= 90% parse |

These are reporting bands, not pass/fail bars; the pilot is measurement.
Changing a band after seeing Q2 results requires a new run/version with the
reason and prior results preserved. It cannot overwrite the frozen primary
measurement or be presented as a predeclared result.

### 6.4 [D] Interpretation and compatibility parity (`interpret.py`, `parity.py`)

The v1 text compared profile output against `bdc_holdings.csv` by `row_id`
and parsed `issuer_name`. That comparison cannot be made: `bdc_holdings.csv`
carries the raw `investment_identifier`, `accession_number` and
`src_context_id` but no `row_id` and no parsed issuer; `row_id` first appears
in `private_markets_holdings.csv`. Wrappers apply in `staging_bdc.py` and
downstream; B2 leaves and investigate rules apply in `staging_bdc.py` (raw
exclusions) and `unified_holdings.py` (promoted plan). One comparison across
those stages would mix raw extraction with corrected, unified output.

Parity is therefore three separate comparisons, each against a pinned
reference artifact whose path, git HEAD and SHA-256 are recorded in the result:

| Boundary | Profile side | Reference artifact | Row key | Compared |
|---|---|---|---|---|
| D1 extraction | cached-only production extraction (`bdc_filings._parse_single_filing` + `_deduplicate_bdc_holdings`) with explicit inherited mechanisms; the parser accepts NO profile parameters, so the profile side equals production | pinned `bdc_holdings.csv` accession slice, including comparative facts | accession/context/period with collision checks | row multiset, FV, cost, principal, raw rates and identifier |
| D2 staging | the actual D1 frame through the profile wrapper adapter and production staging, including raw-stage corrections | independently materialised production staging from the pinned raw slice | source observation key with period lineage | row multiset, FV, parsed issuer, instrument, industry, affiliation |
| D3 unified | the actual D2 frame through ordinary unified transformations, ordered correction replay and final ID assignment | pinned `private_markets_holdings.csv` slice | independently generated `row_id`, checked against source lineage | row multiset, per-row FV, classification |

Rules:

- **D1 is a pinning boundary, not a profile metric.** Wrappers apply at
  staging, and `_parse_single_filing` has no profile input, so D1 is exact by
  construction unless the pinned accession, the cached instance, or the
  parser version differs from the one that built `bdc_holdings.csv`. M4 must
  label D1 as "reproducibility of the pinned extraction" and report any D1
  divergence as a source-selection or parser-version finding. A 16/16 D1 is
  not evidence about the profile. Profile effects are first visible at D2.
- Corrections are replayed at their real production stages and in their real
  order, never inferred: raw comparative selectors run before staging loses
  `period`, and post-staging corrections run at the unified boundary. D3
  has two complete branches with otherwise identical inputs, one with all
  applicable corrections enabled and one without. List the selectors,
  selected source rows, additions and audit evidence for each application.
  Never attach reference output rows or borrow their IDs to force agreement.
- `interpret.py` does not re-implement extraction. Where a profile section
  has a wrapper-v3 equivalent, the profile is translated to wrapper form and
  the existing loaders are pointed at an isolated pilot directory
  (`reload_wrapper_specs(override_dir=...)`, staging config loader). Sections
  with no wrapper equivalent (presentation_views, accounting_scope) are
  reported at D2 as `not_expressible`, which is itself a finding. They must
  not be applied at D1 instead to make a downstream comparison pass. List
  every unchanged base-wrapper field as inherited; parity with a mostly
  inherited wrapper does not measure full profile replacement.
- Per-CIK code that production applies (`explicit_contexts.py` for NexPoint
  and Onex, the Stepstone rescale, Ares literals; 6 of 8 pilot CIKs appear as
  literals in `pipeline/*.py`) is inherited at D1 and listed in the result,
  so a D1 pass on those CIKs is read as "compatible given inherited code".
- Parity requires exact row multiplicity and exact per-row FV, including
  null-versus-zero and currency distinctions, plus exact aggregate FV.
  Compare decimal values without tolerance or rounding, under one stated
  canonicalisation applied to BOTH sides: read the reference CSV columns as
  VARCHAR (never through float inference), and convert each side's text to
  `decimal.Decimal` via `Decimal(text)` then `.normalize()`, so that
  `14700000.0`, `1.47e7` and `14700000` are one value and `0` and `null`
  remain distinct. Pilot-side values come from the parser's own numeric
  output converted with `Decimal(str(value))` before normalisation. The
  canonicalisation function and its version are recorded in the parity
  result; a value that fails to parse as Decimal on either side is
  `unkeyed/ambiguous`, never coerced.
  Other columns have separate typed agreement counts. Null/empty keys and
  collisions are reported as unkeyed/ambiguous and prevent an exact verdict;
  they cannot disappear in a merge or a set comparison.
- Pin the source accession selection, code/configuration hashes and each
  boundary frame before comparison. Verify inputs before and after use.
  A cover-only amendment does not automatically supersede a populated
  primary. The pipeline has no amendment-selection policy of its own; the
  only existing evidenced policy is the one in
  `scripts/run_context_census.py`, which the pilot reuses by reference (pin
  its git blob hash in the manifest). Where that script does not settle a
  case, the fund-quarter is `unavailable` with all candidate accessions
  listed. Source-selection differences and legacy/current-parser changes
  are named divergences, not profile failures or silent exclusions.
- If an existing production path cannot be invoked with all writes confined
  to the pilot workspace, record `not_expressible`/`insufficient_evidence`
  with the missing integration boundary. Do not replace it with an
  approximation while claiming D1-D3 compatibility.

**What parity means.** Parity measures compatibility with production output
today. It does not measure whether production is correct, and it is not an
independent check on the census (the wrapper author and the census may share
the same cues). Correctness evidence comes from source-row witnesses and
existing anchor/fund-total reconciliation on a pinned basis. Aggregate
reconciliation alone cannot prove position-level completeness or identity.

### 6.5 [E] Graduation test (`graduate.py`)

For every live B2 leaf and investigate rule for the eight CIKs, the LeDQeR
generalisability filter, deterministically:

1. Express the correction as a candidate profile entry (e.g. a
   `comparative_period_filter` on rows with `period < report_date` becomes a
   `comparative_periods` declaration; a `row_exclusion` naming a subtotal
   string becomes a `subtotals_and_headings` marker).
2. **Fidelity on every origin quarter first**: independently execute the
   original correction and candidate on the pinned pre-correction frame at
   its actual stage. Compare source-row multisets and the action/value
   effects exactly, including null periods and additions. Non-empty overlap
   is not fidelity. A demonstrated mismatch is `not_expressible`; inability
   to recover the pre-correction frame is `insufficient_evidence`. Already
   corrected published output cannot establish which rows were removed.
3. Apply the candidate to every available out-of-scope quarter at the same
   boundary. Preserve all structural predicates; never strip date clauses
   by string replacement. A supported translation must distinguish temporal
   scope from the mechanism, or remain `not_expressible`.
4. Classify, with an explicit unresolved outcome:
   - `generalises`: touches the same class of rows in >= 2 other quarters,
     AND on each touched quarter the affected positions pass a source-backed
     check, with a witness for every selected observation: comparative
     period/source identity, structural subtotal membership, or a duplicate
     view's retained counterpart of the same position. The filer's reported
     schedule total must also reconcile on the gate's pinned basis,
     including currency, subsidiaries and JVs; its band is reused, not a
     new pilot-wide 1% tolerance. Every touched out-of-scope quarter must be
     assessable and supported, with at least two such quarters. No required
     position may be lost, including zero-FV positions. Recurrence plus
     unchanged FV conservation alone is
     NOT sufficient: a wrong deletion can pass through zero balances or
     offsetting errors.
   - `quarter_bound`: supported translation touches nothing in assessed
     out-of-scope quarters. An already-all-quarters rule has no holdout and
     is `insufficient_evidence`, not a demonstrated quarter-bound rule.
   - `conflicts`: a source-row witness or the filer's total contradicts the
     candidate on an assessed out-of-scope quarter.
   - `insufficient_evidence`: touches rows elsewhere but the source-backed
     check cannot be evaluated (no anchor for the quarter, basis mismatch,
     fewer than 2 supported other quarters, incomplete row witnesses, or
     any touched quarter that remains unassessable). Reported, never
     folded into `generalises`.
   - `not_expressible`: row_id-pinned value fix, or fidelity failure.

Report yield per CIK and per fix class, with `insufficient_evidence` shown
as its own column against the fixed denominator of all live corrections for
the eight CIKs (inventory written before the run).

The comparative-period case needs care: per AGENTS.md, comparative rows are
legitimate prior-period facts, not duplicates. A `comparative_periods`
declaration says how this filer's prior-period contexts are distinguished
from current ones; it does not say "drop them". Fidelity is measured against
the rows the leaf excluded from the current-period view, not against
deletion.

### 6.6 [F] All-quarter extension (`halflife.py`)

Apply the Q1-derived profile and contracts read-only to every later quarter of
each CIK (11-15 quarters). Record, per section, the first quarter a contract
breaches and whether the breach coincides with a form-type change, a known
dated event, or neither. Cheap once [A]-[C] exist; gives re-use half-life
instead of a single Q1->Q2 point.

Measurement rules:

- Time is measured in **quarters since derivation**, not calendar quarter, so
  CIKs with different Q1 dates pool correctly. Compute elapsed time from
  the fund's reporting calendar, not the number of cached files. Skipped
  filings do not shorten time.
- A section that never breaches within the available quarters is a
  **censored** observation at its last observed quarter, not a "no break" or
  a break at the horizon. An unassessable check is not evidence of survival:
  conservatively censor at the last continuously assessable passing quarter,
  and retain later results as diagnostics outside that survival observation.
  Contracts never assessable are separately `unassessable`, not long-lived.
  The half-life is the Kaplan-Meier median when the estimated survival curve
  reaches 0.5; otherwise report "not reached". Include risk-set, event,
  censored and unassessable counts. Use the same frozen contracts, including
  value-range and partition contracts, as M2. State the aggregation unit;
  repeated field checks are not independent section observations.
- The pilot derives from a fixed Q1 profile. Its first-break quarter says how
  long a Q1 profile lasts; it does NOT show whether a profile derived from a
  later quarter would stabilise. That claim needs re-derivation at later
  quarters, which is out of pilot scope and listed as such in section 9.

## 7. Existing assets reused

| Asset | Use |
|---|---|
| `pipeline/context_inventory.py` | context classification inside the census |
| `pipeline/wrapper_content_signatures.py`, S0 linkbase signal | identifier / concept fingerprint fields |
| `pipeline/bdc_xbrl_wrapper.py` loaders + `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json` | reading the hand-authored wrapper for comparison |
| `data/overrides/identifier_rate_grammars/*.json` | format grammar inside contracts |
| `data/overrides/rate_convention/*.json` | citation schema pattern for evidence entries |
| `data/overrides/agent_anchor/*.json` | anchors section |
| `scripts/candidate_footprint.py` | pattern for the parity report |
| `data/reference/sofr_90day_avg.csv` | not needed in pilot; noted for detector 2 later |

## 8. Deliverables

1. `scripts/profile_pilot/` package: census, profile/envelope, translation,
   contracts, interpretation/parity, graduation, half-life and reporting
   modules, plus path/manifest and protection/verification helpers. The plan
   lists the complete module inventory. `run.py` accepts `--cik`,
   `--quarters first2|all`, `--run-id`, `--data-root` and a confined `--out`.
   Schemas live inside the package at `schemas/filer_profile_v0.schema.json`
   and `schemas/census_v0.schema.json`.
2. Tests: one file per module, fixtures from two small cached instances
   (Stellus Q1, NexPoint Q1; these tests are cache-dependent and skipped in
   CI) plus synthetic instances for subtotal, presentation-view and
   comparative-period detection, at least one false-positive case per
   detector, one `insufficient_evidence` case per detector, and schema tests
   for both supersession kinds (retrospective correction, genuine change).
   Verify historical queries before/at/after recording time and effective
   time for both kinds, finite intervals and correction-after-change.
3. Pinned inputs written before their measurement:
   `inventories/wrapper_key_inventory.json` (M1 denominator),
   `inventories/correction_inventory.json` (M3 denominator),
   `inventories/contract_tolerances.json` (M2 bands), primary-quarter and
   contract inventories, and `manifest.json` for the exact inputs,
   configuration and D1-D3 reference artifacts (paths, git HEAD, dirty-source
   digest, SHA-256). Q1 contract learning precedes freezing the M2 inventory;
   Q2 evaluation cannot change it.
4. Cost note: the census collectors for comparative periods, rates, footnote
   markers and fund-level income are new code (6.1), and the three-boundary
   parity needs a staged-frame materialisation (6.4). The pilot is larger
   than the v1 draft priced. Start [E] graduation with pinned overrides,
   recoverable pre-correction stage inputs and source evidence. It can
   report M3 independently; missing origin frames or row witnesses remain
   insufficient-evidence results. Reconstruction that triggers heavy work
   must acquire the shared lease, even when invoked from graduation.
5. Results: `results/summary.json` under the per-run root and
   `docs/investigations/filer_profile_pilot.md` (dated heading, question,
   results), indexed via `python scripts/split_investigations.py --reindex`.
6. Changelog entry per the agent update protocol.

**Staged delivery with go/no-go checkpoints.** The v4 requirements raise the
build cost well above the v3 estimate (see section 12 question 5). Execution
is therefore staged, and each stage ends with a report the owner reads before
the next starts:

| Stage | Tasks | Delivers | Owner reads |
|---|---|---|---|
| A | 1-3 | protection, lease adapter, envelope, graduation | M3 with denominator; count of `insufficient_evidence` items and their causes; measured cost of Tasks 1-3 |
| B | 4-8 | census, profile, translate, contracts | M1 (Q1 and, if evidenced, same-era), M2, partition candidates; collector completeness states per CIK |
| C | 9-11 | connected parity, half-life, runner | M4 per boundary with D1 labelled as pinning, M5 with censoring and unassessable counts |
| D | 12 | execution on all eight, write-up | the five numbers and the decision-table reading |

A stage that reports mostly `insufficient_evidence` or an integration gap is
a valid stopping point; the owner decides whether the next stage is worth
its cost.

## 9. Metrics and decision

| # | Metric | Definition | Informs |
|---|---|---|---|
| M1 | Derivation rate | `exact` / all wrapper keys, with `partial`, `inherited`, `unresolved`, `miss`, `not_derivable` each reported as its own share of the same fixed denominator (`wrapper_key_inventory.json`); per CIK and section. `partial` is never added to `exact`. | how much agent authoring the profile removes |
| M2 | Re-use rate | Q2 contracts `holds` / all contracts; `holds_with_form_type`, `breach` and `insufficient_evidence` reported separately; bands fixed in `contract_tolerances.json` before evaluation | whether a profile survives a quarter |
| M3 | Graduation yield | corrections `generalises` / all live corrections for the eight CIKs (`correction_inventory.json`), with `insufficient_evidence`, `quarter_bound`, `conflicts`, `not_expressible` each as its own share; per fix class | whether corrections and semantics need one system |
| M4 | Compatibility parity | fund-quarters with exact row-multiset, per-row FV and aggregate decimal FV equality at D1, D2, D3 (each / 16, D3 with and without correction replay); missing/ambiguous keys, unsupported integration and missing results reported explicitly | whether a profile can drive production as it stands, and how much of production output is inherited code or corrections |
| M5 | Half-life | Kaplan-Meier median first-break in elapsed fund quarters since derivation; stated CIK/section/partition unit, risk-set/event/censored/unassessable counts, and share of observed breaks coinciding with a form-type change or known event | how long fixed-Q1 contracts remain assessably valid; coincidence does not prove the cause of a break |

No pass/fail thresholds are set in advance; the pilot is measurement. The
decision it informs, in order:

- First distinguish incomplete measurement from a negative result. Missing
  implementations, source channels or same-era evidence cannot establish
  that the architecture fails; report that limitation before a recommendation.
- With adequate measurement, M1 `exact` low (< ~50% on structural sections)
  and `inherited` high -> consider retaining agent authoring and adding time
  validity to the wrapper schema. `unresolved` is not evidence that a field
  cannot be derived.
- M1 high, M2 low even after form-type split -> investigate source drift,
  extraction defects and contract design before attributing the breaks.
  Use supported causes to decide whether form/year-specific contracts are
  needed before making a carry-forward claim.
- M3 high (> ~50% of comparative/exclusion rules `generalises`, not counting
  `insufficient_evidence`) -> build the graduation path in B2 verify/promote;
  corrections and semantics share a system with distinct objects.
- M4 D1 or D2 < 16/16 -> list the exact divergences before any migration
  plan. Attribute a D3 gap to corrections only after the complete connected
  transformation and ordered replay are demonstrated with all other inputs
  fixed; unsupported unification or source selection remains a separate gap.
- M5 says how long a Q1 profile lasts. Whether later-derived profiles last
  longer is not measured here and must not be inferred from it.

The owner reads the five numbers and decides whether to write the migration
spec (profile schema v1, precedence resolver, CIK-literal migration, column
contracts as per-CIK parameters). This spec does not authorise that work.

## 10. Constraints and controls

- Run only in the pilot worktree (section 2). Never check out the pilot
  branch in the sealed checkout while the V13 closeout is open.
- One heavy job at a time; check for running pytest / rebuild processes
  first. The V13 controllers hold the programme heavy lock; census over the
  large instances (Ares, BCRED) and the all-quarter extension wait for it.
  Acquire the existing cross-worktree programme lock for the entire heavy
  operation; process discovery alone is not mutual exclusion. A failed or
  unavailable process/lock inspection blocks heavy work. There is no
  `--allow-heavy` bypass. Every entry point that can trigger a heavy census,
  including profile/contracts/cache misses, must pass the same guard.
  **Lease mechanics (verified 2026-09-28):** the lease is
  `pipeline.programme.runner.heavy_lock(candidate)`, a context manager. It
  scans processes with psutil for `pytest`, `rebuild_outputs.py` and
  `pipeline.programme.bootstrap`, then reads or writes `ROOT /
  'data/programme/heavy.lock'` with `controller_pid`, `controller_created`
  and `candidate`, and refuses if the prior candidate's worker telemetry
  PIDs are alive. `ROOT` resolves from the importing module's file, so the
  pilot adapter must bind the MAIN checkout root, not the worktree. The
  `candidate` argument must be a directory under the main checkout's
  `data/programme/candidates/`; the pilot creates
  `pilot-filer-profile-<run_id>/` there (the second permitted external
  write, section 2) containing only `pilot.json` with the run id and pilot
  root. It never creates `attempts/` or `frozen/` trees. If the programme
  later exposes a candidate-free lease, the adapter switches to it.
- **Last-rebuild rule (owner, 2026-09-28).** The V13 build in flight is the
  last refactor rebuild before the pilot's heavy stages. If it does not
  finalise V13, no V14 build starts; the refactor programme pauses and the
  pilot takes the lock. Light pilot work (schemas, synthetic tests,
  small-instance census and graduation using already-materialised small
  frames) can proceed. Any nested operation that triggers a heavy census or
  stage reconstruction must acquire the same lease; the calling module's
  name does not exempt it.
- Census over a 1,000-row instance must complete in < 60 s and < 2 GiB; use
  DuckDB SQL or vectorised operations for any per-row work.
- ASCII-only logs.
- `python scripts/diff_outputs.py --semantic` after the test run as the
  protected-file backstop, even though the pilot writes nothing there.
  Protect the resolved data root's `output/` and the main checkout's
  `frontend/public/data/`, as well as worktree output roots, before any
  cache-backed tests import pipeline code. Cover both Python writes and
  native-IO changes with before/after inventories. Empty worktree output
  directories do not waive this requirement. Invoke the existing semantic
  diff script against the main checkout read-only, recording its baseline
  differences separately from the pilot preservation result; never refresh
  a baseline. Inspection failure is a failed protection check.
- Every result JSON records a run ID, git HEAD and dirty-source digest,
  exact input/configuration hashes, schema/collector versions and wall clock.
  Cache reuse requires the full dependency identity and a complete prior
  result. Missing result files remain explicit in fixed denominators.

## 11. Risks

- **First-quarter weakness.** Earliest quarters are the weakest XBRL and, for
  young funds, ramp-up books (Fidelity Q1 = 26 rows). Low M1/M2 on those CIKs
  may reflect thin evidence rather than a bad design. Mitigation: same-era
  M1, explicit low-history flags, and per-CIK reporting. M5 cannot establish
  stability of profiles learned at later dates.
- **Form-type confound.** Five pairs cross into a 10-K. Mitigation: split
  reporting; record actual form type from the accession.
- **Census reproduces the wrapper because the wrapper author used the same
  cues.** M1 may overstate independence. M4 does NOT resolve this: it
  measures compatibility with production, which the same wrapper shaped.
  Mitigation: the `inherited` tag makes shared cues visible; source-row
  witnesses and the existing anchor/fund-total reconciliation provide
  correctness evidence within their stated coverage. Totals cannot replace
  position-level witnesses. Report M1 as derivability, not correctness.
- **Graduation test leniency.** "Touches rows elsewhere" is a weak
  generalisability proxy. Mitigation: origin-quarter fidelity, the
  source-backed check on affected positions, an explicit
  `insufficient_evidence` outcome, and `conflicts` classified separately.
  Still a proxy; reported as one.
- **Structural detectors over-claim.** Equal values, sum equality and missing
  concepts are each consistent with benign explanations. Mitigation: the
  three-state detector outcome in 6.1; false-positive and
  `insufficient_evidence` tests per detector.
- **Seal breach.** Adding pilot code in the sealed checkout voids V13.
  Mitigation: worktree-only execution (section 2); recorded in the rubric's
  section 5 if it ever happens.
- **Sections with no independent correctness check in the pilot.**
  Reconciliation against the filer's reported totals is an aggregate check
  on subtotals, presentation views, comparative periods and accounting
  scope. Compensating errors and zero-FV omissions can leave totals unchanged;
  it cannot replace source-row witnesses. It does not cover rate semantics
  and scale (checked only by the fund-income yield contract, a signal not a gate),
  footnote conventions (non-accrual location; no check in the pilot),
  and position identity (no check in the pilot). Derived entries in those
  sections are reported as `derived`, never as verified, and the induction
  review (an agent citing source evidence per entry, section 6.2 status
  flow) is where they would be checked in a migration. Row-level sampled
  audits remain advisory.
- **Mixed formats inside one filing.** Handled by `applies_to` partitions
  (6.2) and per-partition contracts (6.3). Residual risk: a partition with no
  structural discriminator is `insufficient_evidence` and needs an agent to
  find the predicate; the agent's output is still a predicate, never a row
  list.
- **Scope creep into detectors.** Mitigation: section 4; halflife records, it
  does not gate.

## 12. Open questions for the owner

1. Should the pilot also run the two wrapper-only alternates (Saratoga, Lord
   Abbett) as extra controls, at the cost of two more census fixtures?
2. Artifact home: resolved by the v3 owner ruling as `data/pilot/` (section 14).
3. Whether the investigation write-up should propose the v1 profile schema or
   stop at the numbers.
4. **Same-era M1 evidence tier.** Wrappers record no authoring accession
   (section 5). Options: (a) admit "latest cached filing whose filing_date
   precedes the wrapper's last version-bump commit" as a labelled lower tier
   and report it as such; (b) drop same-era M1 and rely on M5 plus the
   low-history flags for the drift-versus-derivability question. Default if
   unanswered: (b), with the comparison reported as `unavailable`.
5. **Cost acceptance.** The v4 requirements (complete collector, connected
   D1-D3 through the unified build, per-correction origin reconstruction,
   protection plugin, lease adapter, event-sourced envelope) are estimated at
   two to three times the v3 build. Ruling 5 asked for a minimal suite. The
   staged checkpoints in section 8 let the owner stop after Stage A or B;
   confirm that this is acceptable, or name the requirements to trim.

## 13. Review log

Six comments on the v1 draft, all verified against the repo on 2026-09-28
and accepted by the owner the same day.

| # | Comment | Verified how | Landed in |
|---|---|---|---|
| 1 | Parity targeted the wrong stage: `bdc_holdings.csv` has no `row_id` or parsed issuer; wrappers and corrections apply downstream; parity is compatibility, not correctness | column header of `bdc_holdings.csv`; `row_id` present only in `private_markets_holdings.csv`; correction appliers in `staging_bdc.py` and `unified_holdings.py` | 3 (goal 4), 6.4, 9 (M4), 11 |
| 2 | "Unaided derivation" needs a boundary: census inherits `explicit_contexts` identity rules and rate grammars; `context_inventory` keeps only target-quarter monetary facts | `context_inventory.py` import of `explicit_member_dimensions`; `if ctx["period"] != quarter: continue` in `scan_instance` | 3 (goal 1), 6.1, 6.2 (`provenance`, `inherited`), 8 (cost note), 9 (M1) |
| 3 | Two-clock envelope conflated retrospective corrections with genuine convention changes; no transaction-time end | v1 envelope had `recorded_at` but no `recorded_until`; supersession always closed `valid_to` | 6.2 (`recorded_until`, `supersession_kind`, overlap rule, as-of tests), 8 (tests) |
| 4 | Structural signals and graduation need an explicit unresolved outcome; recurrence + FV conservation is insufficient | design review; consistent with AGENTS.md weak-vs-strong validation | 6.1 (detector outcomes), 6.5 (fidelity, source-backed check, `insufficient_evidence`), 11 |
| 5 | Metrics: `partial` folded into M1; no fixed denominators; tolerances undefined; M5 lacked censoring and over-claimed stabilisation | reading of v1 section 9 | 6.2 (classes), 6.3 (tolerance table), 6.6 (censoring), 8 (pinned inventories), 9 |
| 6 | Isolation claim wrong: the V13 closeout rubric freezes `scripts/` and `tests/` too | rubric rule 1, `docs/production_stack/2026-09-28_v13_closeout_rubric.md` | 2, 10, 11 |

The two items left open in v2 (same-era derivation, three quarters per CIK)
were ruled on in v3; see section 14.

## 14. Pre-start decisions (owner rulings, 2026-09-28)

| # | Decision | Ruling | Landed in |
|---|---|---|---|
| 1 | Start now or wait for V13 handoff | Start now in the worktree, heavy-lock kept. The V13 build in flight is the last refactor rebuild; if it does not finalise, pause the refactor, pilot takes the lock | 2, 10 |
| 2 | Branch base | Build on `ensemble-fp-experiment`, rebase onto `main` after the V13 merge | 2 |
| 3 | Artifact home | `data/pilot/` git-ignored | 2, 6.x paths, 8 |
| 4 | Partition predicate | Add `applies_to` to the envelope; contracts per partition | 6.2, 6.3, 11 |
| 5 | Non-reconciliation checks in contracts | Minimal suite now: fund-income yield included, per-row format-grammar contract included, non-accrual count deferred. Extend if the pilot works | 6.3, 11 |
| 6 | Same-era M1 | Yes: second profile from each wrapper's authoring quarter | 5, 9 |
| 7 | Quarters per CIK | Two in the pilot; follow-on extends to three then four to validate time-constancy | 5 |

Still open: extra controls (decide after the Stellus census); whether the
write-up proposes the v1 schema (decide at the end; recommendation is
numbers only).

## 15. Implementation review corrections (v4, 2026-09-28)

The owner requested these changes after review of the v3 spec and its first
implementation plan. They refine the existing scope; they do not record a
new approval to migrate or promote production behavior.

| Review finding | Required correction | Spec / plan |
|---|---|---|
| Monetary-only census and incorrect comparative/absence evidence | complete bounded source collection; context dates, missing-channel states and source-pinned negative controls | 6.1 / Tasks 4-5 |
| Namespace used as scale; partitions were placeholders | executable Q1 structural predicates, actual unit conversion and existing S2 evidence limits | 6.2-6.3 / Tasks 2, 8 |
| Graduation could pass on overlap and aggregate totals | exact origin effects; witnesses for every affected row and every touched quarter; unknown evidence blocks graduation | 6.5 / Task 3 |
| Parity stages disconnected; unified IDs borrowed; duplicate/tolerance gaps | connected production boundaries, independent IDs and exact row-multiset/decimal comparisons | 6.4 / Task 9 |
| Genuine changes rewrote historical beliefs | immutable assertions/retractions and historical queries for both supersession kinds | 6.2 / Task 2 |
| M1 compared cues; M5 counted files and unknown survival | executable-value comparison; real elapsed quarters, frozen contracts and explicit censoring | 6.2, 6.6, 9 / Tasks 6, 10-11 |
| Empty-worktree protection and fail-open heavy inspection | actual-root protection, semantic backstop and exclusive shared lease on every heavy entry path | 2, 10 / Tasks 1, 12 |

The revised plan preserves twelve implementation tasks and replaces untested
code templates with acceptance requirements and adversarial test cases.
This revision changes documents only; all implementation checkboxes remain open.
