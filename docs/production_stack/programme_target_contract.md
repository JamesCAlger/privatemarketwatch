# Programme target contract and schema changes

Date: 2026-09-09. Version: 0.2; verification status updated 2026-09-11. This target design implements the thirteen resolved owner decisions. The target holdings schema is not deployed. [Current specification status](programme_spec_status.md) records section 12's owner acceptance, the completed verification/compatibility definitions for final review and unfinished implementation. Measurement-register sections 12-15 specify the automated reference protocol and all-criterion checks; no human-review prerequisite is introduced.

This extends the [existing 88-column crosswalk](../reference/unified_holdings_contract_crosswalk.md), with an exhaustive [field disposition map](../reference/programme_field_disposition.csv). The [decision sheet](programme_decision_sheet.md) controls financial/product policy and the [measurement register](programme_measurement_register.md) defines how to evaluate the result. Existing crosswalk sections remain dated observations of current behavior; this document describes the target.

The [programme data model](programme_data_model.md) now develops section 3's related-record sketch into concrete grains, keys, relationships, evidence inputs, accounting populations and release invariants. It is the logical architecture; this document retains financial meaning and the proposed ten-column schema delta. The model does not claim that persistent identity, FX handling or citation interfaces have been implemented or validated.

The [processing architecture](programme_processing_architecture.md) develops section 5 into P00-P10 stage contracts, dbt/Python/Arelle boundaries, shared rule precedence, reported-cost matching inputs, candidate recovery and separate data/delivery acceptance. The [physical design](programme_physical_architecture.md) specifies storage, registry snapshots, exact public aggregation and recovery/adoption mechanics; the [implementation plan](programme_implementation_plan.md) defines bounded packages and execution controls. Runtime proof, reference calibration and launch decisions remain outstanding.

The main changes are separate reported and analytical values, explicit evidence and missingness, durable identity, declared accounting populations, and one finalized release. Preserve the existing holding grain and useful extraction, correction and validation machinery. The field names below are concrete design choices for implementation planning, not another set of financial-policy questions.

## 1. Grain, keys and authority

A holding is one retained, normalized observation of a disclosed position or lot for a reporting fund and observation date, selected from a specific filing version. Separate loan tranches, equity stakes, warrants, facilities and disclosed lots remain separate rows. Source presentation duplicates and subtotals require evidence-backed dispositions; they are not additional economic positions.

The required history is thirteen quarters from 2023-03-31 through 2026-03-31. The 70-CIK manifest therefore produces 910 obligation records before lifecycle eligibility is determined. It does not imply 910 operating fund-quarters. Preserve the approved optional opening and forward-test policies.

| Contract | Target authority | Enforcement and consumer |
|---|---|---|
| Financial meaning, applicability and missingness | This target extension plus the accepted decision sheet; original field descriptions retained in the crosswalk where unchanged | Implement the same rules in normalization and acceptance cases. A parser, dashboard or dbt model cannot privately redefine them. |
| Ordered physical artifact schema | Existing [output_schemas.py](../../pipeline/output_schemas.py), extended through a versioned migration | Strict validation of final CSV/Parquet companions. dbt declarations and frontend types implement this contract; discrepancies fail compatibility checks. |
| Field enums and applicability checks | Existing [column_validation.py](../../pipeline/column_validation.py), reconciled with physical/source contracts | Structural errors block candidate assembly. Economic diagnostics have an explicit severity/gate mapping; warnings are not automatically gates. |
| Source extraction and filer interpretation | Existing wrappers, grammars, source facts and applicable per-CIK configurations | Retain source values, units, dimensions and anchors; rule scope is CIK/filing/period-specific where appropriate. |
| Corrections | Existing reviewed proposal, deterministic verification and promotion routes | Versioned rule, evidence, before/after value and application event. Placement in a cache is not independent proof of correctness. |
| Entity and position decisions | Existing resolver/matcher extended with persistent registries and revision records | Final holdings joins a pinned identity snapshot. Identity tools do not rewrite the released holdings artifact afterward. |
| Acceptance numbers and reference evidence | Versioned measurement definitions and independently governed benchmarks; current [quarter thresholds](../../data/reference/quarter_acceptance_thresholds.json) remain live | D12 requires definition and baseline before final numerical approval. Workers cannot lower targets or rewrite held-out labels. |
| Canonical holdings and public aggregates | One finalization path, coordinated by `pipeline.unified_holdings`; exports consume its accepted snapshot | CSV remains canonical until the planned reader migration is separately verified. A release contains compatible companions and downstream products. |

New schema types must be added to `output_schemas.py` deliberately. Existing DOUBLE storage is retained for this design; exact public aggregation means one declared decimal serialization/aggregation convention, not a tolerance for differing populations or independent floating-point reduction orders. Source-rounding tolerances belong to B2/B3, not B4.

## 2. Field-family contract

Every existing field is assigned to one family in the disposition CSV. Each family identifies its proposed authoritative writer, semantic delta and acceptance obligations. Values not addressed by a deliberate delta retain their existing source-specific contract.

| Family | Target meaning and required delta | Authoritative writer / boundary | Decisions; criteria |
|---|---|---|---|
| H01 Filing and observation | `cik` is padded fund identity; `entity_name` names the filer. `report_date` is observation date, distinct from filing date and source context period. `source=bdc` describes the source family even when recovery uses HTML. Retain accession/form and explicit version selection. | Extraction plus period-selection normalization; finalized observation joins | D05/D11; A1/A3/B1 |
| H02 Names and external identifiers | Preserve source wording through evidence; normalize names/descriptions for matching/display. `cusip`, `isin`, `lei`, `ticker` remain optional identifiers of the investee/security, never the BDC's own ticker. Identifier absence does not require inference. | Staging/name normalization; reviewed entity decisions separately | D07; B1/C1/C3/D1 |
| H03 Monetary measures | Preserve original amounts/units in evidence. Normalize the published valuation/cost basis to USD before aggregation; distinguish reported cost from the approved FV proxy. Original principal stays original-unit; USD principal is separate. Details below. | Monetary normalization and cost derivation before finalization | D02/D03; B1/B2/B3/B4 |
| H04 Percentages | `pct_of_net_assets` becomes source-reported percentage points after deterministic unit normalization; it is never overwritten by a reconstructed NAV ratio. Add separately named calculated NAV exposure and portfolio weight. | Reported value in normalization; calculated metrics in shared analytics models | D04; B1/B2/B3/B4/E2 |
| H05 Instrument and exposure classification | Retain `asset_category`, `issuer_category`, legacy `index_classification`, `exposure_type`, `asset_class`, `lien_position` and `instrument_type` meanings/vocabularies subject to reconciled mappings. Each assignment has evidence and rule version. `fair_value_level` is optional source hierarchy, not inferred Level 3 for every BDC. | Deterministic classification plus versioned reviewed decisions | D09/D13; B1/D1/D2/E2 |
| H06 Rates | `interest_rate` is comparable all-in stated coupon in percentage points; preserve reported kind/value and supported cash/PIK components. Preserve spread kind and benchmark evidence. No missing-rate or benchmark-value imputation into public calculations. | Convention-aware normalization; atomic migration with income and export consumers | D01; B1/B2/B5 |
| H07 Maturity | Exact dates take precedence; disclosed month/year gives month-end with month precision. Preserve source text, precision and unknown/perpetual status. Year-only maturity stays partial without inventing a month. | Existing staging/HTML interpretation consolidated into one shared contract | D06; B1/B2/C3/E2 |
| H08 BDC source descriptors | Retain normalized BDC identifier as a working key, not a verbatim quotation. Preserve dimensions and source country wording. Reported UGL text remains distinct from derived FV minus cost. | Extraction/staging with field-level source anchors | D10; B1/B2/D1/D4 |
| H09 Provenance and corrections | Retain existing pathway/event fields for compatibility; add structured field-value lineage. A correction or model assignment does not erase the original fact. Verification is separate from derivation category. | Existing provenance/correction producers; normalized lineage adapter | D01-D03/D05/D09/D10; B1/D1/D2/D4/F5 |
| H10 Non-accrual signals | Existing booleans remain detection flags. Add an evidence-aware status; false detection is not confirmed accrual. Strict current PIK remains a separate related artifact. | Existing non-accrual/PIK evidence modules | D01; B5/D1/E2 |
| H11 Accounting scope | Retain `is_subsidiary`, `axis_profile`, `jv_subsidiary` as distinct signals. Add record class, evidenced relationships and anchor-population membership; none implies a global drop. | Source-scope classification and source-anchor mapping | D08/D11; A2/A5/B3/B4 |
| H12 Entity resolution | `entity_id` identifies the disclosed borrower/company and becomes durable; `canonical_name` is its display alias. Store dated group links separately without merging borrower IDs. | Existing entity resolver plus persistent decision/alias history | D07; C1/C2/D2 |
| H13 Industry enrichment | Preserve `extracted_industry` with method attribution. Add first-class GICS sector assignment; `gics_sub_industry` stays optional. Sector may exist without sub-industry. | Existing GICS pipelines with shared versioned assignment output | D09; D1/D2/D3/E2 |
| H14 Position continuity | `position_key` remains a candidate discriminator; `position_id` becomes durable within filer. Matching emits relationship decisions, then final holdings attaches IDs. Unmatched is not proof of origination or sale. | Existing matcher and position registry, completed before finalization | D05/D06/D07; C3/C4/F2 |
| H15 Observation identity | Preserve `row_id` and `row_id_basis`, with an explicit alias/version contract for correction, collision and fallback cases. Source coordinates and selected source version establish identity; mutable FV alone cannot. | Source identity normalization; finalizer validates uniqueness and references | D05/D10; A3/C4/D1/F2 |
| H16 Shared N-PORT fields | All fourteen existing `nport_*` fields remain supported by the shared pipeline and optional/not applicable to BDCs. No BDC gate requires them populated. | Existing N-PORT staging; unchanged shared schema compatibility | Existing scope; B1/F6 |

### Monetary values, cost and FX

The straight public FV sum requires a common currency. For the proposed versioned BDC target, `fair_value` and analytical `cost` are USD amounts; their currency columns describe those effective values. Preserve each original disclosed amount and currency independently in field evidence. Explicit USD needs no conversion; absent contrary evidence uses labeled `assumed_usd`. Normalize XBRL unit references such as `U_USD` using the actual unit definition, not string heuristics alone. Principal remains separate from valuation currency.

This is an explicit normalization delta from the crosswalk's source-valuation-currency description. It must be measured before migration: the existing audit did not establish whether any published FV/cost is actually non-USD. Already-USD amounts must not be converted because the principal is foreign. Known non-USD or malformed units with missing conversion evidence remain unresolved and visible; neither dropping those rows nor calling their values USD satisfies the contract. The assessed FX reference had a header and no rates. The later [units/FX contract](programme_units_fx_identity_contract.md) defines source/date/fallback conventions; real historical-rate coverage and integration remain implementation requirements, not permission for an unrequested download.

| Target field / relation | Contract |
|---|---|
| `fair_value`, `fair_value_currency` | Normalized USD source valuation, including legitimate zero/negative values. Evidence retains raw amount, unit, source precision and any conversion. Unsupported valuation stays null with an explicit reason and coverage impact. |
| `cost_reported` (add) | USD-normalized disclosed acquisition/carrying cost as defined by its source concept, preserving zero. Source amount and economic kind remain in evidence; missing conversion is distinguished from absent disclosure. |
| `cost`, `cost_source` | Analytical cost: usable reported cost first; otherwise first observed FV for the same established position only when source cost is absent. Do not use a proxy merely because disclosed cost is zero, invalid or awaiting FX. Status distinguishes reported, FV proxy and unresolved. |
| Cost donor relation (add) | Link target row/field to donor row/field, report date, source version, identity decision and method version. Select earliest eligible report date in latest-best history, with declared filing precedence. Conflicting lots/candidates cannot be resolved by arbitrary row order. Preserve a zero FV donor when source-valid; do not retain the current blanket nonzero rule without evidence. |
| `shares_held`, `shares_held_source` | Quantity with supported instrument/unit interpretation. Existing repairs retain original quantity and donor/method evidence. Borrower-level median repair cannot silently combine different instruments; prove eligibility before retaining such behavior. |
| `principal_amount`, `principal_amount_currency` | Original principal/par and resolved original currency. Distinguish drawn principal from commitments, undrawn amounts and generic shares/contracts concepts. |
| `principal_amount_usd`, `principal_fx_rate_to_usd`, `principal_fx_status` | `original principal * USD per original unit`; status separates explicit USD, assumed USD, dated reference FX, missing FX, unresolved unit and not applicable. Identity rate 1 does not prove source currency. |

Latest-best history permits later source corrections and donor discovery, with their actual dates recorded. This does not turn a later observed FV into an earlier reported acquisition cost. Preserve reported-only and proxy-inclusive cost coverage separately. Undefined ratios, including division by zero, stay unavailable.

### Rates, percentages, maturity and evidence-aware statuses

| Target addition or changed field | Contract / eligibility |
|---|---|
| `interest_rate_reported`, `interest_rate_kind` (add) | Source-normalized percentage points plus `cash`, `all_in`, `effective_yield`, `other`, or `unresolved`. Raw literal/unit remain in evidence. |
| `interest_rate_cash` (add); `interest_rate`, `pik_rate` | All-in = supported cash + supported PIK. A disclosed all-in rate is already all-in. A cash rate with unknown PIK does not prove all-in; confirmed zero PIK is different from absent evidence. Effective yield remains outside comparable coupon analytics. |
| `basis_spread_kind` (add) | Cash spread, all-in spread or unresolved; use only like-for-like spreads in a weighted metric. Do not reconstruct an absent coupon from a current/peer benchmark. |
| Existing benchmark/type/pathway fields | Preserve disclosed and inferred benchmark labels with their evidence classes. Inferred labels cannot supply an unreported benchmark value for public income/coupon calculations. Normalize intermediate enums explicitly into the final vocabulary. |
| `pct_of_net_assets`; `pct_of_net_assets_calculated` (add) | Reported NAV percentage and separately calculated `100 * USD FV / comparable USD NAV`. Align fund, date, currency and consolidation basis; identify NAV source. |
| `portfolio_weight_pct` (derived metric) | `100 * holding FV / declared portfolio FV`, with denominator identity. The existing portfolio label remains; the canonical headline/donuts always use the full accepted holdings population. Other analytic eligibility rules must be named and measured. |
| `maturity_precision`, `maturity_status` (add) | Precision `day`, `month`, `year`, `unknown`; status `dated`, `partial`, `perpetual`, `not_disclosed`, `unresolved`, `not_applicable`. Exact or month-end date only where supported. Preserve year/text separately through evidence. |
| `nonaccrual_status` (add) | `nonaccrual`, `accrual_confirmed`, `unknown`, `not_applicable`, tied to observation-period evidence. A missing flag stays unknown unless affirmative applicable evidence exists. |
| `pik_current_status` / terms fields (related artifact retained) | Reuse existing status meanings and evidence; attach through stable row identity and release. Terms, current accrual/payment and stressed amendment claims remain separate. No current evidence from positive terms alone. |
| `gics_sector` (add); optional `gics_sub_industry` | Taxonomy-valid level-specific assignment plus decision reference. A supported sub-industry can deterministically supply its parent sector; a sector does not justify inventing a child. Unknown classifications remain in totals. |

Quantities, rates and percentages keep their declared units; do not use a shared generic monetary field. Optional floor/cap evidence is retained without requiring completeness or promoting an ambiguous floor-tag value into a benchmark-floor formula. Reported UGL remains preserved as text until a separate typed interpretation is justified; derived USD FV minus compatible cost is a separately labeled metric.

### Proposed physical additions to holdings

The first implementation draft adds the following ten fields through the existing physical-schema mechanism. It keeps source facts, donor links and decision metadata in related records. Names/types are design choices; migration must update writers, companion schemas, readers and applicability tests together.

| Added column | Physical type | BDC missingness / constraint |
|---|---|---|
| `cost_reported` | DOUBLE | Nullable when undisclosed or unusable; evidence distinguishes absent disclosure from unresolved conversion. Reported zero is retained. |
| `interest_rate_reported` | DOUBLE | Nullable when unsupported; percentage points with explicit source meaning. |
| `interest_rate_kind` | VARCHAR | The declared reported-rate kind; `unresolved` when unknown. Not a claim about an unavailable coupon. |
| `interest_rate_cash` | DOUBLE | Nullable unless cash component is disclosed or deterministically calculable from sufficient evidence; percentage points. |
| `basis_spread_kind` | VARCHAR | Explicit cash/all-in/unresolved meaning; absent spread has unavailable status in field evidence. |
| `pct_of_net_assets_calculated` | DOUBLE | Nullable without compatible nonzero NAV and supported FV; percentage points. |
| `maturity_precision` | VARCHAR | Day/month/year/unknown; source text and any partial year retained through evidence. |
| `maturity_status` | VARCHAR | One declared status from the maturity contract; status and date must agree. |
| `nonaccrual_status` | VARCHAR | Evidence-aware status; no inferred confirmed-accrual default. |
| `gics_sector` | VARCHAR | Nullable supported sector name in a pinned taxonomy; codes/level/version belong to the linked decision. Unknown remains an explicit exposure bucket. |

`portfolio_weight_pct` remains a derived metric with a denominator reference, rather than another persisted base field. New BDC-specific additions are nullable/not applicable for unaffected shared-source rows until their own source contract supports them. Ten proposed additions do not imply a deployed 98-column artifact; the current saved schema still has 88 fields.

## 3. Related records and joins

These are logical relations with concrete keys and required attributes. Reuse/extend the existing artifacts shown; final storage filenames and dbt model names belong to migration packets. Relations avoid copying an entire evidence graph into each of the 88 fields.

| Relation | Grain / key | Required attributes and join contract | Existing home to extend |
|---|---|---|---|
| Release | One immutable candidate/released snapshot; `release_id` | Parent release, code and local-change identity, schema/decision/metric versions, input/rule/cache hashes, artifact row counts/hashes, stage results, verdict and retained prior snapshot. | Quarter-pass state, reattestations and snapshot manifests |
| Fund-quarter obligation | One `(cohort_version, cik, report_date)` | Eligibility, operating/closed/merged status, source availability, evidence references, selected filing and exception ID. Missing output alone cannot establish ineligibility. | Cohort manifest and filing/universe metadata |
| Filing/source document | One cached document version; `document_id` | CIK, accession, filing date, form, document hash, cached locator, media type, report/context dates and amendment precedence. Several documents may belong to one accession. | Cached filings and provenance indexes |
| Source fact/passage | One fact or passage in a document; `evidence_id` | Document ID, context/fact ID, concept, unit, dimensions, instant/duration, source precision; or HTML table/row/cell/element locator and source text/hash. Context alone is not a field-specific citation. | `src_facts`, source reconciliation, HTML bridge, provenance |
| Holding observation | One retained source-selected position/lot observation; `(release_id, row_id)` | Existing fields plus accepted additions; unique source identity or explained fallback, source selection, entity/position and record-class references. Same source row may have different corrected values in later releases. | Unified holdings, finalized once |
| Field value and evidence edges | One `(release_id, row_id, field)` value decision, plus zero/many input edges | Availability, derivation category, source/input references, rule/model/decision IDs, units, original/effective values, correction history and verification status. Input edges have roles such as reported fact, FX, donor, denominator and inference evidence. | Existing provenance ledgers and correction events; extend rather than replace |
| Entity and entity assignment | Persistent entity ID plus versioned `(release_id, row_id)` assignment | Borrower/company scope, supported aliases, method, evidence, confidence, decision time and merge/split redirects. Unresolved assignment remains explicit. Group relationships are dated edges, not borrower-ID merges. | `entity_resolution.py` and entity lookup/overrides |
| Position and continuity decision | Persistent within-filer position ID; versioned pair/chain decisions | Observation members, predecessor/successor, method/evidence, confirmed/uncertain/unmatched status, effective periods and merge/split/retirement history. Distinct disclosed lots cannot be collapsed silently. | `position_matching.py`, `position_id_registry.py`, matches and review artifacts |
| Classification/enrichment decision | One subject/field/taxonomy assignment per decision version | Subject identity and input hash, target level, value/abstention, method/model/prompt/config/taxonomy versions, evidence, original decision time and review status. Cache serialization time is separate. | Company/industry GICS caches, reviewed classification stores |
| Accounting membership / relationship | One observation-to-anchor membership or parent/underlying edge | Record kind, parent/source-scope identifiers, reference total, included/excluded/unknown with reason and evidence, dates. Ownership is optional evidence, never inferred from the ratio of parent/underlying values. | Subsidiary flags, wrapper dimensions and reconciliation basis helpers |
| Fund metric / aggregate lineage | One `(release_id, metric_id, scope, report_date)` result | Formula version, input row selector or immutable membership list, denominator source, coverage, null policy, result and source/evidence links. Contributor expansion must reproduce the published value. | Fund financials, shared analytics and export functions |
| Acceptance result / exception | One metric/scenario result for a release and population; stable exception ID | Measurement envelope defined in the register, residual rows/FV, evidence, permitted disposition, owner decision where required. | Quarter acceptance, validation ledgers, promotion/application audits |

Source-linked `row_id` values are reused where their guarantees hold. Colliding source contexts need stable source-lot discriminators and explicit aliases when a previous fallback changes. Do not use CSV row ordinal, mutable amount or global sorting as the sole durable key. The existing position registry is an implementation starting point, not certification of collision, split or lifecycle correctness; test these before enabling it on the production path.

Each candidate must carry compatible entity, position, PIK and evidence snapshots. Legacy run-local keys may remain internal during migration, but released joins use durable keys or explicit alias mappings. Unknown continuity may produce an unresolved singleton identity; it is not a confirmed new investment. Grouping by `entity_id` is an analytic aggregation, not the holdings grain.

Registry state is an explicit pinned build input and candidate output. Trial allocations and retirements use isolated state; finalization records which state belongs to the candidate. Retry/rollback tests must cover registry changes as well as CSVs so that a failed candidate cannot silently change a later build's identities.

## 4. Evidence and citation contract

Use separate attributes so that a field can be calculated from a source fact, corrected, and independently verified without squeezing those facts into one label:

- `availability`: present, not disclosed, not applicable, unresolved, missing source, or failed extraction.
- `derivation`: reported, normalized, calculated, inferred, or approved default. An FV cost proxy is calculated with `method=first_observed_fv_proxy` and explicit proxy status.
- `correction`: zero/many versioned correction events, each with mechanism and before/after evidence.
- `verification`: not checked, source matched, independently reviewed, disputed, or not assessable, with verifier/version and precise scope. Do not migrate existing ledger vocabulary without an explicit mapping.

Mixed calculations retain each input's categories; a formula using assumed USD or inferred GICS does not become wholly source reported. `reported` means the cited concept/text actually discloses that financial meaning. Extracting a business description and mapping it to GICS yields an inference or mapping decision, not a reported GICS code.

The evidence resolver accepts `(release_id, metric_id)` or `(release_id, row_id, field)`. It returns the displayed value, unit, basis, derivation, contributing inputs and exact document/passages, or an explicit unavailable reason. Aggregate contributors are paginated and retain their total/count; a generic filer URL is not a successful citation. Highlight locators are validated against the document hash, including repeated identical numbers in different rows and footnotes.

HTML/inline-XBRL highlights are core. Evaluate Arelle/iXBRL Viewer through the existing decision-sheet integration task, using cached documents and an explicit inventory of taxonomy/viewer resources; no automatic network preparation. Calculations show inputs/formula; inferences show evidence and method. PDF status is delivered or deferred and does not block a valid HTML citation. A viewer cannot supply the missing lineage by itself.

## 5. Transformation ownership and migration boundaries

| Stage | Target responsibility | Migration treatment |
|---|---|---|
| Cached extraction | Read source facts/documents, preserve contexts/units/dimensions and anchors | Retain Python extractors/wrappers and HTML recovery; no new historical HTML campaign. |
| Selection and normalization | Filing precedence, source-lot roster, compatible types/units, rate interpretation, scope classification | Move substantial deterministic relational transforms into dbt/DuckDB in bounded models; preserve source keys and stored failure rows. |
| Corrections and enrichment | Apply pinned promoted decisions to eligible observations with application audit | Preserve existing proposal/verify/promote roles. Deterministic Python functions may remain as typed stages; no parallel SQL implementation of the same rule without retiring one. |
| Identity | Resolve borrower assignments and within-filer position continuity | Retain Python resolver/matcher and registries; consume pinned normalized/corrected inputs and emit decisions rather than rewriting canonical CSV. |
| Cost/analytic derivations | Apply identity-safe donor selection, aligned NAV ratios and supported rate components | Explicit dbt/DuckDB dependencies on required identity, FX, fund and evidence snapshots. No dependency on a prior run's unrecorded output. |
| Finalization | Assemble all approved fields, keys and provenance; enforce structural/semantic contracts | `pipeline.unified_holdings` remains the coordinating module; one final writer for holdings and companions. Exact CLI orchestration changes are specified in packets. |
| Independent evaluation | Source roster/amount checks, identity/enrichment benchmarks, quarter gates | Python validation and dbt tests retain separate reference evidence. Evaluators must not certify their own corrected roster as ground truth. |
| Serving | Derive full holdings/history and public analytics from one accepted candidate | Export from final holdings after evaluation; stage a complete bundle and bind all payloads to one release. Preserve public v1 scope. |

Break current feedback loops explicitly: independent fund financials needed by NAV or strategy normalization must be ready before those transforms; identity-driven cost donors must be selected after identity, not used to circularly justify that identity. Existing matching inputs and legacy return consumers require dependency tracing before moving either boundary. Preserve all-in storage and income changes as one semantic migration.

No production dbt project is claimed here. Reuse the bounded [dbt spike](dbt_spike_report.md) as integration evidence, not full-pipeline proof. Preserve shared non-BDC behavior, CLI compatibility and existing safeguards. Rebuild/export/baseline/dispatch operations are implementation work, not side effects of writing this spec.

## 6. Concrete specification dependencies

These IDs are retained for traceability. Later preparation supplied their conventions and bounded examples; the remaining entries below are implementation/reference obligations. They do not reopen D01-D13 or keep specification preparation open until the current data passes.

| ID | Current design and preparation status | Remaining implementation evidence |
|---|---|---|
| SPEC-FX | [Units/FX contract](programme_units_fx_identity_contract.md) specifies field-level denomination, ECB reference quotes, latest on/before date within seven days, and unavailable/stale handling. Source-conflict cases and synthetic-rate tests exist. | Complete field-specific source adjudication and real historical-rate integration; pin provider observations and measure USD effects. Token counts are not confirmed currency requirements. No purchases/downloads implied. |
| SPEC-ID | The later units/identity contract specifies immutable creation decisions, governed scope and explicit merge/split history. Bounded allocation, donor and source-mapping examples exist. | Migrate the full population; verify rebuild/addition/lot/amendment behavior and independent link/chain quality. Existing unique IDs alone do not establish correctness or durability. |
| SPEC-RULES | [Authority assessment](programme_rule_authority_assessment_2026-09-09.md) records 77 families, 740 assets, 14 control inputs and ten bounded runtime replays. The closeout adds full B2 application accounting and a B2 order experiment for its frozen inputs. | Complete rule-instance/unit/selector records and global/wrapper/cache/Layer-C interactions; implement admission, ordering, audit and final-writer corrections. B2-only measured effects do not certify every rule family. Master WP-02 remains outstanding. |
| SPEC-REF | The closeout has all 61 source dispositions, four complete development rosters, 20 proposed label corrections and 910 obligation statuses (812 eligible, 98 pre-investment). | Implement automated reference admission; complete independent rosters/decisions, accounting/currency keys, sampling/exposure controls and adjudication. No mandatory human-labelled gold set. Development evidence remains distinct from acceptance evidence. |
| SPEC-VIEW | HTML/iXBRL first, PDF deferrable under D10. The prototype exercises six real highlights across four filings, with 36 measured navigations and explicit calculated/inferred/unavailable paths. | Complete all required displays, source locators, deployment coverage and performance tests. Prototype success is not public-product implementation. |
| SPEC-GATE | Numerical recommendations are accepted as amendable working targets under the 10 September review. The measurement register and working-v1 contract supply current definitions/targets. | Complete independent measurements, evidence-backed calibration and final release evaluation. Preserve unavailable metrics and prior versions; no live gate change or current-data acceptance is implied. |

This supplies the target mapping of the 88 existing fields and required relationship/schema deltas. It does not certify every active rule or establish measured implementation readiness. Complete the outstanding obligations within the implementation packages before claiming final acceptance.

The following paragraphs preserve the chronology of the earlier dated assessments. Their older counts and next-step language do not override the current status above or the subsequent closeout.

The subsequent [conflict resolution](programme_conflict_resolution.md) specifies
each F01-F12 disposition, incompatible legacy test expectations, writer precedence
and CR-01 through CR-07 packet boundaries. Its
[assessment](programme_contract_assessment_2026-09-09.md) adds saved-artifact
measurements and the 910-slot obligation frame; eligibility and independent
accuracy still require adjudication. These additions do not change D01-D13.

The subsequent [reference assessment](programme_reference_and_eligibility.md)
classifies 811 eligible, 98 pre-investment and one unresolved fund-quarter, while
preserving all original gaps. It also supplies raw-source unit/period cases,
including a printed-EUR/tagged-USD principal conflict, and inventories existing
entity as well as position gold. These are preparation results; independent
labeling, executable checks and final numerical calibration remain outstanding.

The subsequent [measurement pilot](programme_measurement_pilot_2026-09-09.md)
resolves Fortress to eligible (812/98/0), executes isolated comparisons and adds
a numerical gate proposal. Its Aurelia and Sentinel reference conflicts reinforce
the existing requirement to bind labels to currency, instrument and accounting
scope. No financial meaning, field ownership or D01-D13 decision was changed.
