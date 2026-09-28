# Filer Profile Pilot: census-derived, bitemporal per-CIK knowledge store

Status: DRAFT v2 for owner review, 2026-09-28. Supersedes nothing; extends
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

- Branch `filer-profile-pilot` off `ensemble-fp-experiment`. No edits under
  `pipeline/`.
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
- Writes: `scratch/2026-09-28_profile_pilot/` only. No `data/output/`,
  `frontend/public/data/`, baseline, threshold, registry or wrapper change.
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
  extension (section 8.4) records where a Q1-derived profile first breaks, but
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
`scratch/2026-09-28_profile_pilot/census/{cik}/{report_date}.json`.

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
  group stays `candidate` until position identity (issuer + instrument +
  maturity where present) agrees across the group.
- Sum equality does NOT establish a subtotal. A sum-of-others context stays
  `candidate` until the identifier text or member label also reads as a
  heading/total, or the wrapper's aggregate markers agree (that agreement is
  then `inherited`).
- A missing concept does NOT establish non-disclosure. `non_disclosure` is
  `insufficient_evidence` unless the field is also absent from identifier text
  segments and footnote/text facts in the instance.

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
| non_disclosure | fields with zero carrying concept | derived |
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
  Resolution order: (filer, form_type, dated) -> (filer, dated) -> default.
- **Two clocks, kept apart.** `valid_from` / `valid_to` are report dates
  (valid time: when the filer's behaviour held). `recorded_at` /
  `recorded_until` are wall clock (transaction time: when we believed the
  entry). Entries are immutable versions; nothing is edited in place or
  deleted. Two distinct events, which the v1 envelope conflated:
  - **Retrospective correction** ("we were wrong about this filer all
    along"): the new version copies the old valid range, the old version gets
    `recorded_until` set, `supersession_kind = "correction"`. Valid time does
    not move.
  - **Genuine convention change** ("the filer changed in quarter Q"): the old
    version gets `valid_to = Q-1` and stays current in transaction time
    (`recorded_until` stays null); the new version starts at `valid_from = Q`,
    `supersession_kind = "change"`.
  - Overlap rule: at most one version per (`key`, `form_type`) may be current
    in transaction time for any report date; the schema validator rejects
    overlapping valid ranges among transaction-current versions.
  - The schema supports an as-of query ("what did we believe about report
    date R at wall-clock time T"), and the pilot ships synthetic tests for
    both events plus one as-of query. The pilot does NOT build a query engine
    or a resolver beyond the validator.
- `confidence` is replaced by `support`, a measured quantity with a named
  estimator (prevalence numerator/denominator, or a context count). Census
  entries carry no unmeasured score.
- `regression_pin` is null in the pilot and documented as the slot for the
  later migration's per-entry regression test reference; it is not populated.
- Profile JSON is written to
  `scratch/2026-09-28_profile_pilot/profiles/{cik}.json`. Schema at
  `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`.

**Derivation-rate comparison**: for each key in the hand-authored wrapper
(`dispatch.*`, `identifier_format.*`, `staging.strategy`, `source_encodings.*`,
`archetypes`, `invariants`, `segment_assertions`), classify the census
proposal as exactly one of:

- `exact` (census value equals the wrapper value),
- `partial` (same shape, different value or subset),
- `inherited` (census reproduces the key only via inherited code or files,
  section 6.1),
- `unresolved` (detector returned `candidate` or `insufficient_evidence`),
- `miss` (census proposes nothing or something contradictory),
- `not_derivable` (wrapper key has no structural counterpart, e.g.
  `known_edge_cases` prose).

The denominator is fixed as all wrapper keys for that CIK, listed once in
`results/wrapper_key_inventory.json` before any census runs. Report per CIK
and per section.

### 6.3 [C] Contracts (`contracts.py`)

Per filer, per canonical field, expectations learned from Q1 census + profile:
source concept(s), fill-rate band, format grammar (from the existing rate
grammar if present), scale, value range, form_type. Evaluated on the Q2 census
and Q2 interpreted rows. Output per (cik, field): `holds`, `holds_with_form_type`,
`breach`, with expected vs observed.

Pilot does not gate or withhold anything; it records. Tolerances are fixed
before any Q2 evaluation and written to `results/contract_tolerances.json`:

| Expectation | Tolerance (Q1 >= 50 positions) | Tolerance (Q1 < 50 positions, `low_history`) |
|---|---|---|
| source concept set | identical set | identical set |
| fill rate | +/- 10 percentage points | +/- 25 percentage points |
| scale | identical | identical |
| value range (rates, spreads) | Q2 p5-p95 inside Q1 min-max widened by 25% | same, widened by 50% |
| format grammar | every Q2 identifier parses | >= 90% parse |

These are reporting bands, not pass/fail bars; the pilot is measurement.
Changing a band after seeing Q2 results is recorded as a change to the
tolerances file with the reason, never applied silently.

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
| D1 extraction | profile-driven read of the cached instance | `data/output/bdc_holdings.csv` slice for (cik, report_date) | (`accession_number`, `src_context_id`) | row set, `fair_value`, cost, principal, raw rate fields, raw identifier |
| D2 staging | D1 output through the profile's identifier_format / subtotals / presentation_views sections | the staged BDC frame as produced by `staging_bdc` for that slice (materialised to scratch during the run; exact production function pinned at implementation) | (`accession_number`, `src_context_id`) | row set after aggregate/subtotal exclusion, parsed issuer, instrument, industry, affiliation |
| D3 unified | D2 output plus explicit replay of the production corrections that touch the slice | `data/output/private_markets_holdings.csv` slice | `row_id` | row set, FV, classification |

Rules:

- Corrections are replayed explicitly at D3, never inferred: the run lists
  each B2 leaf and investigate rule applied to the slice in production
  (`agent_promoted` loaders, read-only) and applies the same row selections.
  D3 is reported twice, with and without replay, so the profile is not
  penalised for corrections it is not meant to hold and the size of the
  correction layer is visible.
- `interpret.py` does not re-implement extraction. Where a profile section
  has a wrapper-v3 equivalent, the profile is translated to wrapper form and
  the existing loaders are pointed at the scratch directory
  (`reload_wrapper_specs(override_dir=...)`, staging config loader). Sections
  with no wrapper equivalent (presentation_views, accounting_scope) are
  reported at D2 as `not_expressible`, which is itself a finding.
- Per-CIK code that production applies (`explicit_contexts.py` for NexPoint
  and Onex, the Stepstone rescale, Ares literals; 6 of 8 pilot CIKs appear as
  literals in `pipeline/*.py`) is inherited at D1 and listed in the result,
  so a D1 pass on those CIKs is read as "compatible given inherited code".
- Parity = exact equality on row set and FV at each boundary; per-column
  agreement reported separately. Row-key collisions or nulls are reported as
  `unkeyed` rows, never dropped.

**What parity means.** Parity measures compatibility with production output
today. It does not measure whether production is correct, and it is not an
independent check on the census (the wrapper author and the census may share
the same cues). Independent correctness lives in the existing anchor and
fund-total reconciliation, which the pilot reads but does not re-derive.

### 6.5 [E] Graduation test (`graduate.py`)

For every live B2 leaf and investigate rule for the eight CIKs, the LeDQeR
generalisability filter, deterministically:

1. Express the correction as a candidate profile entry (e.g. a
   `comparative_period_filter` on rows with `period < report_date` becomes a
   `comparative_periods` declaration; a `row_exclusion` naming a subtotal
   string becomes a `subtotals_and_headings` marker).
2. **Fidelity on the origin quarter first**: the candidate must select
   exactly the row set the leaf or rule touches on its own quarter. A
   candidate that fails fidelity is `not_expressible` and goes no further.
3. Apply the candidate to every other quarter of that filer in
   `bdc_holdings.csv` and count rows it would touch.
4. Classify, with an explicit unresolved outcome:
   - `generalises`: touches the same class of rows in >= 2 other quarters,
     AND on each touched quarter the affected positions pass a source-backed
     check: the filer's reported schedule total (anchor / fund-total
     reconciliation on the same basis the gate uses, subsidiary- and
     JV-aware) moves toward the reported figure or stays within band, AND no
     touched row is a current-period position with a non-zero FV that the
     schedule total needs. Recurrence plus unchanged FV conservation alone is
     NOT sufficient: a wrong deletion can pass through zero balances or
     offsetting errors.
   - `quarter_bound`: touches nothing elsewhere.
   - `conflicts`: touches rows the filer total contradicts.
   - `insufficient_evidence`: touches rows elsewhere but the source-backed
     check cannot be evaluated (no anchor for the quarter, basis mismatch,
     fewer than 2 other quarters available for the filer). Reported, never
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
  CIKs with different Q1 dates pool correctly.
- A section that never breaches within the available quarters is a
  **censored** observation at its last observed quarter, not a "no break" or
  a break at the horizon. The half-life is the Kaplan-Meier median (or
  "not reached" if fewer than half the sections break), with the censored
  count reported beside it.
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

1. `scripts/profile_pilot/` package: `census.py`, `profile.py`,
   `contracts.py`, `interpret.py`, `parity.py`, `graduate.py`, `halflife.py`,
   `run.py` (CLI: `--cik`, `--quarters first2|all`, `--out`), and
   `schemas/filer_profile_v0.schema.json`, `schemas/census_v0.schema.json`.
2. Tests: one file per module, fixtures from two small cached instances
   (Stellus Q1, NexPoint Q1; these tests are cache-dependent and skipped in
   CI) plus synthetic instances for subtotal, presentation-view and
   comparative-period detection, at least one false-positive case per
   detector, one `insufficient_evidence` case per detector, and schema tests
   for both supersession kinds (retrospective correction, genuine change)
   plus one as-of query.
5. Pinned inputs written before any measurement:
   `results/wrapper_key_inventory.json` (M1 denominator),
   `results/correction_inventory.json` (M3 denominator),
   `results/contract_tolerances.json` (M2 bands), and the reference-artifact
   manifest for D1-D3 (paths, git HEAD, SHA-256).
6. Cost note: the census collectors for comparative periods, rates, footnote
   markers and fund-level income are new code (6.1), and the three-boundary
   parity needs a staged-frame materialisation (6.4). The pilot is larger
   than the v1 draft priced. Run [E] graduation first: it needs only the
   override files and `bdc_holdings.csv`, touches none of the new collectors,
   and delivers M3 on its own.
3. Results: `scratch/2026-09-28_profile_pilot/results/summary.json` and
   `docs/investigations/filer_profile_pilot.md` (dated heading, question,
   results), indexed via `python scripts/split_investigations.py --reindex`.
4. Changelog entry per the agent update protocol.

## 9. Metrics and decision

| # | Metric | Definition | Informs |
|---|---|---|---|
| M1 | Derivation rate | `exact` / all wrapper keys, with `partial`, `inherited`, `unresolved`, `miss`, `not_derivable` each reported as its own share of the same fixed denominator (`wrapper_key_inventory.json`); per CIK and section. `partial` is never added to `exact`. | how much agent authoring the profile removes |
| M2 | Re-use rate | Q2 contracts `holds` / all contracts; `holds_with_form_type` and `breach` reported separately; bands fixed in `contract_tolerances.json` before evaluation | whether a profile survives a quarter |
| M3 | Graduation yield | corrections `generalises` / all live corrections for the eight CIKs (`correction_inventory.json`), with `insufficient_evidence`, `quarter_bound`, `conflicts`, `not_expressible` each as its own share; per fix class | whether corrections and semantics need one system |
| M4 | Compatibility parity | fund-quarters with exact row-set and FV equality at D1, D2, D3 (each / 16, D3 with and without correction replay); `unkeyed` and `not_expressible` counts beside each | whether a profile can drive production as it stands, and how much of production output is inherited code or corrections |
| M5 | Half-life | Kaplan-Meier median first-break, in quarters since derivation, across sections and CIKs; censored count; share of observed breaks coinciding with a form-type change or a known dated event | how often detectors would fire, and whether on real changes |

No pass/fail thresholds are set in advance; the pilot is measurement. The
decision it informs, in order:

- M1 `exact` low (< ~50% on structural sections) and `inherited` +
  `unresolved` high -> the store stays agent-authored; add time validity to
  the existing wrapper schema and stop.
- M1 high, M2 low even after form-type split -> filers drift faster than
  assumed; contracts must be per form type and per year before any
  carry-forward claim.
- M3 high (> ~50% of comparative/exclusion rules `generalises`, not counting
  `insufficient_evidence`) -> build the graduation path in B2 verify/promote;
  corrections and semantics share a system with distinct objects.
- M4 D1 or D2 < 16/16 -> list the exact divergences before any migration
  plan. A D3 gap between with-replay and without-replay is the size of the
  correction layer, not a profile defect.
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
- Census over a 1,000-row instance must complete in < 60 s and < 2 GiB; use
  DuckDB SQL or vectorised operations for any per-row work.
- ASCII-only logs.
- `python scripts/diff_outputs.py --semantic` after the test run as the
  protected-file backstop, even though the pilot writes nothing there.
- Every result JSON records git HEAD, input file hashes, and wall clock.

## 11. Risks

- **First-quarter weakness.** Earliest quarters are the weakest XBRL and, for
  young funds, ramp-up books (Fidelity Q1 = 26 rows). Low M1/M2 on those CIKs
  may reflect thin evidence rather than a bad design. Mitigation: M5 shows
  whether later quarters stabilise; report per CIK, never pooled only.
- **Form-type confound.** Five pairs cross into a 10-K. Mitigation: split
  reporting; record actual form type from the accession.
- **Census reproduces the wrapper because the wrapper author used the same
  cues.** M1 may overstate independence. M4 does NOT resolve this: it
  measures compatibility with production, which the same wrapper shaped.
  Mitigation: the `inherited` tag makes shared cues visible; the only
  independent correctness signal available is the anchor / fund-total
  reconciliation, which the pilot reads. Report M1 as derivability, not
  correctness.
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
- **Scope creep into detectors.** Mitigation: section 4; halflife records, it
  does not gate.

## 12. Open questions for the owner

1. Should the pilot also run the two wrapper-only alternates (Saratoga, Lord
   Abbett) as extra controls, at the cost of two more census fixtures?
2. Is `scratch/` the right home for pilot profiles, or should a
   `data/pilot/` directory (git-ignored) be created so results outlive the
   session-scratch convention?
3. Whether the investigation write-up should propose the v1 profile schema or
   stop at the numbers.

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

Not folded in (raised in the same review, not yet ruled on by the owner):
derive a second profile from each wrapper's own authoring quarter so M1
separates three-year filer drift from derivability; extend each CIK to three
quarters so every filer has one same-form and one cross-form step.
