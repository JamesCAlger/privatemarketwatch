# Validation Inventory (tier-tagged, for review)

Compiled 2026-06-15 by reading every validation/guard across the pipeline.
Purpose: see the whole validation surface at once, separate **what we can prove**
(tight) from **what we can only flag** (weak), and see **what is actually
enforced** vs merely reported — so we can graduate checks to a universal,
read-only shadow panel and then promote the tight-but-unenforced ones to gates.

## Legend

- **method**: reconciliation_source | identity | arithmetic | range_threshold |
  fill_coverage | anomaly_stability | format_schema | cross_reference | dedup |
  correction_transform
- **tier**: `tight` = reconciles against an independent source OR is an algebraic
  identity; `weak` = range/fill/anomaly/format/internal-consistency only.
- **enforcement**: `blocking` (fails/stops/removes-from build) | `advisory`
  (writes a report, never blocks) | `opt_in` (only runs when invoked/configured)
  | `inline_mutate` (silently changes data during the build).

---

## 1. Synthesis (the part that matters)

**Scale.** ~450 distinct checks/guards across: `oracle_checks.py` (48),
wrapper oracle + content signatures (~40), `validate_holdings.py` + `validation_rules/` (~115),
highlights/financials/nonaccrual/cik validators (~60), column/strategy/llm/html/source-recon (~145),
inline build guards (~50).

**Enforcement reality — the headline.** Almost **nothing blocks the production
build**:
- `oracle_runner` runs 48 checks but only exits non-zero with `--fail-on-failure`
  (a manual CLI flag); it is **not on the build path**. Every oracle check is
  effectively advisory.
- `validate_holdings.py` writes CSVs and **never raises**.
- `validation_rules.run_all()` computes PASS/WARN/FAIL and **does not raise**;
  "blocking" only means a `promoted=FAIL` rule causes dependents to be SKIPPED.
- The highlights oracle's **only** FAIL triggers are `nav_identity` and
  `income_identity`; everything else is "review_required".
- `validate_fund_financials`, `source_reconciliation`, `column_validation`,
  `fund_strategy_validation`, `validate_nonaccruals`, `validate_html_template`
  are all advisory/opt-in.
- **The only things that actually change or stop production data are inline
  transforms** in `unified_holdings.py` / `bdc_filings.py` / `position_matching.py`
  (dedups, `universe_gate` row removal, `pct_of_net_assets_recalc`, scale fixes,
  `position_id` uniqueness `raise`, index min-FV/constituent filters) — and most
  of those are **silent heuristic mutations**, not reconciliations.

So the validation surface is ~450 measurements that nothing enforces, plus a
handful of silent corrections that aren't measured. That is exactly the case for
a **universal, tier-tagged, read-only shadow panel** + a small promotion list.

**Tier split.** The large majority are `weak`. The `tight` checks cluster into a
few families — and several of those families are **implemented many times over**.

**Massive duplication (consolidate, don't add).** The same idea is re-coded
repeatedly:
- *Positions-vs-fund-total (GAV/FV conservation)* — at least **12** implementations:
  `A04`, `E01`, `E02`, `V7 check_gav_reconciliation`, `F20`, `GAV_BDC01/02`,
  `GAV_NPORT01`, `R07`, `IDX14`, nonaccrual `chart_population_gate`, html
  `aggregate_fv`, plus my shadow FV gate, plus `pct_recalc`'s use of net_assets.
- *Arithmetic subtotal / rollup* — `A01`, `G02`, `excluded_self_referential_subtotal`,
  `documented_source_rollup_exact`, `documented_source_issuer_subtotal_arithmetic`,
  html `self_referential_subtotal`, `D03`/`PC04` (count-FV divergence signal).
- *pct_of_net_assets sum* — `A07`, `V8`, `F22`, `F23`, `PCT01/02` adapter,
  `PC07`, `R11`, `X09` (and my proposed per-row identity, which is tighter).
- *Duplicate filing / amendment* — `B07`, `H03`, `amendment_dedup`,
  `superseded_amendment`.
- *Comparative period* — `B08`, `excluded_comparative_period`, `PP03`.
- *NAV identity* — `E04`, highlights `nav_identity`, `F11`.
- *Rate scale* — `C113`, `F12`, `R14`, `schema_enforcement` rate cap, Tier-A
  `rate_scale_normalization`, plus my shadow rate gate.

**Checks built on known-unreliable inputs (flag).** `balance_sheet_identity` and
`net_assets_equity` (highlights) and `cross_total_assets` depend on the
substring-bound highlights `total_assets`/`stockholders_equity` (see the
2026-06-15 investigation) — the first two are already demoted to diagnostic; the
third still emits review noise. `validate_fund_financials` F10/F11 are the same
identities on the *reliable* companyfacts schema and should be preferred.

**Silent mutations (highest corruption risk, least measured).**
`cost_proxy_fill`, `shares_power_of_10_normalization`,
`mixed_decimals_monetary_normalization`, `classification_qoq_stabilization`,
`re_fund_gics_remap`, Tier-A `rate_scale_normalization`, and the four+ dedups all
**change data in place** with weak/heuristic logic and no independent
reconciliation. These should be the first to get a before/after measured gate.

**The promotion queue (tight + currently advisory/opt-in).** These already exist
and reconcile — they just don't gate: `A01`, `A04/E01`, `E02`, `E04`, `E07`,
`G02`, `H01`, `H05`, wrapper `fv_reconciliation` (opt-in), the whole
`source_reconciliation` match engine, `V7`, `V10`, `PC02/PC03/PC08`,
`R07`, `R10`, `IDX14`, `XS01/03/04/05/06`, `RI01-07`, `F10/F11/F12/F17/F20`,
nonaccrual aggregate/position/chart reconciliation. Promote = run universally,
tier-tag, tighten tolerance, decide blocking.

---

## 2. oracle_checks.py (`oracle_runner` — all advisory unless `--fail-on-failure`)

| id | validates | column | method | tier |
|---|---|---|---|---|
| A01 | rollup FV = Σ child leaf FV | source_fair_value | arithmetic | **tight** |
| A04 | Σ leaf FV ≈ investments_at_fair_value (fallback total_assets) | fair_value | reconciliation_source | **tight** |
| A07 | Σ pct_of_net_assets in [50,250]%; per-row outlier | pct_of_net_assets | range_threshold | weak |
| B01 | ≥95% leaf contexts have FV | source_fair_value | fill_coverage | weak |
| B02 | no dup position key per CIK-qtr | position_key | dedup | weak |
| B07 | ≤1 accession per CIK-qtr-form (amendment) | accession_number | dedup | weak |
| B08 | comparative rows not still blocking | period,report_date | cross_reference | weak |
| C01 | ≥80% debt rows have rate/spread | interest_rate,basis_spread | fill_coverage | weak |
| C04 | ≥70% equity rows have shares | shares_held | fill_coverage | weak |
| C05 | <10% common-equity rows carry rate | interest_rate | range_threshold | weak |
| C08 | ≥95% classified rows have FV | fair_value | fill_coverage | weak |
| D01 | QoQ count ratio [0.4,2.5] | row count | anomaly_stability | weak |
| D02 | QoQ total-FV ratio [0.3,3.0] | fair_value | anomaly_stability | weak |
| D03 | count >2× but FV flat (subtotal-leak signal) | count+fair_value | anomaly_stability | weak |
| D06 | ≥50% prior issuers persist | issuer_name | anomaly_stability | weak |
| D07 | median rate shift ≤300bps QoQ | interest_rate | anomaly_stability | weak |
| E01 | holdings FV vs investments_at_fv ≤5% (=A04) | fair_value | reconciliation_source | **tight** |
| E02 | holdings FV ≤ total_assets×1.05 | fair_value vs total_assets | reconciliation_source | **tight** |
| E04 | nav_per_share×shares ≈ net_assets (5%) | nav,shares,net_assets | identity | **tight** |
| E07 | source leaf count vs output count <10% | leaf counts | reconciliation_source | **tight** |
| F01 | rates in [0,30]% | interest_rate | range_threshold | weak |
| F03 | ≥99% nonzero FV positive | fair_value | range_threshold | weak |
| F04 | per-row pct in [0.001,25]% | pct_of_net_assets | range_threshold | weak |
| F07 | <2% null FV | fair_value | fill_coverage | weak |
| F08 | no dup (cik,date,issuer,instr,FV) | 5 cols | dedup | weak |
| F09 | identifier text not corrupted | issuer/instr/identifier | format_schema | weak |
| F11 | shares positive | shares_held | range_threshold | weak |
| F12 | no rate >100 (scale) | interest_rate | range_threshold | weak |
| G01 | no aggregate/subtotal keyword rows (~100 kw) | issuer/identifier | format_schema | weak |
| G02 | no row FV = Σ next N rows (subtotal leak) | fair_value | arithmetic | **tight** |
| G03 | no name-only/no-FV header rows | issuer,FV,cost | format_schema | weak |
| H01 | ≥90% source leaf FV contexts in holdings | source_fair_value | reconciliation_source | **tight** |
| H03 | no amendment+original both blocking | form_type,accession | cross_reference | weak |
| H05 | source-only rows documented not blocking | status,blocking_issue | reconciliation_source | **tight** |
| I02 | ≥95% leaf-marked rows have FV | source_fair_value | fill_coverage | weak |
| I05 | ≥85% wrapper/content-signature agreement | wrapper_family,sig_status | cross_reference | weak |
| I06 | ≥80% non-PM rows match cash/treasury kw | raw_identifier | format_schema | weak |
| I08 | pipe-segment pattern meets min prevalence | identifier segments | format_schema | weak |
| I09 | ≤5% leaf issuer_names are GICS labels | issuer_name | format_schema | weak |
| I10 | ≤50% multi-position issuers identical instr desc | instrument_description | anomaly_stability | weak |
| I11 | ≤10% near-dup position keys per issuer | position_key | dedup | weak |
| J01 | ≥70% non-A/B1 matches use B1b key (wrapped) | match_method | anomaly_stability | weak |
| J03 | <10% matches are D_fuzzy (wrapped) | match_method | anomaly_stability | weak |
| J04 | position_id unique per cik,source,date | position_id | dedup | weak |
| J05 | ≤5% lower-tier matches suspect (2+ discontinuity) | FV,rate,principal | anomaly_stability | weak |
| J06 | ≤15% fuzzy matches suspect (JW<0.5 / class flip) | identifier,classification | cross_reference | weak |
| J07 | audit C/D/E flips/maturity/subtype (info) | classification,maturity,instr | cross_reference | weak |
| J08 | ≤5% B2+ matches refinancing (maturity+spread) | maturity,basis_spread | anomaly_stability | weak |

---

## 3. Wrapper oracle + wrapper_content_signatures.py

| id | validates | column | method | tier | enforcement |
|---|---|---|---|---|---|
| field_signature.numeric_range | field parses + in [min,max] | per-archetype field | range_threshold | weak | advisory |
| field_signature.regex/enum/presence | format/enum/required-forbidden | configured field | format_schema/fill | weak | advisory |
| unclassified_rate / _fv_rate | unclassified rows/FV ≤ max_pct | archetype coverage | fill_coverage | weak | blocking(in-oracle), opt_in |
| **fv_reconciliation** | Σ FV ≈ fund anchor | fair_value vs investments_at_fv | reconciliation_source | **tight** | **opt_in + advisory** (never appended to fail reasons) |
| position_count_qoq | QoQ row ratio in band | row count | anomaly_stability | weak | advisory |
| edge_case_detection | known edge-case regex present | text col | format_schema | weak | advisory |
| signature_fail → content_signatures_fail | no row signature_status=fail | sig status | cross_reference | weak | blocking(oracle status), review |
| unclassified_prefix_rows | supported-prefix rows got disposition | raw_identifier | fill_coverage | weak | blocking |
| unparsed_remainder_rows | no leftover unparsed text | unparsed_remainder | fill_coverage | weak | blocking |
| wrapper_blockers_remaining | no wrapper-owned blocking rows | blocking_issue+disposition | cross_reference | weak | **blocking (hard reject)** |
| remaining_{mechanism} | no non-diagnostic blocking mechanism | disposition,child counts | cross_reference | weak | blocking, review |
| wrapper_no_archetypes | wrapper has archetypes | wrapper structure | format_schema | weak | **blocking (hard reject)** |
| exclusion_risk_detected | excluded rows lack position-evidence tokens | disposition+identifier | cross_reference | weak | blocking, review |
| rate_outliers_detected | rate in rate_sanity [min,max] | interest_rate | range_threshold | weak | blocking, review, opt_in |
| cost_fv_ratio_outliers | cost/FV in [0.01,100] | cost,fair_value | range_threshold | weak | advisory (not in fail reasons) |
| fv/rate/cost/spread_magnitude_shift | QoQ median ratio not ≥10× | source_* fields | anomaly_stability | weak | blocking, review |
| concept_drift_detected | XBRL concept churn <30% | concept_names | anomaly_stability | weak | blocking, review |
| low_position_continuity | ≥50% leaf keys persist | source_position_key | anomaly_stability | weak | blocking, review |
| unparsed_remainder_spike / unclassified_rate_qoq_jump | QoQ increase below thresh | rates | anomaly_stability | weak | blocking, review |
| fv_reconciliation_status (oracle wiring) | per-qtr FV recon | fair_value vs anchor | reconciliation_source | **tight** | opt_in + advisory |
| source_reconciliation (cleared/remaining) | cached XBRL facts ↔ holdings | source vs output FV | reconciliation_source | **tight** | blocking (drives remaining_*) |
| WRAP.PARSED_FIELD_CONTAMINATION | parsed fields free of labels/contamination | issuer/instr/poskey | format_schema | weak | advisory (packet) |
| WRAP.SOURCE_VERBOSE_IDENTIFIER | verbose raw id + residue/blocker | raw_identifier | format_schema | weak | advisory |
| WRAP.COLUMN_DISTRIBUTION_DRIFT | per-column QoQ JS-divergence drift | many | anomaly_stability | weak | advisory |
| WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER | repeated high-FV unclassified labels | FV,archetype | fill_coverage | weak | advisory |
| WRAP.ROW_DELTA_ATTRIBUTION | trial-vs-prod holdings delta classification | many | dedup | weak | advisory |
| evaluate_promotion_gate / blocking deltas | trial doesn't increase blocking rows/FV vs baseline | blocking deltas | reconciliation_source | **tight** | **blocking (promotion)** |
| validate_agent_verdict_records / summary | verdict JSONL schema + effects | verdict fields | format_schema | weak | blocking (raises) |
| validate_wrapper_definition_structure / json_coherence | archetypes/keywords/regex coherent | wrapper JSON | format_schema | weak | blocking / advisory |
| materiality P0/P1/P2 | affected-FV/row tiering | FV/rows vs totals | range_threshold | weak | advisory |

---

## 4. validate_holdings.py (V-suite — all advisory; writes CSVs, never raises)

| id | validates | column | method | tier |
|---|---|---|---|---|
| V1 spot_check_top_ciks | sample top CIKs for manual review | classification | anomaly_stability | weak |
| V2 classification_by_cik | BDC >50% / N-PORT >80% UNCLASSIFIED | index_classification | range_threshold | weak |
| V3 audit_aggregate_leaks | aggregate/subtotal keyword rows | issuer/identifier | cross_reference | weak |
| V4a/V4b cross_source_overlap | CIK in both sources / dup holdings (JW>0.85) | cik,issuer,FV | dedup | weak |
| V5 check_coverage | universe CIK has holdings; ratio proxy | counts,FV,net_assets | fill_coverage | weak |
| V6 validate_classification (E1-3,A1-4,I1-3) | exposure/asset_class agree w/ structural truth | exposure_type,asset_class | cross_reference | weak |
| V6-LLM | GPT vs rule classification (opt_in) | classification | cross_reference | weak |
| **V7 check_gav_reconciliation** | Σ FV vs investments_at_fv/total_assets | fair_value | reconciliation_source | **tight** |
| V8 pct_of_net_assets_sum | per-CIK-qtr pct sum in levered band | pct_of_net_assets | range_threshold | weak |
| V9 position_count_stability | QoQ count stability / count-FV divergence | count,FV | anomaly_stability | weak |
| **V10 income_yield_consistency** | income yield / median coupon in band | income_yield,coupon | reconciliation_source | **tight** |
| V11-V14 | delegate to source_recon / position_purity / fund_strategy / column_validation | — | — | mixed |

### validation_rules/ RULE_REGISTRY (`run_all` — promoted=FAIL "blocks" via dependency-skip only; no raise)

PC-series (contract): **PC02, PC03, PC08** index/return recomputation identities = **tight, blocking**; PC01/04/05/06/07/09/10 weak advisory; **PC11/PC12** exclusion-list = blocking.
IDX01-15: index sanity (returns/levels/concentration) — all weak; **IDX14** (index vs fund-NAV return) = tight, advisory.
T01-10: QoQ trend anomalies — all weak, advisory.
S01-10: fund strategy vs holdings mix — all weak, advisory (cross_reference).
R-series: relational sanity — weak except **R07** (FV > total_assets, tight) and **R10** (pik ≤ rate, tight identity); R02 disabled.
XS01-06: BDC↔N-PORT cross-source on shared CUSIP — **XS01/03/04/05/06 tight**, advisory; XS02 weak.
F01-10: freshness/coverage — weak, advisory.
M01-10: entity-resolution integrity — weak, advisory.
**RI01-07**: referential integrity (holdings↔universe↔matches↔returns↔financials; artifact freshness) — **tight, blocking** (promoted FAIL).
diagnostics.py DIST01/02/04/05, MONO03/05: distribution/monotonicity calibration candidates — weak, **opt_in** (never block).

---

## 5. Highlights / financials / nonaccrual / CIK validators

### bdc_fund_highlights_oracle.py (only nav_identity + income_identity FAIL; rest review-only)
| id | validates | tier | enforcement |
|---|---|---|---|
| **nav_identity** | assets_net ≈ nav×shares | **tight** | **blocking** (Group1) |
| **income_identity** | nii ≈ tii − expenses | **tight** | **blocking** (Group1) |
| balance_sheet_identity | TA−TL ≈ SE | weak ⚠ unreliable inputs | advisory (diagnostic) |
| net_assets_equity | assets_net ≈ SE | weak ⚠ unreliable | advisory |
| cross_nii/mgmt/expenses/total_income/incentive/interest | highlights ≈ bdc_fund_income | **tight** | advisory (review) |
| cross_total_assets | highlights TA ≈ fund_financials TA | weak ⚠ highlights side unreliable | advisory |
| cross_nav/shares | highlights ≈ fund_financials | **tight** | advisory |
| nav/expense/nii/shares_qoq, total_return_plausibility | QoQ stability / range | weak | advisory |
| expense_ratio_ordering, facility_capacity_ordering | incl ≥ ex ; max ≥ rem | **tight** (ordering) | advisory |
| total_return_above_floor | tr > −100% | **tight** (floor) | advisory |
| asset_coverage_positive, coverage_ratio_floor | sign / ≥1.0 | weak | advisory |
| core_field_count, class_field_asymmetry | coverage / cross-class symmetry | weak | advisory |

### validate_fund_financials.py (advisory; derives validation_tier)
| id | validates | tier |
|---|---|---|
| F1/F2/F3 | finite values / date not future / quarter matches date | weak (F3 tight) |
| **F10** | TA − TL = net_assets (companyfacts schema) | **tight** |
| **F11** | nav×shares ≈ net_assets | **tight** |
| **F12** | borrowings/TA ≈ leverage_ratio | **tight** |
| **F17** | quarterly_return = compounded monthly | **tight** |
| F13 | mgmt_fee ≤ expense_ratio (ordering) | **tight** |
| F16/F18/F30-F34 | RoC heuristic / coverage ≥1.5 / range bands | weak |
| **F20** | canonical GAV reconciliation_status PASS | **tight** |
| F21/F22/F23 | holdings FV/NA band; pct-sum band; reported pct ≈ derived | weak |
| F24/F25/F26/F27/F28 | QoQ count; FV-vs-assets growth; leverage proxies; income vs WAC; coverage join | weak |

### validate_nonaccruals.py (opt_in CLI; source-reconciled)
| id | validates | tier |
|---|---|---|
| aggregate_fv/cost_reconciliation | flagged non-accrual FV/cost ≈ disclosed XBRL aggregate | **tight** |
| position_level_evidence | each flagged id has source non-accrual evidence | **tight** |
| reconciliation_classification | composite PASS/FAIL per group | **tight** |
| chart_population_gate | DL/all FV reconciles to total_assets [0.7,1.3] before charting | **tight** |
| chart_validation_thresholds | ≥1% contributors PASS & ≥90% FV reconciled | **tight** |

### bdc_cik_validator.py (classifies GAV gate strength; packet for review agent)
| id | validates | tier |
|---|---|---|
| gav_gate_role | strong(investments_at_fv)/moderate(total_assets)/context_only | **tight** (strong/moderate) |
| gav_condition / validation_matrix_cell | GAV ok/under/over × source blockers | **tight**/weak |
| source_blocker_extraction | blocking rows from source_reconciliation residual | **tight** |
| aggregate_leak_context | subtotal/dup-dimension candidate counts | weak |

---

## 6. column_validation / fund_strategy / llm / html_template / source_reconciliation

### column_validation.py (`validate_column_contracts`) — all advisory
- **C001-C008** identity/format: source enum, cik digits, report_date date/not-future, accession present, filing_date, entity_name — weak/format.
- **C101-C119** per-field parse/sign/range: fair_value present/parse/≥0/≠0/≤$3B; cost parse/≥0; principal parse/≥0; interest_rate parse/[0,25]; basis_spread [0,15]; pik_rate [0,20]; shares parse/≥0 — all weak.
- **C201-C207** identifier: issuer present/[3,300] chars; cusip=9; isin=12; bdc identifier present — weak/format.
- **C301-C306** enum: index_classification/exposure_type/asset_class/coupon_type — weak/format.
- **C401-C404 / X09 / X10** dates & pct: maturity parse/year≥1900/perpetual sentinel; maturity ≥ report_date; pct ≤100; pct ≥0 — weak/range.
- **X01-X08** cross-field: PE no rate; PC has rate/spread; Fixed no spread; Floating has spread; FV/cost ≤10× / ≥5%; FV ≤10×cost — weak/cross_reference.
- **FX01-FX04** currency: non-USD DL has usd; BDC FV/cost unit USD; N-PORT fx valid — weak/format.
- **column_fill_metrics / quality_tier** fill thresholds; VERIFIED/UNDER_REVIEW tier — weak.
- **Adapters** (re-package upstream): **GAV_BDC01/02, GAV_NPORT01 (tight), YLD01 (tight), SRC_BDC01/02/03 (tight)**; PCT01/02, CNT01/02, CLS_*, AGG01, PP01/02/03, COV01/02, DUP01 — weak.

### fund_strategy_validation.py — advisory (corrections opt_in)
- FS01/FS02/FS03/FS04 strategy↔holdings mix (RE≥50%, PC≥50%, FoF≤30%, dominant stable) — weak cross_reference.
- strategy_reference / holdings_mix — weak. correction_candidate/apply — **opt_in mutate** (APPLY only, excluded transitions/CIKs).

### llm_fund_validation.py
- llm_confusion_matrix — weak advisory. llm_auto_apply — **opt_in mutate** (PE/Credit/RE only).

### validate_html_template.py — opt_in operator tool (PASS/FAIL gates template acceptance)
- **aggregate_fv** (Σ html FV ≈ companyfacts, [0.7,1.4]) — **tight**. **self_referential_subtotal** (Σ ≈ in-doc grand total) — **tight**. **company_subtotal_detect** — tight (dedup). unit_mismatch — tight. carry_rate / position_count_stability / fv_fill / coverage / name_fill / fv_per_position / negative_fv — weak.

### source_reconciliation.py — additive (advisory); FV tol `max(1, 1e-4·max(|s|,|o|))`
- **Match engine (all tight, advisory):** exact_dimensions_raw, exact_identifier, wrapper_exact/structured_leaf_key, staging_normalized, normalized+FV, numeric_identity, issuer_name_extraction, fv_only_identity, partial_name+FV; plus value_mismatch / diagnostic_field_mismatch / missing_from_pipeline / extra_in_pipeline.
- **Documented exclusions (tight where arithmetic):** excluded_self_referential_subtotal, documented_source_rollup_exact, documented_source_issuer_subtotal_arithmetic, excluded_affiliation_dedup, collapsed_duplicate_dimension_path, superseded_amendment, excluded_comparative_period; (weak) excluded_aggregate/money_market/bad_issuer/hierarchy_header/no_fair_value/pre_2022.
- **Wrapper-vs-staging disagreements:** non_private_market / aggregate_detection / hierarchy_parse / identifier_normalization / family_vs_asset_category / wrapper_leaf_staging_excluded — weak cross_reference.
- **Metrics & residual classification:** reconciled_source_row_rate, reconciliation_status (UNDER_REVIEW); ~24 residual mechanisms (blocking_numeric_*, blocking_identifier_parse_artifact, blocking_fair_value_scale/disagreement, blocking_pipeline_only, documented_source_* headers, blocking_source_pct_*). Reconciliation-class = tight; header/parse-class = weak. All advisory.

---

## 7. Inline build guards (the ones that actually change/stop production data)

### unified_holdings.py
| id | does | column | tier | enforcement |
|---|---|---|---|---|
| nport_within_source_dedup / cross_source_dedup / within_filing_subsidiary_dedup / bdc_dimension_path_dedup | drop duplicate rows (rounded-economics keys) | all | weak | **inline_mutate (drops)** |
| cost_proxy_fill | fill null/0 cost from FV | cost | weak | inline_mutate |
| shares_power_of_10_normalization | replace outlier shares (LOG10>1.5) | shares_held | weak | inline_mutate |
| classification_qoq_stabilization / deterministic_restore | override minority class flips; reapply keyword rules | classification | weak | inline_mutate |
| **pct_of_net_assets_recalc** | recompute pct = FV/net_assets when sum>200% | pct_of_net_assets | **tight** | inline_mutate |
| **universe_gate** | drop CIKs absent from combined_universe | cik | **tight** | **blocking (removes rows)** |
| **fund_strategy_asset_class_override** / re_fund_gics_remap | RE-strategy asset_class / GICS remap | asset_class,gics | tight/weak | inline_mutate |
| wrapper_position_key_override / duplicate_lot_suffix | per-CIK key curation | position_key | weak | inline_mutate |
| **manual_row_corrections** | audited per-row field patches | 14 fields | **tight** | inline_mutate |
| unclassified_cache_reclassify | agent-reviewed class on UNCLASSIFIED only | classification | weak | inline_mutate |
| cusip_placeholder_nulling / equity_principal_nulling / lien_gated_to_dl | null placeholder/irrelevant fields | cusip,principal,lien | weak | inline_mutate |
| schema_enforcement_checks | ~25 enum/range/relational assertions | many | weak | advisory (non-fatal log) |

### bdc_filings.py
| id | does | tier | enforcement |
|---|---|---|---|
| mixed_decimals_monetary_normalization | rescale outlier-decimals monetary facts | weak | inline_mutate |
| **stepstone_2025q4_scale_correction** | ×1000 fix reconciled vs pct·net_assets | **tight** | inline_mutate |
| bdc_context_dedup_complete_row | merge dup contexts, flag conflicts | weak | inline_mutate |
| non_position_identifier_filter | drop non-position identifiers | weak | inline_mutate |

### index_returns.py
effective_rate_cap (50%), equity_shares_ratio_guard (5×), income_return_cap (25%q), total_return_outlier_guard (±), span_annualization, **index_min_fv_filter ($100k, blocking)**, **index_min_constituents_filter (10, blocking)** — all weak.

### position_matching.py
FV-ratio guards (100×/50×/5×), rate_scale_normalization (Tier-A), cusip/name multiplicity caps, strong/unique position-key gates — weak.
**Hard-gate vetoes (tight):** classification_flip_veto, instrument_subtype_continuity_veto; maturity_gap_veto (weak/range).
**Structural (tight):** cascade_exclusion, one_to_one_enforcement (Hungarian), position_id_date_uniqueness_guard, position_id_uniqueness_assertion (**raises**), match_overrides (audited).

---

## 8. Recommendations

1. **Graduate the whole list to a universal, read-only shadow runner**, tier-tagged
   as above. Because ~everything is already advisory, this is low-risk and gives
   the complete coverage map per CIK-quarter.
2. **Consolidate the duplicates.** The 12 GAV/FV implementations, the multiple
   subtotal-arithmetic and pct-sum and NAV-identity copies should become one
   canonical tight check each, run once, reused everywhere.
3. **Promotion queue (tight + advisory → enforced):** A01, A04/E01, E02, E04, E07,
   G02, H01, H05, wrapper fv_reconciliation, the source_reconciliation engine, V7,
   V10, PC02/03/08, R07, R10, IDX14, XS01/03/04/05/06, RI01-07, F10/11/12/17/20,
   nonaccrual aggregate/position/chart. Run universal, tighten tolerance, decide blocking.
4. **Measure the silent mutations.** cost_proxy_fill, shares/decimals normalization,
   classification stabilization, GICS remap, Tier-A rate normalization, the dedups —
   add before/after measured gates; these are the highest silent-corruption risk.
5. **Retire/repair checks on unreliable inputs:** highlights balance_sheet_identity,
   net_assets_equity, cross_total_assets — prefer the companyfacts F10/F11.
6. **Weak checks stay flags**, precision-tracked, feeding quality tiers — never
   silent gates. They are the only signal for non-anchorable columns (classification,
   maturity, lien) and the discovery tool for where new tight anchors are worth building.
