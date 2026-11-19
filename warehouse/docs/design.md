# Data model redesign: design

Status: conceptual and logical models agreed by the owner on 2026-11-18. **The physical model is a draft and is
still under discussion.** Nothing is built. This document lives in scratch; it is not a spec of record.

Evidence for every figure is in this folder (`probe_*.py` and their `.out.txt` files), measured on the
15-16 November 2026 build. Working notes with the full history of the discussion: `models.md`.

## 1. Why

The pipeline grew from research. Its central table, `private_markets_holdings`, is both the working surface that
many steps rewrite and the published output. The owner's concern is that results are not reliable or repeatable.

What the probes found:

| Area | Finding |
|---|---|
| Keys | Sound. `row_id` is unique on 813,880 rows; fund + date + scope + position has no duplicates; the identity registry matches the holdings on every row. |
| Attributes at the wrong level | 2,700 of 36,007 borrowers carry more than one sector. 1,701 positions change asset category between quarters and 654 change lien. |
| First stored layer | Already interpreted. Tagged facts are kept only as raw files; each extractor re-parses them. |
| Evidence | Held in three forms (source columns, a JSON column, a ledger for 8 fields in 61 funds). Inferred values share a column with real sources. |
| Findings | Two grains with no shared key (row level, and fund + rule + period). Neither carries a release. |
| Corrections | About 20 stores with different key shapes. |
| Missing tables | Fund period, schedule, release, check, cohort membership. |
| History | One build stamp; each build overwrites the last. |

An earlier refactor programme (13 candidate builds, retired 2026-09-29) had a sound design and failed on delivery:
a big-bang change verified by whole-universe builds of about 5.5 hours. This design is delivered per fund.

## 2. Scope

- BDCs only. Non-cohort BDCs and N-PORT are excluded entirely for now. Because a fund is processed on its own,
  adding them later is not expected to be hard.
- Work is proven on the five v0.5 funds first.
- Built as a new package inside this repository. The existing pipeline keeps running until the new one
  reproduces it for the five v0.5 funds.

## 3. Conceptual model (agreed)

```
Adviser 1--* Fund 1--* Fund period 1--* Schedule 1--* Observation *--1 Position *--1 Entity
Fund 1--* Filing 1--1 Document 1--* Schedule line 1--* Tagged fact
Observation 1--* Evidence --> tagged fact | printed cell | heading | footnote | name string
Check 1--* Finding *--* Decision 1--* Correction
Release 1--* (Fund period, Schedule, Observation, Finding)
```

| Group | Entity | Meaning |
|---|---|---|
| As filed | Fund | One BDC, by CIK, with dated names |
| | Adviser | The fund's manager |
| | Filing, Document | One 10-Q or 10-K, and the inline file as cached |
| | Schedule line | One printed row of a schedule. Kind: schedule of investments, commitments table, cash line |
| | Tagged fact | One XBRL fact with its context. Fund-level facts (NAV, total assets) are tagged facts too |
| Interpretation | Filer reading | How this filer's schedule is read: which contexts are positions, which column holds which field, rate conventions, which of tag and print wins |
| | Evidence | What supports one published value. A derivation rule is recorded separately |
| Published | Release | One frozen build |
| | Cohort membership | A fund's status in a cohort version |
| | Fund period | One fund at one quarter-end: obligation, filing selected, NAV, totals, income |
| | Schedule | One schedule of investments in one accounting scope (the fund's own, or a named JV's), with its filed total |
| | Observation | What the fund disclosed about one position on one date, after interpretation and correction |
| | Position | One fund's continuing holding of one instrument in one scope |
| | Entity | The borrower |
| Quality | Check, Finding | A rule, and its firing on a row, a schedule or a fund period |
| | Decision | A recorded verdict, ruling, disposition, fix record or check-repair request. Outlives a release |
| | Correction | A change authorised by a decision, applied at a declared step |

Rules:

1. An observation belongs to one schedule and one position. A position belongs to one fund, one scope and at
   most one entity (none only with a reason).
2. A schedule's observations reconcile to its filed total, or the difference is a finding.
3. Every published value has evidence or a named derivation. A correction never erases what was filed.
4. Where tag and print disagree, the filer reading says which wins, and the disagreement is kept.
5. A finding names its subject by a key that survives a rebuild, plus the release.
6. A build reads decisions, corrections and identity. It does not create them.
7. Every observation has a schedule line, or a reason from a closed list: outside the schedule, split across
   rows, not yet resolved by the reader.

Owner decisions on meaning:

| Topic | Decision |
|---|---|
| GICS sector | Belongs to the borrower. The fund's own industry label stays on the observation. |
| Position class (asset category, lien, instrument type) | The position holds the decided value. Each observation keeps the value as read that quarter. A difference is a finding by default. |
| Adviser | An entity. |

Derived, not entities: returns, portfolio metrics, the wide holdings table, the frontend JSON.

## 4. Logical model (agreed)

PK = primary key. "Per release" means `release_id` is part of the key.

### As filed (written once per filing)

| Table | PK | Content |
|---|---|---|
| `fund` | `cik` | `adviser_id` |
| `fund_name` | `cik`, `valid_from` | name |
| `adviser` | `adviser_id` | name, CRD number where known |
| `filing` | `accession` | fund, form, filing date, period, accession amended |
| `document` | `document_id` (content hash) | filing, file name |
| `context` | `accession`, `context_id` | instant or period |
| `context_member` | `accession`, `context_id`, `axis` | member |
| `tagged_fact` | `accession`, `fact_id` | context, concept, unit, value, decimals; schedule line where resolved |
| `schedule_line` | `document_id`, `row_index` | kind, heading path, footnote marks, cell text |

### Interpretation

| Table | PK | Content |
|---|---|---|
| `filer_reading` | `cik`, `reading_version` | valid report-date range, settings, content hash |
| `source_row` | `source_row_id` (accession + context) | role (position, aggregate, comparative, superseded, unresolved), reason |

### Published

| Table | PK | Content |
|---|---|---|
| `release` | `release_id` | input hashes, code version, status |
| `cohort_membership` | `cohort_version`, `cik` | active, deferred, held back |
| `fund_period` | per release; `cik`, `report_date` | obligation status, filing selected, about a dozen financial columns |
| `schedule` | per release; `cik`, `report_date`, `scope_id` | scope kind, JV name, filed total |
| `observation` | per release; `row_id` | schedule, position, source row, schedule line or reason; measures, terms, status, labels as filed, class as read |
| `observation_field` | per release; `row_id`, `field` | evidence kind and reference, derivation, correction, verification status |
| `position_assignment` | per release; `row_id` | position, method, score |
| `position` | `position_id` | fund, scope, entity or reason, decided class |
| `entity` | `entity_id` | canonical name, GICS sector and its basis |
| `entity_alias` | `entity_id`, `name_variant` | |

`row_id` stays `hash(accession + context)`. Position and entity ids are durable; the assignment of a row to them
is per release. Fund-period financials come from the existing fund-level outputs (`fund_financials`,
`bdc_fund_income`, `bdc_fund_highlights`), each referenced by accession + concept + period.

### Quality

| Table | PK | Content |
|---|---|---|
| `check` | `check_id`, `version` | subject grain, severity, evidence strength |
| `finding` | `finding_id` = hash(check, subject key) | subject type and key |
| `finding_occurrence` | per release; `finding_id` | observed values |
| `decision` | `decision_id` | type, statement, evidence, decided by, validity condition |
| `decision_finding` | `decision_id`, `finding_id` | |
| `correction` | `correction_id` | decision, target (source row + field, or add / remove a row), value, step |
| `correction_application` | per release; `correction_id` | applied, no-op, rejected, failed |

A finding's state is derived from its occurrences and decisions. It is not a stored, editable column.

Retention: findings, decisions and corrections are kept for every release. Observations are kept for signed-off
releases and the current one.

## 5. Physical model (DRAFT, under discussion)

Agreed so far: Parquet is the store and DuckDB the engine; each filing is parsed once into a fact table that
everything reads; dbt is the SQL framework (the owner is learning dbt through this work); Python stays for
parsing and filer interpretation.

Proposed layout, not yet agreed:

```
data/
  raw/          cached filings, as today
  filed/        parsed once per filing, never rewritten      cik=<cik>/accession=<acc>/
  reference/    fund, adviser, filing, cohort, FX, GICS, checks
  decisions/    append-only, as today
  corrections/  one table
  readings/     filer readings per fund, versioned
  identity/     registry; changed only by an explicit allocate step
  releases/<release_id>/
    interpreted/  published/  quality/                       each cik=<cik>/
    marts/        star schema and the wide holdings table
  releases/CURRENT
```

Sizes for the 61 cohort funds: 4.95M tagged facts, 1.22M contexts, 1.74M context members, about 0.56M source
rows, 0.28M observations. Small for DuckDB.

Marts: `fact_observation`, `dim_fund`, `dim_adviser`, `dim_entity`, `dim_position`, `dim_filing`, `dim_date`, and
`private_markets_holdings` kept as a compatibility output for existing checks and the frontend export.

Checked on every build: keys unique and references resolved; each schedule against its filed total; every source
row has one role; every observation has a line or a reason; same inputs give the same content hash per fund.

Open physical points:

| # | Point | State |
|---|---|---|
| 1 | Order of work | DECIDED by owner 2026-11-18 (revised the same day): marts first and kept small, as a dbt project over today's outputs; then the parse-once filed layer; then the middle (source rows, observations, corrections) last, so it is written once with its input and its output contract both fixed. The dbt staging models are the seam. **Only the five v0.5 funds, so that no large batch job runs.** |
| 2 | Findings ledger on dbt | Discussed 2026-11-18; see section 6. No decision. |
| 3 | Where position and entity attributes are stored | DECIDED by owner 2026-11-18: as append-only decision records beside the registry, keyed on a stable anchor, not on the id. Position class is anchored on the `row_id` of the position's earliest observation; entity sector on the borrower's normalised name key. The build joins them to whatever ids it allocates. The registry keeps identity and assignment only. Background: ids are not durable today (carry-over from the prior registry is switched off by owner ruling 2026-10-05). |
| 4 | How a release is assembled | DECIDED by owner 2026-11-18: a fund build is the unit (inputs: that fund's filings, reading, corrections, decisions, shared reference data, code version; outputs: one partition and a manifest with an input hash and a content hash). A release is a manifest of fund builds; a fund whose input hash is unchanged is carried forward by reference. A release is today's batch under another name: `CURRENT` moves last, after integrity checks, the fund-by-fund comparison with the previous release, and the owner's go. Entity resolution is cross-fund, so it is a separate explicit step whose output is a pinned input to fund builds. |
| 5 | How the existing overrides map onto the target | DECIDED by owner 2026-11-18: not converted. A loader presents the existing stores as the target tables so the wrapper and correction skills keep working. Four groups: how to read a filer (wrappers, rate grammars, identifier anchors, rate conventions, highlights wrappers) to `readings/`; row-level changes (two correction CSVs, aggregate-row overrides, spread corrections, printed rows declared in wrappers) to `corrections/`; rules that select rows (investigate rules, B2 templates) to `corrections/` as a second kind; decisions (dispositions, verdict retirements, oracle exceptions, match overrides) to `decisions/`. `agent_anchor` feeds `schedule`; the cohort manifest feeds `cohort_membership`. **This changes the logical model: `correction` has two kinds, a single-row change and a rule that selects rows.** |
| 6 | What dbt covers | My recommendation, carried with point 1 and not separately confirmed: marts and structural checks at first, extending backwards as each layer is replaced. |
| 7 | dbt is not installed | Checked 2026-11-18: no dbt package in the project's Python 3.13.5; DuckDB 1.4.3 is present. A September trial project exists at `spikes/dbt_roundtrip/`. Installing dbt needs the owner's go. |

## 6. Findings ledger on dbt (discussion, no decision)

The ledger has three parts and they fit dbt differently.

| Part | Fit | Note |
|---|---|---|
| Structural checks on the new tables (keys, references, not null) | Good | dbt's built-in tests. New checks, so nothing to keep equal to an old result. |
| Detection rules that are SQL over tables | Good, as models | Written as dbt models that output finding rows, not as dbt tests: a test only says pass or fail and overwrites its failing rows each run. |
| Source reconciliation | Good once the fact table exists | Becomes a join against `tagged_fact`. |
| Checks that read the document, fuzzy matching, agent review | Stay in Python | They write to the same finding table. |
| Status from decisions (standing rulings, superseded entries, validity) | Leave in Python for now | Built 2026-11-12 and only just in use. |

Risks: finding ids must not change (1,845 of 2,180 decisions name finding ids); porting a rule is a check change
under the acceptance contract and needs proof that old and new raise the same findings; two systems run side by
side until the port is finished.

## 7. Not decided, not covered

- Why the current build takes 75-90 minutes and 11 GB. Data volume does not explain it.
- The 1,005 funded loans classed as unfunded commitments by the printed-row reader (cause not established).
- How the five-fund reproduction test is defined (which columns, what tolerance).
- Any change to AGENTS.md, the acceptance contract or the findings workflow.
