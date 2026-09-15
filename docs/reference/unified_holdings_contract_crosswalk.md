# Unified holdings contract crosswalk

Date: 2026-09-08; programme extension added 2026-09-09. Status: sections 1-18 are the descriptive audit; section 19 maps the accepted programme decisions to a target implementation design. No production schema or migration has been applied.

## Read this first

The repository already has a substantial schema, financial conventions, per-CIK wrapper schemas, rate grammars, provenance contracts, validators and static benchmarks. The task is to reconcile these definitions with implementation and consumers, not design them again from scratch.

The owner has now resolved all thirteen [programme decisions](../production_stack/01_decisions.md). Earlier audit questions and recommendations below are retained as dated findings, not open policy choices. Use [section 19](#19-programme-target-extension) and the linked target contract for the current design disposition.

This document maps **all 88 columns in the saved `private_markets_holdings.csv` header**, plus important related BDC artifacts. Interpretation is limited to **unlisted BDCs in the authoritative wrapper cohort**. N-PORT-only columns are explicitly accounted for, not proposed for removal from the shared pipeline.

Evidence basis: source-code and documentation inspection of the working tree at HEAD `2e0491a45d1493e7a3ee329aee52ec96bb34986c`, plus the saved CSV header. The worktree was dirty, including `pipeline/config.py` and frontend files; this is not a clean-commit reproducibility claim. The initial crosswalk did not profile field values. The subsequent [availability audit](#18-availability-audit-and-preferred-representations) adds bounded profiling and three cached XML checks. No filing downloads, dataset rebuilds, tests, agent dispatches or production-output writes were performed. References to tests mean existing test coverage was located/inspected, **not that tests were run or that all cases are covered**.

### Main conclusions

1. **Keep the existing schema machinery.** Physical types, field-quality rules, source evidence and per-CIK extraction definitions already exist.
2. **Resolve semantic mismatches before renaming or splitting fields.** Highest-impact examples are interest-rate meaning, cost proxies and the use of these fields in analytics.
3. **Do not equate a check with an enforced release gate.** Different layers deliberately have different powers, and some currently disagree on allowed values.
4. **The historical holdings output is not automatically an as-known-at-the-time ML dataset.** Amendments, full-history proxies, classification stabilization and current enrichment caches can introduce later information.
5. **Unknown and not disclosed are legitimate outcomes.** Optional loan terms must not become mandatory agent-completion targets.

## 1. How to read the crosswalk

Each row records an existing intended meaning, observed implementation, relevant checks, consumer and residual issue. Status labels are not accuracy scores:

- **Defined:** meaning and implementation are identifiable; no specific contradiction established in this inspection. Not a source-correctness certification.
- **Mixed:** one stored field carries more than one economic meaning or derivation pathway.
- **Gap:** a specific contract, identity, temporal or enforcement limitation was located.
- **BDC-empty:** BDC staging deliberately emits an empty field; optional enrichment is not being ruled out.
- **Out of scope:** N-PORT-only field, not applicable to the requested BDC analysis.

Types below are the persisted Parquet contract: `text` = VARCHAR, `number` = DOUBLE, `date` = DATE, `integer` = BIGINT, `boolean` = BOOLEAN. CSV itself has no enforced native type. Blank text, numeric NULL and false do not have a universal shared missingness meaning.

### Evidence map

These keys identify the precise code/doc families used in the tables. Function names are given because line numbers move.

| Key | Existing authority or implementation | Role and enforcement boundary |
|---|---|---|
| A | [AGENTS.md](../../AGENTS.md) | Owner's product scope and semantic decisions; newer changelog entries must also be consulted. No indices in public v1. |
| D | [schemas.md](schemas.md) | BDC extraction fields, row identity, PIK semantics, provenance event/ledger definitions; contains historical sections and stale statements. |
| U | [unified_holdings.py](../../pipeline/unified_holdings.py), `UNIFIED_COLUMNS`, `build_unified_holdings`, `_enforce_schema` | Assembly, corrections, enrichment and final row IDs. `_enforce_schema` returns/logs violations; it does not stop the write. |
| T | [output_schemas.py](../../pipeline/output_schemas.py), [utils.py](../../pipeline/utils.py), `write_parquet_companion` | Ordered output columns and physical types; strict production companion writing raises on schema/cast failures. CSV is written first, so this is not an atomic release transaction. |
| E | [bdc_filings.py](../../pipeline/bdc_filings.py), `CONCEPT_MAP`, `_match_concept`, extraction/dedup | Source concepts, context-level values, source units, non-accrual detection and raw-fact provenance. |
| S | [staging_bdc.py](../../pipeline/staging_bdc.py), `_prepare_bdc`, `unified` CTE | Period/amendment selection, per-CIK parsing, type/rate/currency transformations and initial unified mapping. |
| H | [bdc_xbrl_html_bridge.py](../../pipeline/bdc_xbrl_html_bridge.py), `apply_html_section_bridge_field_overlays`, `apply_ixbrl_field_status_overlay` | Source-backed blank-field enrichment called by S; maturity/reference provenance can be `html_section_bridge` or `ixbrl_field_status`. |
| W | [wrapper_v3.schema.json](../../schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json), [bdc_xbrl_wrapper.py](../../pipeline/bdc_xbrl_wrapper.py), [wrapper_content_signatures.py](../../pipeline/wrapper_content_signatures.py) | Formal per-CIK extraction/dispatch/staging/archetype contracts. Content signatures are diagnostic; a schema file alone does not prove every production route runs its validator. |
| V | [column_validation.py](../../pipeline/column_validation.py), `COLUMN_CONTRACTS`, `validate_column_contracts`; [validate_holdings.py](../../pipeline/validate_holdings.py) | Required/source-aware coverage, enums, numeric/cross-field checks and reconciliation adapters. Emits issues; action labels do not themselves delete holdings or block export. |
| P | [provenance_reverify.py](../../pipeline/provenance_reverify.py), `CHEAP_FIELDS`, `cheap_tier`, `full_tier` | Eight financial fields: declared-raw replay and cached-instance recheck. Verification status lives in separate ledgers, not a blanket verified bit on a holding. |
| R | [identifier_rate.py](../../pipeline/identifier_rate.py), `apply_grammar`, `evaluate_invariants`; [identifier_spread_corrections.py](../../pipeline/identifier_spread_corrections.py) | Per-CIK identifier grammar, units and cash/PIK derivations; reviewed overlay/correction paths, not automatic publication of every parsed term. |
| C | [rate_convention.py](../../pipeline/rate_convention.py), [convention_validation.py](../../pipeline/convention_validation.py), [B1 contract](../adjudication_architecture/B1_adjudication_contract.md) | Evidence about cash-leg versus all-in conventions, separate from an all-in storage migration. B1 explicitly states the all-in target. |
| K | [pik_status.py](../../pipeline/pik_status.py), [bdc_position_pik.py](../../pipeline/bdc_position_pik.py) | Strict current PIK evidence, schedule-terms proxy and separate transition artifacts. |
| M | [position_matching.py](../../pipeline/position_matching.py), `assign_position_ids`; [position_id_registry.py](../../pipeline/position_id_registry.py) | Cross-quarter chain assignment and optional registry; production default `use_registry=False`. |
| CL | [classification.py](../../pipeline/classification.py), [lien_classification.py](../../pipeline/lien_classification.py), [instrument_classification.py](../../pipeline/instrument_classification.py) | Shared classifications; U also applies cached/agent/fund-level overrides and historical stabilization. |
| XF | [export/fund_exports.py](../../pipeline/export/fund_exports.py) | Fund holdings, weighted coupon/spread/maturity, cost-based measures and credit stress. |
| XA | [export/analytics_exports.py](../../pipeline/export/analytics_exports.py) | Concentration, spread, PIK-terms, credit-risk and quality exports. |
| XI | [export/index_exports.py](../../pipeline/export/index_exports.py), [index_returns.py](../../pipeline/index_returns.py) | Portfolio characteristics and legacy/research return consumers. Their continued existence is not approval to expose indices in public v1. |
| XH | [export/helpers.py](../../pipeline/export/helpers.py), `_load_unlisted_bdc_ciks`; [frontend types](../../frontend/src/lib/types.ts) | Cohort loading and downstream JSON shapes. A frontend type is not the financial definition of its input. |
| Q | [quarter_acceptance.py](../../pipeline/quarter_acceptance.py), [thresholds](../../data/reference/quarter_acceptance_thresholds.json), [published_basis.py](../../pipeline/published_basis.py) | Explicit quarter-level acceptance, currently provisional v3 published basis. This is distinct from type checks, column flags and historical v2 sign-offs. |

Related tests: [unified](../../tests/test_unified_holdings.py), [physical schemas](../../tests/test_output_schemas.py), [column validation](../../tests/test_column_validation.py), [holdings validation](../../tests/test_validate_holdings.py), [provenance replay](../../tests/test_provenance_reverify.py), [row identity](../../tests/test_row_id.py), [wrappers](../../tests/test_bdc_xbrl_wrapper.py), [signatures](../../tests/test_wrapper_content_signatures.py), [rate grammar](../../tests/test_identifier_rate.py), [spread corrections](../../tests/test_identifier_spread_corrections.py), [PIK](../../tests/test_pik_status.py), [matching](../../tests/test_position_matching.py), [registry](../../tests/test_position_id_registry.py), [analytics exports](../../tests/test_analytics_exports.py), [lien](../../tests/test_lien_classification.py), [instrument type](../../tests/test_instrument_classification.py), [quarter acceptance](../../tests/test_quarter_acceptance.py). These are related coverage, not a claim of one independent gold test per column.

## 2. Observation and fund identity

Existing grain is a retained, normalized holding observation selected from filings, not a borrower total and not an immutable record of every as-filed version. Multiple instruments for one borrower must remain distinct. S removes non-current context periods and selects latest-filed amendments by fund/report date/base form; source caches retain information that the unified view does not.

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `source` | text; source family | S emits `bdc`. | U enum accepts bdc/nport; V C001 also accepts html; physical-schema and column tests. | Reconciliation and source-specific analytics. **Gap F05:** validators disagree; BDC HTML provenance is not fully described by this flag alone. |
| `cik` | text; SEC fund identity | S pads to 10 characters; other correction paths normalize separately. | U exact length/digits; V C002 weaker digit-normalizability; newer holdings CIK check; wrapper tests. | Fund joins and cohort filter. **Defined**, but not sufficient to establish unlisted/public scope: use cohort manifest. |
| `entity_name` | text; reporting fund name | E/S passthrough; not investee identity. | V C008 and required coverage. | Fund display/grouping. **Defined:** CIK, not name, is the primary fund key. |
| `accession_number` | text; source filing accession | E/S passthrough; S amendment selection can replace older observations. | V C006 presence for BDC; row-ID/provenance tests. | Source lookup, corrections, row anchors. **Gap F06:** latest-view selection is not a filing-vintage history. |
| `filing_date` | date; date of source filing | E/S passthrough; orders amendment preference. | V C007 parseability when present; T date cast. | Availability proxy and amendment selection. **Gap F06:** date is not a full information-availability timestamp or revision history. |
| `report_date` | date; observation/report period | E/S passthrough; S filters context `period` against it and excludes pre-2022 reports. | V C004/C005, U parseability, T date; unified tests. | Quarter grouping, term remaining, reconciliation. **Defined:** distinct from filing date; context `period` is not a saved unified column. |

## 3. Holding names and external identifiers

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `issuer_name` | text; investee/issuer name | S global parsing plus per-CIK wrapper/bridge/name normalization. | V C201-C203/C206; W signatures; unified/wrapper tests. | Entity matching, concentration, display, dedup. **Defined with inference:** clean-looking name does not prove correct borrower/tranche separation. |
| `instrument_description` | text; instrument/tranche description | S identifier parsing and bridge rules. | W signatures; unified, matching and classification tests; no complete source-truth coverage established here. | Tranche identity, instrument/lien classification. **Defined with coverage gap:** blank can mean undisclosed or not extracted. |
| `cusip` | text; security identifier | S emits empty for BDCs. | V C204 length if present. | Matching and cost-proxy partitioning. **BDC-empty:** not an available BDC matching key on this path. |
| `isin` | text; security identifier | S emits empty for BDCs. | V C205 length if present. | Potential external matching. **BDC-empty.** |
| `lei` | text; legal entity identifier | S emits empty for BDCs. | T text; no BDC-specific source-truth check located. | Potential entity enrichment. **BDC-empty.** |
| `ticker` | text; ticker symbol | S emits empty for BDCs. | T text; no BDC-specific source-truth check located. | Potential display/enrichment. **BDC-empty:** not the reporting BDC's own ticker. |

## 4. Values, units and currency

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `fair_value` | number; position fair value in reported valuation currency | E concept parsing/scaling; S scale/dedup/selection; U approved corrections. | V C101-C105; source and fund reconciliation; P; Q; unified/provenance tests. | Public FV sum and weights. **Defined:** source-correct totals do not certify every row or field; zero/negative values can be legitimate. See F10 for population basis. |
| `cost` | number; source cost basis, but may be proxy | E/S cost; U `with_cost` replaces NULL **and zero** with first nonzero FV in the full position-history partition; stamps `derived_proxy`. | V C106/C107, X07/X08; P distinguishes proxy; explicit unified proxy tests. | FV/cost, underwater and stress measures, return fallback. **Mixed F02/F06:** reported cost and FV proxy share a column; historical window may use later observations. |
| `pct_of_net_assets` | number; percent of NAV, percentage points | S scale heuristic; U `_correct_pct_of_net_assets` may replace values with FV/consolidated NAV x100 in high-sum fund-quarters. | V X09/C404; pct-sum checks; P pct sense check; unified/provenance tests. | Display and leverage-like diagnostics. **Mixed F04:** reported denominator and reconstructed consolidated denominator share a field; not portfolio weight. |
| `shares_held` | number; share/contract quantity | E/S quantity; U `with_shares_fix` may replace outliers using historical neighboring values and full-history median price. | V C118/C119; U sign check; P; unified proxy tests. | Per-unit equity analytics/returns. **Mixed F06:** source quantity versus repaired proxy; donor grouping is fund + issuer, not always a unique instrument. |
| `principal_amount` | number; original-unit principal/par | E principal/combined balance concepts; S `_pa`, scale corrections; U overrides. | V C109/C110, X06 via USD principal; P; unified tests. | Debt quantity, matching and source reconciliation. **Defined with ambiguity:** combined shares/contracts/principal concepts require correct context; not automatically commitment or undrawn amount. |
| `fair_value_currency` | text; valuation unit/currency label | S strips namespace prefix and uppercases source unit token. | V FX02 recognizes USD-like unit tokens. | Interpreting monetary value. **Gap F03:** label is not guaranteed ISO currency; no general FV conversion is performed by this mapping. |
| `cost_currency` | text; source cost unit/currency | Same unit-token normalization as FV. Proxy cost does not separately replace its currency label in `with_cost`. | V FX03; T text. | Comparing cost/FV. **Gap F02/F03:** proxy value and retained cost-currency label need consistent interpretation. |
| `principal_amount_currency` | text; original principal unit | S strips namespace/uppercases token. | FX01 and principal checks. | FX conversion and original-currency analytics. **Gap F03:** blank is treated as USD; token handling differs from USD recognition in validators. |
| `principal_amount_usd` | number; USD-equivalent principal | S: blank/USD unit -> original amount; otherwise join reference FX on currency + report date; unavailable FX -> NULL. | V FX01/X06, U sign check; unified tests. | FV/par credit stress and per-unit debt returns. **Defined with assumption F03:** use conversion status, not numeric presence alone, as evidence. |
| `principal_fx_rate_to_usd` | number; USD per original currency unit | S: 1 for blank/USD principal unit; otherwise reference FX. | Physical numeric type; related FX tests. | Reconstruct USD principal. **Gap F03:** rate 1 can encode an assumption about a missing currency, not observed USD evidence. |
| `principal_fx_status` | text; conversion pathway | S emits blank, `source_usd`, `reference_fx`, `missing_reference_fx`. | Related FX diagnostics, not a full BDC enum in V. | Conversion eligibility/audit. **Gap F03:** `source_usd` combines explicit USD and missing-unit default. |

## 5. Classifications

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `asset_category` | text; broad instrument category | S maps source dimensions/text to LOAN, DEBT, EQUITY_COMMON, EQUITY_PREFERRED, FUND, OTHER. | U enum and relational checks; W; unified tests. | Shared classification and debt/equity eligibility. **Defined with inference:** classification, not a verbatim disclosed label. |
| `issuer_category` | text; corporate/fund/government/other | S source/text inference. | U enum and relational checks; classification validation. | Fund-versus-direct exposure logic. **Defined with inference.** |
| `index_classification` | text; legacy named analytical bucket | U/CL rules, historical stabilization, strategy/manual/agent/cache overrides. | U enum; V C301; classification cross-checks; unified tests. | Still used for v1 instrument buckets and DL eligibility. **Gap F06:** historical/current interpretations mix; field name does not authorize a public index. |
| `exposure_type` | text; DIRECT/FUND/LIQUID | U/CL, stabilization and later overrides. | U enum; V C303; classification tests. | Direct versus fund exposure. **Defined with inference; F06:** not a source-reported accounting consolidation flag. |
| `asset_class` | text; PRIVATE_CREDIT, PRIVATE_EQUITY, REAL_ESTATE, STRUCTURED_CREDIT, HEDGE_FUND, CASH, OTHER | U/CL, stabilization, strategy and correction layers. | U enum; V C304; cross-field validation. | Mix, eligibility, classifications. **Defined with inference; F06:** preserve source/derived distinction and vintage. |
| `fair_value_level` | text; accounting valuation hierarchy level | S emits empty for BDCs. | T text; source-specific checks elsewhere. | XF hierarchy breakdown supports populated sources. **BDC-empty:** cannot infer BDC position-level Level 3 or valuation method from this field. |

## 6. Rates and maturity

Rates in unified holdings are intended to be **percentage points**: 5.0 spread means 500 bps, 9.5 coupon means 9.5%. This is not a universal raw-XBRL unit convention. No code path shown here establishes that SOFR+500 is exactly 9.5% without the applicable benchmark/fixing and relevant term evidence.

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `interest_rate` | number; owner/B1 target is all-in stated coupon | E maps bare and PaidInCash concepts into the same field; S tag-first/text fallback and magnitude normalization; no uniform all-in migration. | V C112/C113/X01/X02; P; C; rate/unified tests. | XF/XI weighted coupon; return income. **Mixed F01:** cash, all-in and some effective-yield observations are not one comparable coupon measure. |
| `interest_rate_source` | text; extraction pathway | S `xbrl_field`, `identifier_text`, or blank; correction metadata recorded separately. | P uses pathway to select replay/verification treatment. | Evidence eligibility and diagnosis. **Defined:** does not encode cash/all-in convention or prove a later corrected value. |
| `basis_spread` | number; spread over reference rate, percentage points | S structured-first/text fallback and magnitude heuristic; reviewed Agent A keyed spread overrides may replace tagged value. | V C114/C115/X04/X05; P; R and correction tests. | XF/XA weighted spreads; matching. **Mixed F01:** cash versus inclusive spread convention must be respected; some XA charts restrict to >0 and <=15. |
| `basis_spread_source` | text; original extraction pathway | S `xbrl_field`/`identifier_text`/blank; corrections tracked separately. | P and Agent A correction tests. | Provenance. **Defined with caveat:** read with `corrected_fields`, not alone. |
| `reference_rate_type` | text; reference benchmark label | S tag -> text -> SOFR/LIBOR inference from nonzero tagged spread and report date, with foreign-text exclusions. | R agreement/semantic checks; no universal source-truth guarantee in V. | Floating-rate interpretation. **Mixed F01:** observed and inferred labels coexist; label does not supply tenor, reset date or fixing. |
| `reference_rate_source` | text; benchmark provenance | S `xbrl_field`, `identifier_text`, `inferred_post_libor`, `inferred_pre_libor`, blank; H adds `html_section_bridge` / `ixbrl_field_status`. | Parser/provenance-path tests; not one of P's eight replayed numeric fields. | Distinguish disclosed from inferred benchmark. **Defined:** useful existing contract to retain. |
| `coupon_type` | text; fixed/floating classification | S explicit/parser result, then text/spread inference. | U allows Fixed/Floating/blank; V C306 also allows Variable; R intermediate uses uppercase. | XF floating/fixed shares; X04/X05. **Gap F05:** different layer vocabularies need explicit translation/authority, not automatic global replacement. |
| `pik_rate` | number; disclosed contractual PIK-rate component | S tag/text fallback, magnitude normalization, additional boundary repair when >=20 and >interest rate; U corrections possible. | V C116/C117; P; R; PIK terms/current separation tests. | Schedule-terms exposure; convention-aware return income. **Defined with caveats F01/F08:** positive terms do not prove current PIK or distress; null is not confirmed zero. |
| `maturity_date` | date; contractual maturity where known | S tag first; text date fallback; month/year becomes month-end; invalid or year >=2099 becomes blank. | V C401-C403/X10; T date; grammar/matching tests. | XF maturity buckets/WAM; M maturity veto. **Gap F07:** inferred day precision and perpetual/unknown conflation; V still documents 9999 sentinel. |
| `maturity_date_source` | text; maturity extraction pathway | S tag/text/blank; H adds `html_section_bridge` / `ixbrl_field_status`; no saved precision field. Text source can be stamped when text exists even if final parse is invalid. | Related parser tests; not part of P numeric replay. | Evidence diagnosis. **Gap F07:** source marker is not validity, precision or perpetual status. |

## 7. BDC-specific source descriptors

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `bdc_investment_identifier` | text; BDC position identifier text | S publishes `_raw_id`, which has undergone stripping/normalization in earlier CTEs. | V C207 presence; W grammar; source matching tests. | Corrections, parsers, matching, audit. **Gap F09:** the name/documentation suggests raw source, but this is not guaranteed verbatim source text. |
| `bdc_form_type` | text; source form, e.g. 10-K/10-Q | S passthrough after base-form/amendment selection. | E/S and wrapper tests; T text. | Filing lineage. **Defined:** 10-K does not by itself make a position value a full-year flow. |
| `bdc_dimensions_raw` | text; serialized source dimension path | E/S passthrough. | Source reconciliation, W routing, P context checks. | Position scope, PIK evidence joins, subsidiary classification. **Defined:** dimensions can contain presentation duplicates; not an economic instrument ID. |
| `bdc_unrealized_gain_loss` | text; extracted unrealized appreciation/depreciation | S `_ugl`; T deliberately VARCHAR. | No entry in P `CHEAP_FIELDS`; no dedicated numeric V rule located. | Available for research/audit; XF also derives FV minus cost independently. **Gap F11:** do not assume numeric or interchangeable with derived FV-cost. |
| `bdc_investment_country` | text; investment geography parsed from hierarchy | S `_hier_country` or blank. | Wrapper/parsing tests; no full country dictionary/coverage contract located in inspected validators. | Potential geography analytics. **Gap:** country meaning (domicile/operations/etc.) is not established uniformly here. |

## 8. Provenance and corrections

These are existing contracts, not proposed new features. Source-pathway markers, correction markers and verification results answer different questions. See D and P for field-specific status vocabularies.

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `src_context_id` | text; primary winning XBRL context | E dedup winner -> S passthrough. | P full-tier recheck; row-ID and extraction tests. | Source anchor. **Defined:** donor-filled fields can come from another context; primary is not necessarily source of every field. |
| `src_context_count` | integer; deduplicated context count | S carries `dedupe_context_count` as text in memory; T integer cast. | Typed schema and dedup tests. | Dedup diagnostic. **Defined:** count does not establish dedup correctness. |
| `src_conflict_fields` | text; fields whose dedup candidates disagreed | E `dedupe_conflict_fields` -> S. | Dedup/provenance tests. | Target review. **Defined:** empty means no recorded conflict, not independently verified agreement. |
| `src_transforms` | text; ordered field:event transformations | S rate/sign normalization; U cost/share proxy events; E events also live in `src_facts.x`. | P replays known events; boundary/proxy tests. | Explain normalized value. **Defined:** not a complete standalone lineage graph for all later enrichment. |
| `src_field_overrides` | text; bridge source coordinate references | HTML-section bridge stamps field, source hash and table/row coordinates. | Bridge/provenance tests. | Locate alternative source evidence. **Defined:** not a generic list of all manual/agent corrections. |
| `cost_source` | text; special cost pathway | Empty for ordinary source pathway; `derived_proxy` for U FV proxy. | P special handling; explicit unified proxy tests. | Should control reported-cost eligibility. **Gap F02:** inspected XF/XA cost analytics do not filter this marker. |
| `shares_held_source` | text; special share pathway | Empty normally; `derived_proxy` for U repair. | P and unified tests. | Quantity provenance. **Defined with consumer risk F06:** no standalone donor date/source ID in this field. |
| `fair_value_source` | text; original FV pathway | S emits `xbrl_field` for nonnull `_fv`; other layers can correct value. | P and corrected-field guardrails. | Evidence eligibility. **Defined:** source marker alone is not a release-quality status. |
| `principal_amount_source` | text; original principal pathway | S `xbrl_field` when `_pa` exists, otherwise blank. | P and numeric checks. | Principal evidence. **Defined:** does not certify original concept was economically principal rather than a combined balance quantity. |
| `pct_of_net_assets_source` | text; original percentage pathway | S `xbrl_field` when `_pct` exists; later recalculation stamps `corrected_fields`. | P pct sense check. | Provenance. **Mixed F04:** inspect correction marker to distinguish original percentage from recomputation. |
| `pik_rate_source` | text; PIK-rate extraction pathway | S `xbrl_field`/`identifier_text`/blank. | P and PIK tests. | Terms evidence. **Defined:** not current-payment evidence. |
| `bdc_unrealized_gain_loss_source` | text; original UGL pathway | S emits `xbrl_field` if `_ugl` is nonnull. | T text; outside P eight-field replay. | Audit. **Gap F11:** D says reserved/always blank, but writer now populates it. No current nonblank count measured. |
| `src_facts` | text containing JSON; per-field declared raw value/concept/events | E writes field objects with `r`, optional `c`, optional `x`; S carries through. | P cheap/full tiers and tests; T only enforces text, not JSON economics. | Reconstruct/check eight financial fields. **Defined with coverage limit:** absent JSON is not source confirmation. |
| `src_filled_fields` | text; fields filled from secondary dedup context | E donor-fill audit -> S passthrough. | P re-verification treatment; extraction/provenance tests. | Detect primary-context insufficiency. **Defined:** does not itself carry each donor context ID. |
| `corrected_fields` | text; post-extraction changed fields, including `_row:added` | U manual/B2/promoted corrections; S scale/Agent A changes; other named correction writers. | P special handling; correction guardrail tests. | Avoid treating overrides as untouched source. **Defined:** flag identifies affected fields, not complete justification or authority; join correction artifacts. |

## 9. Non-accrual and ownership/presentation flags

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `nonaccrual_footnote` | boolean; position-level footnote signal | E footnote/context detector; S missing/unparseable -> false. | Non-accrual evidence/validation and related tests. | XA/XF non-accrual and stress measures. **Gap F08:** false means no retained positive detection, not independently confirmed accrual status. |
| `nonaccrual_dimension` | boolean; XBRL non-accrual dimension signal | E dimension detector; S missing/unparseable -> false. | Dimension/evidence tests. | OR-ed with footnote flag in XA/XF. **Gap F08:** detection coverage is not encoded in this boolean. |
| `is_subsidiary` | integer; subsidiary/JV look-through presentation flag | S checks two specific dimension patterns, retains rows; not general borrower-name matching. | Subsidiary and reconciliation tests; Q published-basis logic. | Reconciliation presentation treatment. **Gap F10:** distinguish legacy subsidiary-adjusted checks from v3 published sums; not a global delete instruction. |
| `axis_profile` | text; normalized source presentation profile | S strips attached member values, normalizes/sorts segments. | Provenance and correction guardrails. | Compare presentation layers, not economic exposure. **Defined:** derived source identity; must not be arbitrarily corrected. |
| `jv_subsidiary` | text; agent-reviewed JV label | U `_apply_unclassified_cache` stamps `Y` by reviewed normalized name; blank otherwise. | Cache/classification tests; not equivalent to source-axis test. | Reviewed classification/audit. **Mixed F10:** this is not synonymous with `is_subsidiary`; do not substitute in sums. |

## 10. Enriched identity, classifications and continuity

| Field | Type / existing meaning | Actual transformation / writer | Validation and tests | Consumer / status and unresolved discrepancy |
|---|---|---|---|---|
| `entity_id` | text; resolved investee entity | U joins cached entity lookup by issuer-name variant + source. | Entity/match diagnostics and gold cases; not P numeric verification. | Borrower concentration/cross-fund lookup. **Defined with inference F06:** borrower identity, not unique loan identity; current cache can revise history. |
| `canonical_name` | text; entity display name | Same entity lookup join as `entity_id`. | Related resolution tests/diagnostics. | Display/grouping. **Defined:** not a source-exact name; avoid grouping solely by name. |
| `extracted_industry` | text; source/identifier industry | S hierarchy industry; U fills from identifier-extraction lookup. | Wrapper/extraction tests; related classification checks. | Industry research/GICS inputs. **Mixed F06:** structural extraction and cached enrichment share a field. |
| `gics_sub_industry` | text; normalized industry classification | U cached GICS plus fund-strategy remaps. | GICS tests/cross-checks. | XA/XF exposure and concentration charts. **Defined with inference F06:** not issuer-disclosed GICS, and no per-row vintage/confidence in unified. |
| `lien_position` | text; First Lien/Second Lien/Unsecured for direct lending | CL keywords, staged reconciled overlay fallback, then cached reviewed classification. | Lien/unified tests, wrapper signatures. | Lien mix and spread-by-lien. **Mixed:** different evidence sources; no dedicated source/confidence column in unified. Senior secured wording is not universal proof of first lien. |
| `instrument_type` | text; Revolver/Delayed Draw Term Loan/Term Loan/Unitranche | CL keyword priority with staged fallback. | Instrument/unified tests. | Position-level mix/matching. **Defined with limited vocabulary:** blank may be bonds/equity/unknown, not extraction failure; not a complete instrument taxonomy. |
| `position_key` | text; parsed within-fund instrument discriminator | S normalized issuer/instrument or per-CIK raw-text key; U wrapper replacement and selected duplicate-lot disambiguation. | Wrapper, tranche-identity and matching tests. | Matching candidate generation. **Gap F12:** not guaranteed unique/stable across every quarter/build; not a cross-fund security identifier. |
| `position_id` | text; inferred cross-quarter chain identity | Blank at S; M assigns chains in returns/matching workflow, default registry off. | Matching/registry tests and independent match-gold apparatus. | PIK transitions/history. **Gap F12:** can renumber per rebuild; do not expose as durable external/API key. |
| `row_id` | text; source-anchored observation identity | U final `_assign_row_ids`: source+accession+context hash; content-ranked suffix for collisions; natural-key fallback. | Row-ID tests, preservation through matching tests. | Source reconciliation, correction selectors. **Defined with limit F12:** not cross-quarter identity; fallback and colliding groups can change with content. |
| `row_id_basis` | text; anchor versus fallback pathway | U `src_anchor` or `natural_key`. | Row-ID tests; T text. | Identity eligibility. **Defined:** `src_anchor` does not remove collision caveats or identify amended filings as the same observation. |

## 11. N-PORT-only columns retained in the shared artifact

Every field below is explicitly emitted as empty by BDC staging. These columns remain part of the physical shared schema; this audit does not authorize changing N-PORT or dropping columns. T supplies text types; N-PORT parsing/validation was not audited here.

| Field | Type / existing meaning | Actual BDC transformation | Validation boundary | BDC consumer / status |
|---|---|---|---|---|
| `nport_holding_id` | text; N-PORT holding ID | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_series_name` | text; reporting series name | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_series_id` | text; reporting series ID | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_asset_cat` | text; original asset category | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_issuer_type` | text; original issuer category | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_payoff_profile` | text; source payoff profile | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_investment_country` | text; source investment country | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_is_restricted` | text; source restricted-security flag | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_quarter` | text; source quarter metadata | Empty. | N-PORT-only; T. | **Out of scope.** |
| `nport_is_default` | text; source default flag | Empty. | N-PORT-only; T. | **Out of scope:** no corresponding BDC default label may be inferred from this blank. |
| `nport_are_interest_payments_in_arrears` | text; source arrears flag | Empty. | N-PORT-only; T. | **Out of scope:** not BDC confirmed-no-arrears. |
| `nport_is_paid_in_kind` | text; source paid-in-kind flag | Empty. | K has source-specific handling. | **Out of scope:** BDC current PIK uses separate evidence. |
| `nport_currency_code` | text; source currency code | Empty. | N-PORT-only; T. | **Out of scope:** use BDC unit/currency columns. |
| `nport_liquidity_classification` | text; source liquidity bucket | Empty. | N-PORT-only; T. | **Out of scope:** blank does not classify BDC investment liquidity. |

## 12. Relevant information outside unified holdings

These existing fields/artifacts are part of the architecture and must not be mistaken for absent definitions. This is a targeted dependency map, not a complete field audit of each auxiliary table.

| Existing artifact / fields | Defined meaning and actual behavior | Validation / consumer | Crosswalk consequence |
|---|---|---|---|
| E raw `interest_rate_floor`; R `interest_rate_floor` | Extractor concept mapping and per-CIK grammar already support a floor. Not a column in unified. | Grammar/source checks where evidence exists. | Preserve optional disclosed floor evidence; promotion/use needs a clear distinction between benchmark floor and total-coupon floor. Do not invent missing floors or mandate completeness. |
| R `interest_rate_all_in`, `interest_rate_cash_leg`, `interest_rate_total`, `pik_convention` | Explicit inclusive/additive grammar semantics. `apply_grammar` derives cash or total and currently treats missing parsed PIK as 0 in these arithmetic branches. | Grammar invariants/held-out tests and separate promotion workflows. | An intermediate derivation is not a globally migrated output contract. Missing-as-zero assumption needs applicability tests before reuse. |
| C rate-convention artifacts and per-CIK overrides | Classify reported cash/all-in/unknown; evidence includes concepts, source labels and reconciliation signals. `rate_convention.py` itself does not alter holdings. | Convention validation/agent evidence; XI return adjustment uses the convention-gate artifact. | Reuse this machinery for F01; do not assume a single convention for every field, filing period or row without checking scope. |
| K `pik_current_status`, `pik_current_flag`, `pik_current_evidence` | paying/not_paying/unknown based on position-level evidence. Terms-only remains unknown. Booleans are exported as text true/false/blank. | `test_pik_status.py` explicitly separates fund income, position evidence and terms. | Existing strict status contract should remain separate from schedule terms. |
| K `pik_current_amount` | Sum of matched PIK evidence amounts; underlying extractor retains concept, unit, period and evidence kind. | Position-evidence matching; aggregation tests. | Not automatically a clean quarterly cashflow: stock/flow periods, repeated concepts and units need an explicit analytical aggregation contract before summing economically. No error count measured here. |
| K `holding_row_id` | Currently assigned from reset DataFrame index converted to text, not unified `row_id`. | Local matching/sorting in PIK builder. | **F12:** run-local join key, not stable observation identity across rebuilt artifacts. |
| K `pik_terms_flag`, `pik_terms_rate` | Positive `pik_rate` marks terms; missing numeric rate is treated as 0 for the boolean. | PIK tests and schedule proxy exports. | False means no detected positive terms, not affirmative absence. Keep missing-rate coverage visible. |
| K schedule/current transition outputs | Separate definitions for current-status transitions and `pik_terms_started`; terms-started excludes first-seen-with-terms. | PIK transition tests; depends on M matching. | Not confirmed distressed PIK amendment; historical matching changes can alter event inference. |
| `fund_financials.csv` | Independent fund balances such as NAV/assets; used for reconciliation and percentage denominators. | Fund validation and source anchors. | Retain outside position table. Auxiliary fields not exhaustively re-audited here. |
| `bdc_fund_income.csv` / fund highlights | Income and per-share financials in separate modules/artifacts. | Income/convention checks; fund analytics. | Required for fund cashflow research; holdings changes alone are not purchases, repayments or investor distributions. |
| `provenance_ledger.csv` / summary | Per-row/field verification results and reason codes. P currently enumerates eight numeric fields. | P and quarter/shadow consumers. | Do not call all 88 columns verified because one financial field or a fund-level sum reconciles. |
| `row_validation_issues.csv`, column-quality and quarter-acceptance artifacts | Diagnostics, quality metrics and release assessment have separate schemas. | V and Q. | Retain their distinction; link a field's rule to its actual gate consumer. |
| Database DDL and frontend JSON types | [db.py](../../pipeline/db.py) defines `pmi_holdings`; frontend interfaces define derived response shapes. | Database/export tests where applicable. | Additional consumers, not authorities overriding CSV financial semantics; not certified for complete 88-column parity by this audit. |

## 13. Confirmed discrepancies and bounded decisions

Priorities below are recommendations for owner review, not approved code changes. They distinguish directly observed code behavior from consequences inferred from that behavior.

### F01 - Coupon target versus mixed rate storage (high)

**Observed:** E maps PaidInCash and bare interest-rate concepts into `interest_rate`; C/B1 states an all-in target. S normalizes magnitudes but does not universally combine cash and PIK. V C113 explicitly permits some effective-yield observations. XF computes WAC from positive stored rates without joining the convention artifact. XI return income conditionally adds PIK according to a convention-gate CIK list.

**Consequence:** WAC is not established as a comparable all-in contractual coupon across the population. Fixing storage alone could double-count PIK in return consumers. Similar caution applies to a spread that may include PIK. This is a code-established semantic risk, not a measured error percentage.

**Decision:** retain existing convention/grammar evidence; agree applicability and separate economic rate kinds before the already-required atomic storage/consumer migration. Review rate scale normalization at the same time: S uses <=0.50/>=50 branches, while R `normalize_rate_pct` uses abs(value)<1. These are different functions over different inputs; test common boundary examples rather than assuming either is universally correct.

### F02 - Source cost and FV proxy share a field (high)

**Observed:** U intentionally replaces missing/zero cost with an FV proxy and stamps `cost_source`. XF cost totals/underwater measures and XA `_export_credit_risk` use cost without a `cost_source` eligibility check. The credit-risk extract does not select that marker.

**Consequence:** those outputs are not guaranteed to describe reported-cost marks. Replacing a legitimate zero is also economically different from filling missing data. This is not undocumented behavior: the proxy is described and tested, but some consumers do not distinguish it.

**Decision:** specify eligibility/labeling for reported-cost analytics; preserve historical proxy consumers until deliberately migrated. Whether to split the column is a later implementation choice.

### F03 - Currency and missing-unit assumptions (high for par/FX analysis)

**Observed:** S preserves normalized unit tokens rather than guaranteed ISO currencies; blank principal unit follows the USD path and is labeled `source_usd`. V's FX02/FX03 accepts USD-like tokens more broadly than the direct principal conversion branch.

**Consequence:** an apparent currency and conversion status may represent an assumption or token-format artifact. No general FV/cost FX conversion is supplied by these columns.

**Decision:** define unit-token normalization separately from currency identification; distinguish explicit USD from assumed USD. Test disclosed foreign currency, namespace units, blank units and missing FX before changing defaults.

### F04 - Percentage denominator and raw/recomputed provenance (medium)

**Observed:** S normalizes percentages; U can recompute them from consolidated NAV and stamps `corrected_fields` while retaining the original pathway marker. Eligibility begins with aggregate pct sum >200, not direct proof that the original denominator is wrong.

**Consequence:** one column contains source and recomputed percentages. Leveraged portfolio FV/NAV can legitimately exceed 100%; pct/NAV is not portfolio weight.

**Decision:** preserve source-versus-derived evidence and define denominator eligibility. Do not use a sum near 100% as a universal correctness test.

### F05 - Validation definitions and enforcement differ (high governance priority)

**Observed:** U source/coupon enums differ from V; maturity sentinel policies differ between S and V. U schema violations only log. U applies some caches/overrides after `_enforce_schema`. T enforces physical companion shape/casts but does so after CSV write. V describes itself as reporting, not downstream gating; `ACTION_BLOCK_VERIFIED` is an issue label, not direct enforcement.

**Consequence:** a valid Parquet file, a column FAIL and a quarter PASS can answer different questions. Type enforcement is not economic validity or atomic publication.

**Decision:** document each check's layer and release consumer; reconcile contradictory value vocabularies. Do not make every heuristic flag fatal or widen thresholds to force agreement.

### F06 - Historical output is not a point-in-time ML feature store (high for ML)

**Observed:** S latest-amendment selection drops earlier alternatives from unified. U cost window includes following rows; shares use full-history medians and can take following donors; classification stabilization uses all available observations. Entity/industry/GICS/lien enrichment consumes current caches rather than an as-of lookup shown in this build.

**Consequence (inference):** later information can change earlier features even when filing_date is retained. Selecting training rows by report_date or filing_date alone does not remove that leakage. Reproducible current output and point-in-time-correct historical features are different requirements.

**Decision:** retain latest-best historical output for research; define a separate as-known-at-cutoff mode/feature contract if predictive backtesting is undertaken. Existing snapshots support regression but do not by themselves restore vintages of every feature.

### F07 - Maturity precision/perpetual meaning is lost (medium)

**Observed:** S converts month/year to month-end, drops year >=2099, and does not persist precision/perpetual status. V documents a 9999 sentinel. A text-source marker can survive a failed date parse.

**Consequence:** exact maturity-day analysis and matching vetoes may consume an inferred day. Blank conflates absent, invalid and removed perpetual sentinel.

**Decision:** agree precision and perpetual representation; preserve optional missingness. Do not infer a full repayment schedule from a maturity date.

### F08 - Negative evidence is not uniformly represented (high for stress research)

**Observed:** non-accrual missing/unparseable flags become false. K current PIK has a genuine unknown state, but schedule-terms boolean treats missing rate as zero. K labels matched non-positive evidence `not_paying`; that is evidence/aggregation-specific, not blanket performing status.

**Consequence:** no detected flag is not confirmed absence. Changes in disclosure or matching can appear as economic transitions.

**Decision:** reuse the strong existing PIK distinction and make detected/confirmed/unknown coverage explicit for each analysis. Do not redefine `pik_terms_started` as bad PIK.

### F09 - The saved BDC identifier is not guaranteed verbatim (medium)

**Observed:** S publishes `_raw_id` after identifier normalization/affiliation stripping. D/V wording refers to a raw identifier. Original source anchors/dimensions and cached filings still exist.

**Consequence:** consumers cannot rely on this string being an exact source quote, even if it works as the established correction key.

**Decision:** document current semantics, retain keys for compatibility and locate verbatim source through existing evidence. Add a separate verbatim field only if a concrete consumer requires it.

### F10 - Published population versus presentation-adjusted checks (high)

**Observed:** A requires straight cohort holdings sums for public FV. Q v3 uses published basis without subsidiary/category exclusions; older subsidiary-aware conservation guidance still exists. `is_subsidiary` and `jv_subsidiary` have different origins. XA credit-risk charts explicitly apply DL/positive-FV and optional GAV eligibility filters, so their denominators are narrower.

**Consequence:** different totals are not automatically bugs, but every metric must name its population. A qualified credit-stress denominator must not be presented as the public total portfolio. No current chart-reconciliation measurement was run here.

**Decision:** preserve the canonical public total and document analytical subsets. Resolve paused gate policy through the existing owner process, not via this schema audit. XH also falls back to broader references/empty filter if scope files are unavailable; decide fail-closed publication behavior separately.

### F11 - Documentation drift and uneven verification coverage (medium)

**Observed:** D calls UGL source reserved/always blank; S now populates it when `_ugl` exists. D gives some staging fields as text while T persists integer/date types. U's comment mentions one appended row-ID column although the artifact has two. P enumerates eight numeric fields, not all identifiers/classifications/terms.

**Consequence:** readers can mistake stale descriptions for runtime contracts or extrapolate numeric provenance checks to every datapoint.

**Decision:** update existing reference sections after this crosswalk is reviewed; distinguish stage type from persisted type and verification scope from source presence. No replacement schema system is required to do that.

### F12 - Several identifiers have different stability guarantees (high for API/history)

**Observed:** M default registry remains off; position IDs can renumber. U row IDs are source anchored with explicit fallback/collision behavior. K still creates `holding_row_id` from the DataFrame ordinal. Entity IDs identify borrowers, not facilities.

**Consequence:** these keys cannot safely substitute for one another across builds, quarters or datasets. A stable row anchor is not evidence that two funds own the same legal tranche.

**Decision:** document permitted join scope now; use existing source IDs in a separately tested PIK migration and decide registry/external-key policy before an API or historical event contract depends on it.

## 14. Existing per-CIK and agent contracts: retain, do not recreate

| Layer | Existing implementation | What the crosswalk requires next |
|---|---|---|
| Per-CIK extraction/dispatch | W v3 schema and wrapper JSONs; S reads staging specializations. | Tie each parsed output to the common financial meaning and source evidence. A CIK-specific parse is not a CIK-specific definition of cost or cash coupon. |
| Per-CIK grammar | R JSONs carry extractors, types, available/unsupported datapoints, PIK convention and invariants. | Use actual disclosed terms; distinguish intermediate fields from production output. Do not count a supported grammar field as universally populated. |
| Per-CIK conventions | C classification/overrides and separate validation artifacts. | Resolve F01 using the existing evidence, keeping ambiguous regimes unresolved. |
| Corrections | U manual rows, promoted B2 leaves and promoted rule layers; separate authoring schemas/contracts. | Audit whether the changed field's economic meaning is independently checked, not just FV conservation. Correction precedence already exists in code; catalog it before consolidation. |
| Agent design | [WRAPPER_SYSTEM.md](../wrapper/WRAPPER_SYSTEM.md), [B2 contract](../adjudication_architecture/B2_remediation_contract.md), associated validators. | Existing architecture already says agents propose deterministic rules. Do not treat all design requirements as fully enforced without tracing promotion and gate consumers. |

## 15. Benchmarks to reuse

- [Official baseline manifest](../refactoring/baseline_manifest.json) and `data/snapshots/baseline/`: current regression reference. Do not refresh it merely to erase semantic deltas.
- [Source-labelled positions](../../data/gold/labels/position_labels.jsonl) and frozen sample/label schema under `data/gold/`: reusable evidence, not a complete contract test for every column. The prior inspection counted 132 records/128 distinct keys; no re-estimation was performed in this audit.
- Match-gold batches under `data/output/match_quality/gold/`: evaluate chain/match behavior separately from numeric fields.
- [gold_standard.json](../../tests/fixtures/gold_standard.json): five placeholder entries with null expectations; not an active source-correctness benchmark until populated.
- Existing named tests above: preserve current-behavior tests, but explicitly distinguish them from desired-definition tests when an intentional migration changes expected semantics.

## 16. Bounded follow-up, not a wholesale redesign

1. Review F01/F02/F03/F08 and agree what existing analytics may claim today, with source/unknown/proxy eligibility.
2. Reconcile F05/F11 in the existing docs/types/validators; record which source is authoritative for each layer.
3. Add source-backed acceptance cases to the existing benchmark apparatus for the approved semantic changes, including false positives and legitimate missing disclosures.
4. Implement each change separately with targeted tests, cached rebuild, semantic diff and signed-quarter re-attestation where holdings change. Rate storage and income consumers are one atomic semantic migration.
5. Treat F06/F12 as explicit prerequisites for point-in-time ML and durable API identifiers, not reasons to replace the current research dataset.

No definitions, thresholds, per-CIK rules, pipeline behavior or public outputs are changed by this document. No source-based accuracy percentage is asserted. The crosswalk is complete for the saved 88-column header, but auxiliary artifacts, every override instance, all runtime paths and population-level correctness are not exhaustively certified.

## 17. Documentation verification

- Saved CSV header versus crosswalk: 88 columns, 88 unique field rows; no missing or extra fields.
- Persisted `OUTPUT_SCHEMAS` types versus documented field types: 88 compared, zero mismatches.
- All relative links in this crosswalk resolve to existing local paths.
- Investigation index regenerated with the existing tool; the pre-existing conservation investigation entry was preserved.
- Documentation diff whitespace check completed. No pytest, rebuild, semantic output diff, frontend build/export or quarter re-attestation was run; this task changes documentation only.

## 18. Availability audit and preferred representations

Follow-up dated 2026-09-08. Question: which choices in F01-F12 are supported by existing data, rather than an idealized complete disclosure schema?

### Population and limitations

- Active 70-CIK wrapper manifest, BDC source only, report dates 2025-12-31 and 2026-03-31 (Q4-2025 and Q1-2026, not Q4-2026).
- Current unified typed companion: 2026-09-08 16:49 local; extracted BDC companion: 2026-09-05 08:33; strict PIK companion: 2026-09-05 10:02. CSV remains canonical. These are not all one synchronized build.
- Curated population: Q4 28,938 rows / 67 funds / $374,335,565,067 FV; Q1 30,067 rows / 69 funds / $381,537,030,207 FV. Straight cohort sums, not certified correct totals.
- Extracted BDC comparisons restrict to the same cohort, current-period records and accessions present in curated holdings. Joining accession + source context yields 28,873 Q4 and 30,028 Q1 matches, with unique extracted anchors. Extraction is an intermediate artifact, not an independent ground-truth label set.
- Read-only DuckDB aggregates plus three bounded cached-XML inspections; no exhaustive filing-table review. Row coverage is not accuracy, FV coverage, or proof of disclosure absence. All recommendations below are proposed choices, not implemented changes.

### Most useful coverage measurements

The following percentages use only rows classified DIRECT_LENDING: 25,659 Q4 and 26,541 Q1. Classification itself was not revalidated here.

| Populated field | Q4-2025 | Q1-2026 |
|---|---:|---:|
| Interest rate, before resolving its meaning | 78.8% | 78.5% |
| Spread | 84.9% | 87.4% |
| Maturity date, regardless of precision | 95.6% | 95.4% |
| Principal in its recorded original unit | 92.3% | 90.1% |
| Principal in USD | 42.7% | 39.7% |
| Lien classification | 93.3% | 93.3% |

### Decisions supported by availability

| Issue | Evidence from the inspected artifacts | Preferred representation / next decision |
|---|---|---|
| F01 - Cash versus all-in rate | Q1 matched extraction has 1,621 explicitly cash-rate concepts. Premier Roofing's cached XML separately reports 11.49% cash and 2% PIK. The existing convention registry has 40 all-in, 19 cash-leg and six unknown cohort records, with mixed confidence; the older shadow convention gate has different categories/counts. | Preserve reported rate plus meaning, and separate cash/PIK/all-in values when supported. The sample supports 13.49% all-in, not adding PIK to every reported rate. Prefer a disclosed coupon over reconstructing it from a contemporary benchmark; inferred rates need benchmark date/reset assumptions. Reconcile the existing convention artifacts instead of voting between them. Any storage migration must also update income consumers atomically. |
| F02 - Reported cost versus proxy | Source-extracted cost exists on 28,842/30,028 Q1 matched rows (96.1%), including 969 explicit zeros. Curated Q1 contains 1,425 proxy-cost rows, but only 0.28% of absolute FV. | Reported cost is sufficiently available to remain the analytical default. Keep legitimate zero values. Separate an explicitly modeled cost proxy; do not silently treat missing cost as FV or use a proxy in reported markdown analysis. The proxy's small FV share does not establish that it is harmless for row-level ML. |
| F03 - Currency and USD principal | Q1 original principal coverage is 90.1% of direct-lending rows versus 39.7% USD principal. Across both quarters, 23,980 populated principal values carry `U_USD` and `missing_reference_fx`. In the independently checked XML, `U_USD` resolves to `iso4217:USD`. The reference FX CSV currently has a header and no rates. | Resolve source unit IDs to their actual currency measures, preserving original principal and currency. Then derive USD principal using dated FX only for genuinely foreign currency. A USD-token screening suggests Q1 coverage could reach about 87.0%, but this is a recovery candidate estimate, not a validated fix. Do not apply FX to FV/cost just because principal is foreign-denominated. |
| F04 - Reported %NAV versus recomputed ratios | Q1 has 15,490 populated percentages, and 6,975 rows marked corrected for this field. Positive same-quarter NAV is present for 65 cohort funds in fund financials, not all 70. | Keep reported %NAV distinct from derived holding FV / fund NAV and portfolio weight. Derive only with aligned date, consolidation scope and currency. A sum above 100% can be consistent with leverage; missing denominator remains unknown. |
| F05 - Contract checks versus release gates | The code crosswalk establishes vocabulary/enforcement differences. No row-frequency claim is made about their effects. Field availability also clearly differs between debt and equity. | Keep structural requirements strict and economic checks applicability-aware. A missing coupon on equity is not a broken row; a prohibited enum is a contract issue. Reuse existing validators and quarter gates, documenting which checks actually block publication. |
| F06 - Latest-best history versus point-in-time history | Filing/accession anchors largely exist, but the inspected transforms use latest amendments, later cost/share donors and full-history/current enrichment. This audit did not inventory every historical cache vintage. | Keep latest-best history for descriptive research. Build separately cutoff-controlled features before predictive backtests. Cached filings are useful inputs, but a baseline snapshot is not proof that every feature was available at the historical prediction date. |
| F07 - Exact maturity versus partial/unknown date | Q1 direct-lending maturity coverage is already 95.4%. Across all Q1 holdings, 11,727 maturity source markers are `ixbrl_field_status`; this is a material existing enrichment path. Matched Q4 extraction contains 37 dates in year 2099 or later; none survive in saved maturity. | Retain the existing enrichment. Preserve reported text, date precision and missing/sentinel reason. Do not invent exact maturity days, assume every removed sentinel means perpetual, or infer a repayment schedule from maturity alone. |
| F08 - PIK/non-accrual: absent versus unknown | Current curated Q1 has 2,246 positive PIK-term rates and 465 detected non-accrual flags. The older strict PIK artifact is entirely unknown for both selected quarters (28,942 / 30,083 rows). Extracted evidence nevertheless contains 20 positive position-income records per report date and one positive capitalization record in Q1; these are evidence records, not a verified count of current published positions. | Use disclosed PIK terms as the broad terms-exposure measure; preserve strict current-payment/accrual status separately. Investigate evidence-to-position attachment and period eligibility before claiming that current PIK is universally undisclosed or that its matching is broken. No flag is not confirmed performing; terms appearing is not confirmed distressed amendment. |
| F09 - Verbatim versus normalized identifier | 7,842/30,028 Q1 matched identifier strings differ between extracted and unified data. Original identifiers and cached dimensions remain accessible. | Keep normalized keys for current matching/corrections, but preserve separate source wording/evidence for audit. A transformed identifier is not a verbatim filing quote. This is preservation and documentation, not a need for new disclosure. |
| F10 - Public total versus analytical subsets | Current Q1 holdings sum to $381.537bn across the cohort and include 66 `is_subsidiary` rows. Direct-lending rows are a smaller population. | Preserve the canonical straight public holdings sum. Define each analytical denominator explicitly; retain-and-flag subsidiary rows. Whether a figure is consolidated exposure or look-through exposure is an analytical choice, not a license to silently remove rows. No publication/gate policy was changed. |
| F11 - Existing schema versus stale descriptions | Runtime maturity enrichment was missing from the initial crosswalk pathways and is corrected above. UGL fields can be populated by code but are blank in both inspected curated quarters. Numeric provenance replay covers eight fields, not the complete schema. | Update the existing dictionary and show current availability separately from supported behavior and verification. Do not create a competing schema or call every populated field verified. Derived FV minus comparable reported cost is a separate metric, not evidence of a reported UGL fact. |
| F12 - Observation, chain and borrower identity | Source-anchored rows: 30,028/30,067 Q1; borrower IDs: 29,207. Current saved `position_id` is blank throughout both selected quarters. Chain assignment exists in the returns/matching workflow, not initial staging, and its registry is off by default. | Use source anchors for filing observations and the existing matcher for quarter-to-quarter position chains. Require compatible, completed matching outputs before transition analysis. Do not substitute borrower IDs for facilities or expose rebuild-dependent chains as durable API identifiers. No rebuild-cause diagnosis was performed. |

### Optional terms: floors are partly available, but not automatically usable

Floor-tag values occur on 5,594 of the 30,028 Q1 matched source anchors (18.6% of all matched positions, not a debt-only disclosure rate). They are not among the saved unified columns. This supports retaining an optional source-evidence field, not requiring a floor for every loan. A checked iHeart corporate-bond source tags 9.13% as `InvestmentInterestRateFloor`, while its identifier also gives a 9.13% coupon; the economic interpretation needs the filing table/footnotes, which this audit did not resolve. Do not automatically apply every floor-tag value as a contractual benchmark floor. No cap-availability estimate was established.

### Cached source checks and reproducibility

Three XML files were parsed without networking, entity resolution or mutation:

- `data/raw/filings/bdc_xbrl/1572694/000119312526212431.xml`, context `C_0062ecb4-8c64-4506-be56-da5d44c46222`: ML Holdco principal 12,786,000 in `U_USD`, whose measure is USD, versus blank curated USD principal. This context also has a native SOFR extensible-enumeration fact, demonstrating at least one source-backed alternative to benchmark inference; recovery coverage was not measured.
- `data/raw/filings/bdc_xbrl/1742313/000174231326000013.xml`, context `c-145`: Premier Roofing separate 0.1149 cash and 0.02 PIK facts.
- `data/raw/filings/bdc_xbrl/1588272/000119312526134282.xml`, iHeart 9.13% corporate-bond context: floor-tag interpretation caution above; `Unit_USD` also resolves to USD.

Session diagnostics are in `scratch/2026-09-08_schema_availability/`: `profile_availability.py` (read-only DuckDB, two threads, 768MB limit, no spill, 75-second watchdog) and `check_source_samples.py` (three named XML files, size/fact limits, 45-second watchdog). Both completed successfully. Scratch is disposable; the substantive measurements and limitations are recorded here. No tests, rebuild, output semantic diff, export or quarter re-attestation was run. No production data or financial definitions changed.

## 19. Programme target extension

Added 2026-09-09 following owner resolution of D01-D13. The [target contract](../production_stack/02_data_contract.md) extends this crosswalk with field-family meaning, proposed authoritative writers, explicit schema deltas, related-record keys, evidence categories and migration boundaries. The [field disposition CSV](programme_field_disposition.csv) maps all 88 existing columns in saved-header order to sixteen contract families, current physical type, disposition, target writer, delta, decisions and acceptance criteria. The [measurement register](../production_stack/04_acceptance.md) covers all 28 accepted criteria.

This extension preserves the holding observation/lot grain. It does not require a replacement schema from scratch, make optional disclosures mandatory, or remove shared N-PORT columns. New fields and related records remain a versioned implementation design; current types and public data have not changed.

| Finding | Accepted policy / target implementation | Authority and required validation |
|---|---|---|
| F01 | All-in coupon with supported cash/PIK components, reported value/kind preserved and no missing-rate estimates. Spread kinds remain explicit. | H06/H09; convention-aware normalization and atomic income/export migration. B1/B2/B5. |
| F02 | Preserve disclosed cost including zero; add reported-cost representation and donor-linked first-observed-FV analytical fallback for absent cost. | H03/H09; identity-safe donor selection and proxy contribution. B1/B2/D1/D2. |
| F03 | Explicit or assumed USD distinguished; resolve actual XBRL units, preserve original principal and source valuation evidence, and expose unresolved foreign FX. Target proposes common USD valuation/cost normalization before the public sum. | H03/H09; SPEC-FX must inventory actual non-USD valuation and define dated FX before migration. B1/B2/B3/B4. |
| F04 | Source-reported NAV percentage, derived NAV ratio and portfolio weight are distinct; existing portfolio display retained. | H04/H09; shared metric definitions and independent fund denominator evidence. B1/B3/B4/E2. |
| F05 | Existing schema/type/field/gate machinery has distinct authority; validate the final candidate and calibrate final numerical metrics under D12. | Authority table and single finalizer in target contract; no live-threshold change. B1/F1/F3/F5. |
| F06 | Latest-best history with pinned source precedence, decision versions and reproducible releases. No as-known-at-cutoff product. | H01/H09/H12-H15 and release relation; later decisions retain actual dates. A3/C4/D2/F2. |
| F07 | Retain source-exact or month-end maturity, with precision, year-only partial state and evidence-backed perpetual/unknown interpretation. | H07/H09; shared matcher/analytics interpretation. B1/B2/C3/E2. |
| F08 | Detection flags remain distinct from known-negative/unknown status; PIK terms/current accrual/distressed amendment claims stay separate. | H10 and existing PIK relation with durable joins; applicability and period checks. B5/D1/E2. |
| F09 | Preserve normalized working identifier and separately anchored source wording; citations resolve field-specific evidence. | H08/H09/H15; HTML/iXBRL primary, PDF deferrable. D1/D4/D5. |
| F10 | Retain records and canonical sum; declare source-accounting membership and evidenced relationships. No required ownership-adjusted analytic or new HTML campaign. | H11 plus obligation/accounting relations; independent source rosters and anchor bridges. A1/A2/A5/B3/B4. |
| F11 | Reconcile descriptions, types and field verification scope; support sector-only GICS and optional finer classifications. Reported UGL remains distinct from derived measures. | H05/H08/H09/H13 and schema authority; current support, fill and accuracy remain separate. B1/D1/D3/F1. |
| F12 | Stable borrower, within-filer position and source-observation IDs have separate scopes; aliases and merge/split history preserve revised joins. | H12/H14/H15; existing resolver/matcher/registry extended and tested under SPEC-ID. C1-C4/F2. |

P2 now has an initial field/relationship authority map. Remaining work is identified as SPEC-FX, SPEC-ID, SPEC-RULES, SPEC-REF, SPEC-VIEW and SPEC-GATE in the target contract. Complete active-rule precedence, benchmark applicability, detailed technical dependencies and measured calibration before declaring launch readiness. The specification draft does not certify those tasks complete.

Verification: 88 disposition rows match the current saved CSV header/order and physical schema; no existing field omitted or duplicated. All twelve findings and all 28 outcome criteria have design/measurement mappings. Local links and document consistency checked. No tests, rebuilds, exports, threshold changes or production writes.

Subsequent trace, 2026-09-09: the
[F01-F12 conflict resolution](../production_stack/03_pipeline_design.md)
now specifies actual writer/overlay order, existing incompatible test expectations,
target dispositions and bounded implementation packets. Its
[saved-input assessment](../production_stack/04_acceptance.md)
records fresh thirteen-quarter profiles, the 910-slot obligation frame and
correction-instance evidence. Findings remain implementation work; the completed
design trace does not mean the conflicts are fixed or the programme has passed.
