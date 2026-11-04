# 02 Data contract: grain, fields, related records and conventions

Consolidated 2026-09-12. Implements [decisions](01_decisions.md) D01-D13. The physical ordered schema authority remains `pipeline/output_schemas.py`; enum and applicability checks remain `pipeline/column_validation.py`; the original 88-column field map is `docs/reference/programme_field_disposition.csv`. This document defines meaning. Implementation update, 2026-09-14: the canonical production CSV still has 88 columns; the isolated candidate writer implements the ten financial additions and two accounting-scope columns below, for 100 final columns. Targeted checks pass; fresh full-candidate integration remains required. No candidate schema or data has been adopted into production.

**Updated 2026-10-06** (agent, at the owner's request in session). The 2026-09-14 sentence above is superseded: the published `data/output/private_markets_holdings.csv` and its Parquet companion carry all 100 columns (783,763 rows, 339 funds, checked 2026-10-06 against the 2026-10-01 build). The disposition CSV still lists the original 88 fields; the twelve additions are defined in section 4 only. Statements below that begin "Today" were re-checked on that date and corrected where they no longer held. Section 10 lists where the published data does not yet meet this contract. Not re-verified in this pass: sections 5, 6 and 9, and the related-record homes in section 5.

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
| `entity_id` | Durable borrower identity. As of 2026-10-06 a UUID in the published file; blank on 3,594 rows. Whether it is stable across rebuilds was not measured. |
| `position_id` | Durable within-fund, within-scope continuity identity. As of 2026-10-06 a UUID on every published row, allocated by `pipeline/durable_identity.py`. Carry-over of ids from the previous build is switched off by owner ruling 2026-10-05 (`config.IDENTITY_CONTINUITY_ENABLED = False`), so ids are not yet stable across rebuilds. |
| `accounting_scope_id` | Reporting owner and basis: parent schedule versus a named JV's underlying schedule. |

Observation primary key is `(R, row_id)`. At most one observation occupies `(R, cik, report_date, accounting_scope_id, position_id)`; concurrent lots get separate position IDs. Every retained observation has a position ID, including an explicit unresolved singleton. Entity assignment may be null with a reason.

Time: `report_date` is the economic observation date (a comparative December schedule in a March filing has a December `report_date`); `filing_date` is separate; decision records carry `recorded_at` in UTC; validity intervals are `[from, to)`.

Types: dates `DATE`, IDs and enums `VARCHAR`, flags `BOOLEAN`, counts `BIGINT`, money and rates `DOUBLE`. Null, numeric zero, source dash and negative are four different states and stay different.

Worked example: Fund A's Acme first-lien loan in March and June is one position with two observations; its Acme equity is a second position; Fund B's Acme loan is a third position. All three link to one Acme entity. Cross-filer instrument identity is out of scope.

## 2. Field families

Each of the 88 original fields belongs to one family in the disposition CSV; the twelve fields of section 4 belong to the family named in their rule (H03, H04, H06, H07, H10, H11, H13). Values not named by a delta keep their existing contract.

| Family | Target meaning | Writer |
|---|---|---|
| H01 filing and observation | `cik` is the fund; `entity_name` is the filer; `report_date` is the observation date; accession, form and selected version retained. | Extraction plus period selection |
| H02 names and identifiers | Source wording kept in evidence; normalized name for matching and display. `cusip`, `isin`, `lei`, `ticker` describe the investee, never the BDC. Absence is not inferred. | Staging |
| H03 monetary | `fair_value` and analytical `cost` are USD; original amount and unit kept in evidence. `cost_reported` distinct from proxy. Principal stays original-unit with a separate USD equivalent. | Normalization before finalization |
| H04 percentages | `pct_of_net_assets` is the reported figure in percentage points, never overwritten by a NAV ratio. Calculated NAV exposure and portfolio weight are separate. | Reported in normalization; calculated in analytics |
| H05 classification | Existing vocabularies retained; each assignment has evidence and rule version. `fair_value_level` is source hierarchy, not inferred Level 3. | Deterministic rules plus versioned reviewed decisions |
| H06 rates | `interest_rate` is all-in in percentage points; cash and PIK components and reported kind retained. No imputation into public calculations. A filed rate is published only when its kind is known (section 3). | Convention-aware normalization |
| H07 maturity | Exact date wins; month/year gives month-end with month precision; text and precision retained. | Staging, one shared interpretation |
| H08 BDC descriptors | Normalized identifier is a working key, not a quotation. Dimensions and country wording retained. | Extraction |
| H09 provenance | Existing pathway fields kept; corrections never erase the original fact; verification separate from derivation. | Existing provenance producers |
| H10 non-accrual and PIK | Detection flags stay flags. Add an evidence-aware status. Strict current PIK is a separate artifact. | Existing PIK modules |
| H11 accounting scope | `is_subsidiary`, `axis_profile`, `jv_subsidiary` retained as signals. Add record class and anchor membership. No global drop. | Scope classification |
| H12 entity resolution | `entity_id` durable; `canonical_name` is its alias. Group links are dated edges. | Resolver plus registry |
| H13 industry | `extracted_industry` kept with method. Add `gics_sector`; `gics_sub_industry` optional. As of 2026-10-06 `gics_sector` is a column of the published file (446,691 of 783,763 rows filled). | Existing GICS pipelines |
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
| Apollo, Jun-2025, Amey term loan: principal GBP 125.4 million; fair value fact 169.1 million with unit GBP | The fair value is already in dollars (169.1 / 125.4 = 1.349 against a rate of 1.372). Do not convert; see the filer rule below. |

**Filers that state dollar values under a foreign unit tag (added 2026-10-06).** Automatic adjudication assumes the unit tag is the value's currency. For some filers it is not: the tag follows the loan's currency while fair value and cost are in dollars. A wrapper may declare `source_encodings.foreign_unit_values = ["reported_in_usd"]`; `pipeline/monetary_units.py` then records the field as USD with unit status `reported_in_usd`, keeps the tagged currency in `src_facts`, and no conversion runs. Evidence required for the setting: the untouched values sum to the filed total, and fair value over local principal sits at the exchange rate, not at 1. Set for Apollo Debt Solutions, HPS Corporate Lending and BCRED. In the five v0.5 funds every automatically converted row (79) was of this kind. The published file holds 822 converted rows across 35 funds; the others were not checked, so automatic conversion should be treated as unverified for them.

**Principal currency (added 2026-10-06).** `principal_amount_currency` is the currency the document defines for the principal fact's unit, not the unit's name (Apollo names its units `U_USD`, `U_EUR`). `principal_amount_usd` equals the principal when that currency is USD; otherwise it is a reference conversion at the fair-value date rule above, only for filers whose wrapper sets `source_encodings.principal_usd_reference = ["fred_h10"]`.

**Percent of net assets scale (added 2026-10-06).** `pct_of_net_assets` is in percentage points. A filing states it on one scale: twenty or more tagged values summing past 20 are already in percent and are kept as filed; otherwise a value of 0.5 or less is read as a fraction and multiplied by 100. Filers that tag the percent only per industry or category (Ares, Apollo, HPS; Blue Owl from 2025-03-31) leave the column empty; `pct_of_net_assets_calculated` is the comparable figure.

**Cost (D02).** Analytical `cost` is usable reported cost first, otherwise the earliest source-valid FV of the same established position under latest-best history, with donor row, date, release and method `first_observed_fv_proxy` recorded. Reported zero wins. Invalid cost or pending FX is not absence. Multiple earliest donors are an ambiguity, not a tie broken by row order. Matching consumes reported cost only; proxies are computed after identity.

**Implementation update, 2026-09-14 (verification in progress).** `pipeline/monetary_fx.py` accepts optional `data/reference/monetary_conversion/quotes.json` and `unit_adjudications.json` through the existing admission manifest, with legacy admission disabled. The version-1 package contains `quotes` or `decisions` arrays. Each FV decision identifies its observation, `field: fair_value`, source value, reviewed currency and source document hash. Each FRED H.10 observation retains its ID, date, `usd_per_unit` legs, series ids and a relative local source path/hash (amended 2026-09-15 from the ECB per-EUR design). Document-resolved ISO-4217 units are adjudicated automatically with a deterministic `unit:<row_id>` decision; unresolved units and misleading tags still require a manual decision. The real FRED package was imported 2026-09-15. Original FV, currency, adjudication and quote inputs stay in `src_facts`; missing conversion leaves USD FV null and the position retained. The financial finalizer, return inputs and public sums share that result. Replaying a finalized conversion requires the same admitted unit decision and selected quote evidence; changed or withdrawn inputs require rebuilding from cached source. A newly available quote cannot silently reuse an earlier unavailable result. Historical cost is not reconstructed using current FX. Independent field assessment rebuilds the USD reference from separately read source facts and the frozen admitted package; absent conversion support is an assessability shortfall. Public totals disclose missing USD FV counts, and field evidence distinguishes original foreign amounts from calculated USD values.

**Rates (D01).** Add `interest_rate_reported`, `interest_rate_kind` (`cash`, `all_in`, `effective_yield`, `other`, `unresolved`), `interest_rate_cash`, `basis_spread_kind`. All-in equals supported cash plus supported PIK; a cash rate with unknown PIK does not prove all-in. Effective yield stays outside coupon analytics.

**Rates, state at 2026-10-06.** The flip described in plan P6 has happened in code: the finalizer (`pipeline/financial_conventions.py`) writes the all-in rate to `interest_rate`, and the income formula in `pipeline/index_returns.py` uses that rate without adding PIK. The kind of a filed rate comes from, in order: an explicit kind supplied by a governed source producer; the tag's own name (effective yield, paid in cash, all-in); for the plain rate tag or a rate read from the row text, `all_in` when the row has no PIK rate and its text does not name PIK, because without PIK the all-in and the cash coupon are one number (every filer, owner instruction 2026-10-06); the filer's reviewed reading of its plain rate tag, `source_encodings.filed_rate_reading = ["all_in"]` or `["cash_leg"]` in the wrapper; otherwise `unresolved`, and `interest_rate` stays empty with the filed number kept in `interest_rate_reported`. Under an `all_in` reading a row whose PIK rate exceeds the filed rate contradicts the reading and stays `unresolved`. Under `cash_leg` the earlier rule holds: all-in needs a PIK rate on the row. Evidence required for a reading: fully PIK loans whose filed rate equals the PIK rate (all-in), or filed rates below the PIK rate across the fund (cash leg). Set to `all_in` for BCRED, HPS, Apollo and Ares (commit fdac285). `basis_spread` is in percentage points; a spread read from the row text that is 25 or more is in basis points and is divided by 100. `basis_spread_kind` is `unresolved` on every published row.

**Coupon filed only in the PIK tag (added 2026-10-06).** Where a wrapper sets `source_encodings.pik_only_tag_reading = ["coupon"]`, a loan row with a PIK rate, no plain rate and no spread publishes the PIK rate as `interest_rate` (kind `all_in`, transform `interest_rate:pik_only`, `interest_rate_reported` empty). Set for Ares only, on printed-schedule evidence. It is not the default: HPS and Blue Owl file a margin over the reference rate in the same tag, so for some of their rows `pik_rate` holds a margin, not a rate. The final schema check accepts a rate with no filed plain rate only when it carries this transform and equals `pik_rate`.

**Maturity (D06).** `maturity_precision` in `day`, `month`, `year`, `unknown`; `maturity_status` in `dated`, `partial`, `perpetual`, `not_disclosed`, `unresolved`, `not_applicable`. Matching uses precision-aware intervals.

**Statuses.** `nonaccrual_status` in `nonaccrual`, `accrual_confirmed`, `unknown`, `not_applicable`. A missing flag is unknown. PIK terms, current PIK payment or accrual evidence and stress amendments remain three separate claims; `pik_terms_started` is never labelled confirmed distressed PIK.

**GICS (D09).** `gics_sector` is a taxonomy-valid sector with a decision reference. A supported sub-industry supplies its parent sector deterministically. Inferred stays inferred.

## 4. Physical additions

Added through `pipeline/output_schemas.py` in one versioned migration that updates writers, companions, readers and applicability tests together. All twelve are in the published file as of 2026-10-06.

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

New IDs are UUIDv5 from `(identity kind, governed scope, immutable creation-decision ID)` under a fixed programme namespace, persisted as `VARCHAR`. Entity scope is global; position scope includes filer and accounting scope. Reordering or adding observations never changes an allocated ID. Restatements get new observation anchors; an evidenced same instrument keeps its position ID. Splits create new IDs with reassignment history; merges name a survivor and retire the other only when nothing points to it. Legacy IDs survive only as `(legacy build fingerprint, legacy ID)` aliases. The existing opt-in registry keys on `cik | source | report_date | raw identifier | principal | shares` with dimension and lot discriminators and has a measured raw-identifier drift near 1.6%; it is the starting point, not the accepted design. State at 2026-10-06: the finalizer allocates through `pipeline/durable_identity.py` and `data/output/identity_registry.duckdb`; published ids are UUIDs; the older opt-in registry is not on the production path; carry-over from the prior registry is switched off (owner ruling 2026-10-05) until sign-off.

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

## 10. Where the published data departs from this contract (2026-10-06)

Measured on the published file (2026-10-01 build) unless a sandbox is named. The fund-sandbox figures are for the five v0.5 funds
(`scripts/fund_ledger_trial.py`, label `five7`); none of the fixes behind them is in the published file until a full rebuild.

| Contract point | Departure | State |
|---|---|---|
| H06: `interest_rate` is the all-in rate | Published on 4,229 of 563,602 BDC rows. 349,045 rows have a filed rate that is withheld because the kind is `unresolved` | Fixed in code two ways: rows with no PIK publish for every filer (estimate from the published file: 317,313 rows in 173 funds, not checked outside the v0.5 funds); rows with PIK publish for four v0.5 funds by a wrapper reading. About 27,000 PIK rows in other funds, and 11,778 paid-in-cash rows with no PIK rate, stay withheld |
| H06: `basis_spread_kind` | `unresolved` on all rows | Open; no reading mechanism exists for it |
| H03: fair value and cost are USD | Automatic conversion multiplied dollar values by the exchange rate for filers that tag the loan's currency (79 rows in the v0.5 funds, e.g. Apollo Amey 169.1M published as 232.0M). 3 published rows carry a non-USD `fair_value_currency` (AFN, RSD, AED) | Fixed in code for Apollo, HPS, BCRED. 743 converted rows in 32 other funds are unchecked |
| H03: principal has a separate USD equivalent | Empty for every Apollo row (unit names read as currency codes) and for foreign principal generally (the rate file was empty) | Fixed in code; reference conversion on for the five funds only |
| H04: `pct_of_net_assets` is the reported figure in percentage points | Blue Owl 2023-06-30: 195 rows multiplied by 100 (quarter summed to 5,084) | Fixed in code for every filer; checked on the five funds |
| H02: normalized name for display | Ares `issuer_name` carried the instrument on 18,195 of 18,374 rows; 255 Apollo rows carried industry and instrument | Fixed by wrapper settings |
| M03: each retained lot has one observation | BCRED dropped 4 to 13 positions a quarter and Ares up to 3 (classed as category rollups). Ares lost eight positions in two filings whose value is tagged on the issuer-name axis | Fixed by wrapper settings and two pinned rules. The extractor still reads a position's value from its own context only |
| M11: totals reconcile to the public population | Issuer-level and affiliate-table rows published as positions (Blue Owl 365M to 1.0B a quarter, Ares 18M to 112M, Apollo heading rows) | Fixed by rules and wrapper settings. Sandbox: published equals filed (plus cash rows) within 0.45M in 63 of 69 fund-quarters |
| M12: no proposal affects final values without the promotion route | Seven rule files written in session 2026-10-05/06 (and one existing rule widened) load as legacy inputs: there is no admission manifest in `data/overrides/agent_investigate_rules` | Open; owner decision |
| M05: registry ids survive rebuilds | Carry-over switched off | Open until sign-off |
| M06: every governed field has a state consistent with its value | `interest_rate:coupon_unresolved` was written on rows that file no rate | Fixed in code (decision D-010): written only when a filed rate cannot be read |
| H06: `pik_rate` is a rate | Where a loan's coupon is a PIK margin over a reference rate, the tag holds the margin | HPS: the margin is published as `basis_spread` on 60 rows whose reference rate is tagged (`pik_only_tag_reading: ["margin"]`). Open for Blue Owl: the reference rate is not tagged on its 247 PIK-only rows, and rows with both a spread and a PIK figure carry the cash margin only in `basis_spread` |
| H06: a filed rate is published | Ares filed some rates on a context next to the value row (five loans); Apollo printed one bond rate in row text only and tagged one rate a hundred times too small | Fixed: wrapper setting `rate_only_contexts` for Ares; row corrections for Apollo |
| H01: asset category | Preferred units, a loan and a bond classed as common equity; Blue Owl's Amergin units classed as a credit fund interest | Corrected row by row for the flagged quarters (13 rows in `row_corrections.csv`). Amergin keeps the wrong class in quarters where no check fired |
| H03: principal | Ares 2022-09-30 SDLP certificates carry the filed principal of 269.8 billion (tag and printed page) against a value of 1,121M | Left as filed; recorded as dispositions DS-005, DS-022, DS-023 |
| H03: cost is the filed cost | Blue Owl undrawn lines from 2024-12-31 carried a negative proxy cost (508 rows) | Fixed in code (owner ruling 2026-10-06): a negative first value gives no proxy; cost is empty. Every fund; checked on the five |
| Fund-level flows are quarterly | In a 10-K quarter `total_investment_income`, `total_expenses` and `net_investment_income` are the annual amount divided by four (`pipeline/bdc_fund_income.py`). The new `net_expenses` is the true quarter | Open; found 2026-10-06, not changed |
| M11: totals reconcile | Apollo 2026-03-31 was 3,272K below the printed total (two wrongly signed tags). BCRED was above the filed total in four quarters (misspelled JV labels, one footnote figure) | Fixed. Sandbox `five15`: published equals filed within 0.5M in 69 of 69 fund-quarters of the v0.5 funds |
| M12: no proposal affects final values without the promotion route | Standing dispositions (`data/overrides/finding_dispositions/`) were written and accepted by an agent under the owner's in-session permission of 2026-10-06, not by the owner or a deterministic check | Owner review of `docs/investigations/v05_decision_log.md` |

Not assessed in this pass: M01, M02, M04, M07, M08, M09, M10 and the acceptance cases in section 9.
