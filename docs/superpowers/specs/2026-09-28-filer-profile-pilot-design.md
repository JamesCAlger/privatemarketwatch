# Filer Profile Pilot: census-derived, bitemporal per-CIK knowledge store

Status: DRAFT for owner review, 2026-09-28. Supersedes nothing; extends
`docs/oxford_ledge_review/2026-09-17_oxford_ledge_comparison_and_remediation_loop.md`
sections 13-14 (which remain NOT FINALISED) with a bounded, measured pilot.

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
  `pipeline/`; the V13 source seal (801 pinned files) is untouched.
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
   deterministic census reproduces unaided.
2. Measure **quarter-over-quarter re-use**: a profile derived from a filer's
   first quarter applied to its second quarter; which sections carry unchanged,
   which carry with a form-type qualifier, which must be rewritten.
3. Measure **graduation yield**: how many existing B2 leaves and investigate
   rules for the pilot CIKs would pass a generalisability test and become dated
   profile declarations.
4. Establish **parity**: profile-driven interpretation reproduces production
   rows and FV for the pilot fund-quarters exactly (same gate class as Parquet
   PR-1).
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
 [D] interpret Q1 and Q2 rows via profile --> compare vs bdc_holdings.csv --> parity
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
existing cache readers. Nothing here is new analysis; it is the existing
wrapper-skill profiling step made deterministic and stored.

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
  "key": "identifier_format.delimiter",
  "value": " | ",
  "form_type": null,
  "valid_from": "2022-09-30",
  "valid_to": null,
  "recorded_at": "2026-09-28T14:02:11Z",
  "superseded_by": null,
  "author": "census",
  "status": "derived",
  "confidence": 0.97,
  "evidence": [{"kind": "context_ids", "accession": "...", "ids": ["c-12", "c-13"]}],
  "regression_pin": null
}
```

- `author` in {census, agent, human}. `status` in {derived, proposed,
  verified, promoted, retired}. Pilot only writes `census` / `derived`.
- `form_type` null means all forms; a non-null value narrows the entry.
  Resolution order: (filer, form_type, dated) -> (filer, dated) -> default.
- `valid_from` / `valid_to` are report dates (valid time). `recorded_at` is
  wall clock (transaction time). Supersession sets `valid_to` and
  `superseded_by` on the old entry; nothing is deleted.
- Profile JSON is written to
  `scratch/2026-09-28_profile_pilot/profiles/{cik}.json`. Schema at
  `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`.

**Derivation-rate comparison**: for each key in the hand-authored wrapper
(`dispatch.*`, `identifier_format.*`, `staging.strategy`, `source_encodings.*`,
`archetypes`, `invariants`, `segment_assertions`), classify the census
proposal as `match`, `partial`, `miss`, or `not_derivable` (wrapper key has no
structural counterpart, e.g. `known_edge_cases` prose). Report per CIK and per
section.

### 6.3 [C] Contracts (`contracts.py`)

Per filer, per canonical field, expectations learned from Q1 census + profile:
source concept(s), fill-rate band, format grammar (from the existing rate
grammar if present), scale, value range, form_type. Evaluated on the Q2 census
and Q2 interpreted rows. Output per (cik, field): `holds`, `holds_with_form_type`,
`breach`, with expected vs observed.

Pilot does not gate or withhold anything; it records. Fill-rate tolerance is
widened when Q1 has < 50 positions (Fidelity) and the packet stub is marked
`low_history`.

### 6.4 [D] Interpretation and parity (`interpret.py`, `parity.py`)

Applies the profile to Q1 and Q2 rows for the CIK and compares to the
production `bdc_holdings.csv` slice: row count, row identity by `row_id`,
fair value, cost, principal, rate fields, issuer, instrument, industry,
affiliation. Parity = exact equality on row set and FV; per-column agreement
reported separately.

Where production applies a B2 leaf or investigate rule to a pilot fund-quarter,
parity is computed twice: raw profile output, and profile output plus the same
rows the correction touched, so the profile is not penalised for corrections
it is not meant to hold.

### 6.5 [E] Graduation test (`graduate.py`)

For every live B2 leaf and investigate rule for the eight CIKs, the LeDQeR
generalisability filter, deterministically:

1. Express the correction as a candidate profile entry (e.g. a
   `comparative_period_filter` on rows with `period < report_date` becomes a
   `comparative_periods` declaration; a `row_exclusion` naming a subtotal
   string becomes a `subtotals_and_headings` marker).
2. Apply the candidate to every other quarter of that filer in
   `bdc_holdings.csv` and count rows it would touch.
3. Classify: `generalises` (touches the same class of rows in >= 2 other
   quarters, no FV-conservation regression on those quarters), `quarter_bound`
   (touches nothing elsewhere), `conflicts` (touches rows the filer total
   contradicts), `not_expressible` (row_id-pinned value fix).

Report yield per CIK and per fix class.

### 6.6 [F] All-quarter extension (`halflife.py`)

Apply the Q1-derived profile and contracts read-only to every later quarter of
each CIK (11-15 quarters). Record, per section, the first quarter a contract
breaches and whether the breach coincides with a form-type change, a known
dated event, or neither. Cheap once [A]-[C] exist; gives re-use half-life
instead of a single Q1->Q2 point.

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
   (Stellus Q1, NexPoint Q1) plus synthetic instances for subtotal,
   presentation-view and comparative-period detection, and at least one
   false-positive case per detector.
3. Results: `scratch/2026-09-28_profile_pilot/results/summary.json` and
   `docs/investigations/filer_profile_pilot.md` (dated heading, question,
   results), indexed via `python scripts/split_investigations.py --reindex`.
4. Changelog entry per the agent update protocol.

## 9. Metrics and decision

| # | Metric | Definition | Informs |
|---|---|---|---|
| M1 | Derivation rate | wrapper keys `match`+`partial` / derivable keys, per CIK and section | how much agent authoring the profile removes |
| M2 | Re-use rate | Q2 contracts `holds` / all; `holds_with_form_type` reported separately | whether a profile survives a quarter |
| M3 | Graduation yield | corrections `generalises` / total, per fix class | whether corrections and semantics need one system |
| M4 | Parity | fund-quarters with exact row-set and FV equality / 16 | whether the profile can replace the wrapper |
| M5 | Half-life | median first-break quarter across sections and CIKs; share of breaks coinciding with form-type change or a known dated event | how often detectors would fire, and whether on real changes |

No pass/fail thresholds are set in advance; the pilot is measurement. The
decision it informs, in order:

- M1 low (< ~50% on structural sections) -> the store stays agent-authored;
  add time validity to the existing wrapper schema and stop.
- M1 high, M2 low even after form-type split -> filers drift faster than
  assumed; contracts must be per form type and per year before any
  carry-forward claim.
- M3 high (> ~50% of comparative/exclusion rules generalise) -> build the
  graduation path in B2 verify/promote; corrections and semantics share a
  system with distinct objects.
- M4 < 16/16 -> list the exact divergences before any migration plan.

The owner reads the five numbers and decides whether to write the migration
spec (profile schema v1, precedence resolver, CIK-literal migration, column
contracts as per-CIK parameters). This spec does not authorise that work.

## 10. Constraints and controls

- One heavy job at a time; check for running pytest / rebuild processes first.
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
  cues.** M1 may overstate independence. Mitigation: M4 parity against
  production rows is the independent check.
- **Graduation test leniency.** "Touches rows elsewhere" is a weak
  generalisability proxy. Mitigation: the FV-conservation check on touched
  quarters; classify `conflicts` explicitly; report the proxy as a proxy.
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
