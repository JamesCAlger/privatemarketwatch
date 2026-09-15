# 02 Data contract: grain, fields, related records and conventions

Consolidated 2026-09-12. Implements [decisions](01_decisions.md) D01-D13. The physical ordered schema authority remains `pipeline/output_schemas.py`; enum and applicability checks remain `pipeline/column_validation.py`; the original 88-column field map is `docs/reference/programme_field_disposition.csv`. This document defines meaning. Implementation update, 2026-09-14: the canonical production CSV still has 88 columns; the isolated candidate writer implements the ten financial additions and two accounting-scope columns below, for 100 final columns. Targeted checks pass; fresh full-candidate integration remains required. No candidate schema or data has been adopted into production.

## 1. Grain, keys and time

Three identities are never conflated:

- **Entity**: the borrower or investee company. One company can issue several instruments and appear in several funds.
- **Position**: one fund's continuing holding of one disclosed instrument or lot within one accounting scope.
- **Observation**: what the fund disclosed about that position on one date, as selected in one release.

| Key | Meaning and stability |
|---|---|
| `release_id` (R) | One frozen, evaluated data snapshot. Every release-bound join includes it. |
| `cik` | Ten-digit padded text. |
| `document_id` | One exact cached document version: accession, document name, content hash. |
| `row_id` | One normalized source-selected observation. Today `hash(accession + contextRef)` with a stable fallback. Reused for corrections to the same source identity. |
| `entity_id` | Durable borrower identity. Today allocated sequentially per rebuild; durability is plan package P7. |
| `position_id` | Durable within-fund, within-scope continuity identity. Today blank in the canonical CSV (see [plan defect ledger](05_plan.md)). |
| `accounting_scope_id` | Reporting owner and basis: parent schedule versus a named JV's underlying schedule. |

Observation primary key is `(R, row_id)`. At most one observation occupies `(R, cik, report_date, accounting_scope_id, position_id)`; concurrent lots get separate position IDs. Every retained observation has a position ID, including an explicit unresolved singleton. Entity assignment may be null with a reason.

Time: `report_date` is the economic observation date (a comparative December schedule in a March filing has a December `report_date`); `filing_date` is separate; decision records carry `recorded_at` in UTC; validity intervals are `[from, to)`.

Types: dates `DATE`, IDs and enums `VARCHAR`, flags `BOOLEAN`, counts `BIGINT`, money and rates `DOUBLE`. Null, numeric zero, source dash and negative are four different states and stay different.

Worked example: Fund A's Acme first-lien loan in March and June is one position with two observations; its Acme equity is a second position; Fund B's Acme loan is a third position. All three link to one Acme entity. Cross-filer instrument identity is out of scope.

## 2. Field families

Each of the 88 existing fields belongs to one family in the disposition CSV. Values not named by a delta keep their existing contract.

| Family | Target meaning | Writer |
|---|---|---|
| H01 filing and observation | `cik` is the fund; `entity_name` is the filer; `report_date` is the observation date; accession, form and selected version retained. | Extraction plus period selection |
| H02 names and identifiers | Source wording kept in evidence; normalized name for matching and display. `cusip`, `isin`, `lei`, `ticker` describe the investee, never the BDC. Absence is not inferred. | Staging |
| H03 monetary | `fair_value` and analytical `cost` are USD; original amount and unit kept in evidence. `cost_reported` distinct from proxy. Principal stays original-unit with a separate USD equivalent. | Normalization before finalization |
| H04 percentages | `pct_of_net_assets` is the reported figure in percentage points, never overwritten by a NAV ratio. Calculated NAV exposure and portfolio weight are separate. | Reported in normalization; calculated in analytics |
| H05 classification | Existing vocabularies retained; each assignment has evidence and rule version. `fair_value_level` is source hierarchy, not inferred Level 3. | Deterministic rules plus versioned reviewed decisions |
| H06 rates | `interest_rate` is all-in in percentage points; cash and PIK components and reported kind retained. No imputation into public calculations. Storage and income formula flip together. | Convention-aware normalization |
| H07 maturity | Exact date wins; month/year gives month-end with month precision; text and precision retained. | Staging, one shared interpretation |
| H08 BDC descriptors | Normalized identifier is a working key, not a quotation. Dimensions and country wording retained. | Extraction |
| H09 provenance | Existing pathway fields kept; corrections never erase the original fact; verification separate from derivation. | Existing provenance producers |
| H10 non-accrual and PIK | Detection flags stay flags. Add an evidence-aware status. Strict current PIK is a separate artifact. | Existing PIK modules |
| H11 accounting scope | `is_subsidiary`, `axis_profile`, `jv_subsidiary` retained as signals. Add record class and anchor membership. No global drop. | Scope classification |
| H12 entity resolution | `entity_id` durable; `canonical_name` is its alias. Group links are dated edges. | Resolver plus registry |
| H13 industry | `extracted_industry` kept with method. Add `gics_sector`; `gics_sub_industry` optional. Today sector is derived from sub-industry at export time. | Existing GICS pipelines |
| H14 continuity | `position_key` is a candidate discriminator; `position_id` becomes durable. Unmatched is not proof of origination or sale. | Matcher plus registry, before finalization |
| H15 observation identity | `row_id` and `row_id_basis` kept; aliases for collision and fallback changes. Mutable FV is never identity. | Finalizer validates uniqueness |
| H16 shared N-PORT fields | Fourteen `nport_*` fields stay supported and optional for BDC rows. | N-PORT staging |

## 3. Monetary, rate, maturity and status rules

**Currency and FX (D03).** Resolve each monetary field separately; principal currency says nothing about cost or FV currency. Evidence order: explicit field or cell denomination; coherent document unit definition; inherited table denomination; then `assumed_usd`. Printed versus tagged disagreement is a retained source conflict, not resolved mechanically. Genuine foreign FV without a reported USD equivalent converts after unit adjudication, using Federal Reserve H.10 rates as published by FRED (owner decision 2026-09-15: the single canonical FX source, USD per unit): latest observation on or before the balance date, at most seven days old, decimal arithmetic, no interpolation, no lookahead. Adjudication is automatic when the cached XBRL instance defines the fact unit as one ISO-4217 measure other than USD (the document unit definition, not unit-reference spelling); unresolved units still need a manual decision. Missing or stale rates yield `FX_unavailable` or `FX_stale` and count as unassessable exposure. The admitted quote package is built by `scripts/build_fx_quotes.py` from the cached FRED series (`scripts/fetch_fx_fred.py`) and pinned by source hash.

| Source case | Required treatment |
|---|---|
| Apollo Debt Solutions, Mar-2026, Forterro SARON loan: principal printed CHF, cost and FV tagged AFN | Resolve cost and FV independently of principal; never convert the AFN tags. |
| Same filing, Forterro STIBOR loan: principal SEK, cost and FV tagged RSD | Separate facility, separate conflict; no global RSD rule. |
| Antares, Sep-2025, BigTime: principal prints $200 thousand, inline unit EGP | Source-grounded USD correction. |
| Antares, Mar-2026, Riser Interco: prints GBP981 thousand, inline unit EGP | Source-grounded GBP correction; counterexample to replacing all EGP with USD. |
| Apollo, Jun-2024, Delivery Hero: prints Korean won, tagged KPW | Later filing says South Korean won; corroborates KRW but does not certify the older disclosure. |

**Cost (D02).** Analytical `cost` is usable reported cost first, otherwise the earliest source-valid FV of the same established position under latest-best history, with donor row, date, release and method `first_observed_fv_proxy` recorded. Reported zero wins. Invalid cost or pending FX is not absence. Multiple earliest donors are an ambiguity, not a tie broken by row order. Matching consumes reported cost only; proxies are computed after identity.

**Implementation update, 2026-09-14 (verification in progress).** `pipeline/monetary_fx.py` accepts optional `data/reference/monetary_conversion/quotes.json` and `unit_adjudications.json` through the existing admission manifest, with legacy admission disabled. The version-1 package contains `quotes` or `decisions` arrays. Each FV decision identifies its observation, `field: fair_value`, source value, reviewed currency and source document hash. Each FRED H.10 observation retains its ID, date, `usd_per_unit` legs, series ids and a relative local source path/hash (amended 2026-09-15 from the ECB per-EUR design). Document-resolved ISO-4217 units are adjudicated automatically with a deterministic `unit:<row_id>` decision; unresolved units and misleading tags still require a manual decision. The real FRED package was imported 2026-09-15. Original FV, currency, adjudication and quote inputs stay in `src_facts`; missing conversion leaves USD FV null and the position retained. The financial finalizer, return inputs and public sums share that result. Replaying a finalized conversion requires the same admitted unit decision and selected quote evidence; changed or withdrawn inputs require rebuilding from cached source. A newly available quote cannot silently reuse an earlier unavailable result. Historical cost is not reconstructed using current FX. Independent field assessment rebuilds the USD reference from separately read source facts and the frozen admitted package; absent conversion support is an assessability shortfall. Public totals disclose missing USD FV counts, and field evidence distinguishes original foreign amounts from calculated USD values.

**Rates (D01).** Add `interest_rate_reported`, `interest_rate_kind` (`cash`, `all_in`, `effective_yield`, `other`, `unresolved`), `interest_rate_cash`, `basis_spread_kind`. All-in equals supported cash plus supported PIK; a cash rate with unknown PIK does not prove all-in. Effective yield stays outside coupon analytics. The current storage carries the cash leg; the all-in flip and the income formula in `pipeline/index_returns.py` change atomically (plan P6).

**Maturity (D06).** `maturity_precision` in `day`, `month`, `year`, `unknown`; `maturity_status` in `dated`, `partial`, `perpetual`, `not_disclosed`, `unresolved`, `not_applicable`. Matching uses precision-aware intervals.

**Statuses.** `nonaccrual_status` in `nonaccrual`, `accrual_confirmed`, `unknown`, `not_applicable`. A missing flag is unknown. PIK terms, current PIK payment or accrual evidence and stress amendments remain three separate claims; `pik_terms_started` is never labelled confirmed distressed PIK.

**GICS (D09).** `gics_sector` is a taxonomy-valid sector with a decision reference. A supported sub-industry supplies its parent sector deterministically. Inferred stays inferred.

## 4. Physical additions

Added through `pipeline/output_schemas.py` in one versioned migration that updates writers, companions, readers and applicability tests together.

| Column | Type | Constraint |
|---|---|---|
| `cost_reported` | DOUBLE | Nullable; zero retained; absent disclosure distinguished from unresolved conversion in evidence |
| `interest_rate_reported` | DOUBLE | Percentage points with declared meaning |
| `interest_rate_kind` | VARCHAR | Declared kind; `unresolved` when unknown |
| `interest_rate_cash` | DOUBLE | Only when disclosed or deterministically calculable |
| `basis_spread_kind` | VARCHAR | `cash`, `all_in`, `unresolved` |
| `pct_of_net_assets_calculated` | DOUBLE | Null without compatible nonzero NAV |
| `maturity_precision` | VARCHAR | `day`, `month`, `year`, `unknown` |
| `maturity_status` | VARCHAR | Must agree with the date |
| `nonaccrual_status` | VARCHAR | No inferred confirmed-accrual default |
| `gics_sector` | VARCHAR | Nullable pinned-taxonomy sector; unknown is an explicit bucket |
| `accounting_scope_id` | VARCHAR | Reporting CIK plus parent or explicit underlying scope; unresolved subsidiary scope isolated by observation |
| `accounting_record_class` | VARCHAR | `parent_schedule`, `underlying_schedule`, `unresolved_underlying_schedule`; no global subsidiary deletion |

`portfolio_weight_pct` stays a derived metric with a denominator reference. Financial additions are nullable where inapplicable to shared non-BDC rows. Accounting scope is retained for every final observation and recomputed after corrections; per-anchor inclusion belongs in the separate membership relation.

## 5. Related records

Logical relations with concrete keys. Physical names belong to the migration packets; today most of these live in existing artifacts named in the last column.

| Relation | Key | Required content | Existing home |
|---|---|---|---|
| Release | `release_id` | Parent, code and dirty-patch identity, schema and decision versions, input and rule hashes, artifact hashes and counts, verdict | Quarter-pass state, snapshot manifests |
| Fund-quarter obligation | `(cohort_version, cik, report_date)` | Eligibility, operating status, source availability, exception class, selected filing | Cohort manifest and filing index; 910-row register in `programme_reference_evidence_2026-09-09/` |
| Source document | `document_id` | CIK, accession, filing date, form, hash, cache path, media type | Cached filings |
| Source fact | `evidence_id` | Document, context, concept, unit, dimensions, period, precision | `src_facts`, source reconciliation |
| Holding observation | `(R, row_id)` | All typed fields; source selection; entity, position and scope references | `private_markets_holdings.csv` |
| Field state and inputs | `(R, row_id, field)` plus ordered inputs | Availability, derivation, correction history, verification; typed input edges (reported fact, FX, donor, denominator, inference evidence) | Provenance ledger, correction audit |
| Entity and assignment | `entity_id`; `(R, row_id)` | Aliases, method, evidence, merge and split redirects; unresolved explicit | `entity_resolution.py` lookup and overrides |
| Position and links | `position_id`; `(R, link_id)` | Members, predecessor and successor, method, confirmed/uncertain/unmatched, revisions | `position_matching.py`, `position_id_registry.py`, match CSVs |
| Classification decision | decision version | Subject, level, value or abstention, model and taxonomy versions, evidence, review status | GICS caches and review stores |
| Accounting membership | `(R, anchor_id, row_id)` | Included, excluded or unknown with reason; anchor basis, currency, date | Subsidiary flags, anchor leaves, published basis |
| Metric result | `(R, metric_id)` | Formula version, immutable membership, denominator, coverage, null policy | Export functions |
| Validation result | `(R, check_id, evaluation_id)` | Check version, thresholds version, population, counts, status, evidence hash | `quarter_acceptance.json`, shadow ledger |

Registry state is a pinned input and a candidate output. Trials never mutate the accepted registry.

## 6. Four evidence axes

| Axis | States |
|---|---|
| Availability | `present`, `not_disclosed`, `not_applicable`, `unresolved`, `missing_source`, `failed_extraction` |
| Derivation | `reported`, `normalized`, `calculated`, `inferred`, `approved_default` |
| Correction | Zero or more versioned events with mechanism and before/after |
| Verification | `not_checked`, `source_matched`, `independently_reviewed`, `disputed`, `not_assessable` |

A proxy cost is `present`, `calculated`, method `first_observed_fv_proxy`, with an input recording the absent reported cost. The axes are never collapsed into one label such as "verified". A formula using assumed USD or inferred GICS does not become wholly reported.

## 7. Identity allocation

New IDs are UUIDv5 from `(identity kind, governed scope, immutable creation-decision ID)` under a fixed programme namespace, persisted as `VARCHAR`. Entity scope is global; position scope includes filer and accounting scope. Reordering or adding observations never changes an allocated ID. Restatements get new observation anchors; an evidenced same instrument keeps its position ID. Splits create new IDs with reassignment history; merges name a survivor and retire the other only when nothing points to it. Legacy IDs survive only as `(legacy build fingerprint, legacy ID)` aliases. The existing opt-in registry keys on `cik | source | report_date | raw identifier | principal | shares` with dimension and lot discriminators and has a measured raw-identifier drift near 1.6%; it is the starting point, not the accepted design.

## 8. Structural invariants

| ID | Invariant |
|---|---|
| M01 | Primary keys unique; typed foreign keys resolve; derived joins include the release. |
| M02 | Every cohort-quarter obligation exists independently of extracted rows; exclusions have evidence. |
| M03 | Each retained lot has one observation and one position assignment; concurrent lots never share an ID. |
| M04 | Continuity stays within one fund and compatible scope; name similarity alone never merges. |
| M05 | Registry IDs survive reorder, rebuild and unrelated additions; revisions are versioned; a failed trial cannot mutate accepted state. |
| M06 | Every governed field has a state consistent with its value; zero, null, dash and negative keep their meanings. |
| M07 | Every evidence link resolves to the right document version; inputs form an acyclic graph. |
| M08 | Cost proxies use a same-position donor only when reported cost is absent; reported zero wins. |
| M09 | No cross-currency public sum, no rate completion, no fabricated precise maturity, no inferred GICS labelled reported. |
| M10 | Anchor membership and public membership are separate and reproducible. |
| M11 | Headline FV and instrument and sector breakdowns reconcile exactly to the same public population under one arithmetic convention. |
| M12 | Proposals cannot affect final values without the promotion route; final validation runs after the last value-changing step; no later writer changes a sealed release. |

## 9. Acceptance cases for the contract

| Case | Required result |
|---|---|
| Acme loan and equity, two funds, two quarters | One entity, three positions, four observations. |
| Bain Jun-2023 ordinary and preferred equity | Two observations; both costs reported even when equal to FV. |
| Sentinel parent term loan versus ULTRA III JV delayed draw, Dec-2025 | Same borrower text and date, distinct scope, position and observation keys; negative values eligible. |
| Esdec Q3-2023 printed EUR principal versus inline USD | Both representations retained with an interpretation decision; USD FV and cost not converted because principal is EUR. |
| Paragon 3.38% PIK displayed versus inconsistent inline scale | Scale and display evidence retained; tag agreement alone is not a verified coupon. |
| First observed FV is zero, later cost absent | Zero is the documented donor. |
| Entity split after an earlier wrong merge | New release records the revision and rebinds sector assignments; earlier release intact. |
| Crash after registry allocation, before export | Retry reuses the candidate-local allocation; accepted registry unchanged. |

Implementation clarification, 2026-09-13: the internal N-PORT source retains its disclosed coupon-type vocabulary `Fixed`, `Floating`, or `Variable`. `Variable` is admitted only for `source=nport`; it is not coerced to a BDC floating-rate classification. The preflight found three such records; the pinned raw N-PORT input contains83,740. This does not expand the BDC-only public cohort or establish the cash/all-in meaning of their annualized rates.

