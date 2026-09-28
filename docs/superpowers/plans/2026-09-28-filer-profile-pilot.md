# Filer Profile Pilot Implementation Plan

Revision: 2026-09-28, aligned with spec v4. This replaces the v3 plan's
untested implementation templates. The pilot has not been implemented or run
by this revision. The owner's v3 scope and start rulings remain unchanged.

Revision v4.1 (2026-09-28): four integration corrections verified against the
repo (lease needs a pseudo-candidate; D1 has no profile input; decimal
canonicalisation; amendment policy lives in a script), the verified-facts
block restored from the v3 plan, and staged go/no-go checkpoints (spec 8).

## Staged delivery (spec section 8)

| Stage | Tasks | Stop-and-report deliverable |
|---|---|---|
| A | 1-3 | protection receipts, lease adapter, envelope tests, M3 with denominator and `insufficient_evidence` causes, measured cost |
| B | 4-8 | M1 (Q1; same-era only if spec 12 q4 admits evidence), M2, partition candidates, collector completeness per CIK |
| C | 9-11 | M4 per boundary (D1 labelled pinning), M5 with censoring and unassessable counts, runner |
| D | 12 | all eight CIKs, write-up, changelog |

Do not start a stage before the owner has read the previous stage's report.

## Goal and execution contract

Build the shadow measurement pilot for eight BDCs and report M1-M5 with
evidence, fixed denominators and explicit unavailable results. Implement the
tasks below; do not treat illustrative tests as proof that cached data passes.
Use the repository's proportional verification workflow. Agent delegation
requires the session's authorization; this plan does not require a fleet.

Spec: docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md (v4),
especially sections 2, 5, 6, 9 and 10.

- Work in .claude/worktrees/filer-profile-pilot on filer-profile-pilot.
  No edits or branch switches in the sealed main checkout; no pipeline/
  edits in either checkout. Read-only commands against main are permitted.
- Reads of cached XML and outputs use an explicit resolved data root.
  Tracked configuration comes from the pinned pilot worktree.
- Measurement artifacts, isolated stage outputs and verification logs live
  under <data_root>/pilot/filer_profile/<run_id>/. The shared programme lock
  is the sole coordination-file exception; it is not a measurement output.
- No network, model calls, SEC downloads, production adoption, baseline
  refresh, registry changes, wrapper promotion or public export.
- Never widen a threshold or ignore unavailable evidence to improve a metric.
  Unsupported integration is an explicit result, not an approximate pass.
- No large pandas row loops. Use DuckDB for holdings scans and joins; bounded
  XML iteration is source parsing. ASCII-only logs.
- The primary experiment uses the spec's two quarters per CIK. Same-era M1,
  out-of-scope M3 evidence and fixed-Q1 all-quarter M5 scans remain included.
  Additional primary third/fourth-quarter experiments remain follow-on work.
- The last-rebuild ruling remains in force. Heavy pilot work waits for the
  shared programme lease; light work follows the spec's allowed scope.
- Commit completed implementation tasks with a short subject and concise
  body when executing this plan. Do not push or rebase during V13 closeout.

## Verified integration points and cautions

Inspect signatures in the pinned checkout before binding an adapter.

| Existing asset | Reuse | Boundary that must stay explicit |
|---|---|---|
| pipeline.context_inventory.scan_instance | inherited source-role diagnostics | retains target-quarter monetary facts; cannot be the complete census collector |
| pipeline.bdc_filings._parse_single_filing + _deduplicate_bdc_holdings | D1 production extraction | cache-only per-filing parse; takes NO profile parameters, so D1's profile side equals production and D1 is a pinning boundary (spec 6.4); preserve all source periods and dedup lineage |
| pipeline.explicit_contexts | inherited per-CIK identity mechanisms | rules can be period-scoped; do not assume one rule covers every quarter |
| pipeline.staging_bdc._prepare_bdc | D2 production staging | raw comparative corrections run while period still exists |
| pipeline.bdc_xbrl_wrapper loaders | isolated wrapper overlay | list inherited base fields and restore process state |
| pipeline.agent_promoted and correction appliers | ordered production replay | origin fidelity needs pre-correction rows, not already corrected public output |
| pipeline.unified_holdings | ordinary unified transformations and final row IDs | staging plus agent corrections alone is not this boundary |
| pipeline.rate_convention._aggregate_signals | existing S2 income signal | pin calculation/constants, input units, coverage and convention; no substitute yield formula |
| pipeline.programme.runner.heavy_lock(candidate) | existing shared lease protocol | context manager; psutil scan for pytest / rebuild_outputs.py / pipeline.programme.bootstrap, then `ROOT/data/programme/heavy.lock`; `candidate` MUST be a directory under the main checkout's `data/programme/candidates/`, so the adapter creates `pilot-filer-profile-<run_id>/` there (spec 2, 10); ROOT resolves from the importing module's file, so bind the main root explicitly |
| scripts/run_context_census.py | the only existing evidenced amendment / cover-only selection policy | it is a script, not a pipeline module; reuse by reference and pin its git blob hash in the manifest; unsettled cases are `unavailable` |
| tests/conftest.py | Python-write guard and native-IO inventory | its default protected roots are worktree-local |
| scripts/diff_outputs.py --semantic | required baseline backstop | execute against the actual main outputs; baseline divergence is separate from preservation |

Canonical names include principal_amount, maturity_date and shares_held.
Raw BDC rates are decimals; unified rate fields are percentages. Namespace
type does not identify numerical scale. A source context can carry multiple
conflicting facts; selecting the first one is not a resolution mechanism.
Source observation IDs are not cross-quarter position IDs.

## Facts verified against the repo on 2026-09-28 (do not re-derive)

- The worktree has NO `data/raw/` and NO `data/output/` (git-ignored). All
  cache and output reads resolve to the main checkout's `data/` through an
  explicit data root. `data/overrides/` is tracked and present in the worktree.
- `pipeline.context_inventory.scan_instance(path, cik, quarter, *, max_bytes,
  max_contexts, max_facts, timeout_seconds) -> dict` keeps only contexts whose
  period equals `quarter` with at least one mapped or suspicious fact. Context
  dict keys: `context_id, period, period_kind, entity_cik, dimensions[{axis,
  axis_namespace, value, kind, member_namespace}], facts[{field, concept,
  fact_id, raw_text, value, value_status, unit_ref, unit_measures, currency,
  decimals}], unknown_concepts, extractor_recognized, role, role_reason`.
  Result keys include `contexts, counts, document_period_ends, source_complete,
  errors, sha256`. `classify_context` imports `explicit_member_dimensions`
  from `pipeline.explicit_contexts` (inherited per-CIK identity code).
- `bdc_holdings.csv` columns: `period, investment_identifier, industry,
  investment_type, affiliation, dimensions_raw, acquisition_date,
  basis_spread, cost, face_amount, fair_value, interest_rate,
  interest_rate_floor, maturity_date, pct_of_net_assets, pik_rate,
  principal_amount, realized_gain_loss, reference_rate_type, shares_held,
  unrealized_gain_loss, fair_value_unit, cost_unit, principal_amount_unit,
  interest_rate_concept, src_facts, nonaccrual_footnote, nonaccrual_dimension,
  cik, entity_name, accession_number, form_type, filing_date, report_date,
  dedupe_context_count, dedupe_conflict_fields, dedupe_filled_fields,
  dedupe_axis_split, src_context_id`. NO `row_id`, NO `issuer_name`. Rates
  are decimals.
- `private_markets_holdings.csv` carries `source, cik, accession_number,
  report_date, issuer_name, fair_value, bdc_investment_identifier,
  bdc_dimensions_raw, src_context_id, corrected_fields, is_subsidiary, row_id,
  position_id, index_classification, interest_rate, pik_rate` among others.
  Rates are percentages.
- `bdc_filings_index.csv` columns: `cik, entity_name, accession_number,
  form_type, filing_date, report_date, primary_document,
  xbrl_download_status, xbrl_local_path`. Cache layout
  `data/raw/filings/bdc_xbrl/{cik_stripped}/{accession_no_dashes}.xml`. All 16
  primary fund-quarters had `xbrl_download_status == cached` on 2026-09-28.
- `bdc_fund_income.csv` columns: `cik, entity_name, report_quarter,
  report_date, form_type, accession_number, start_date, end_date,
  duration_months, total_investment_income, interest_income, dividend_income,
  fee_income, other_income, net_investment_income, management_fee,
  incentive_fee, interest_expense, total_expenses`.
- Wrapper v3 JSON top-level keys: `schema_version, cik, entity_name, version,
  source, dispatch{rule_prefix, prefix_rules, leaf_markers_by_family,
  aggregate_markers, non_private_markers, fallback_family_patterns, ...},
  staging{strategy, ...}, identifier_format{delimiter, field_order,
  alternate_delimiters}, archetypes, invariants{fv_reconciliation,
  position_count_qoq, rate_sanity, unclassified_rate}, known_edge_cases[{id,
  description, first_seen_quarter, detection_pattern, disposition}]`, plus
  optional `segment_assertions`, `source_encodings`. No authoring accession.
  Loaders: `bdc_xbrl_wrapper._load_specs_from_json(directory)`,
  `reload_wrapper_specs(override_dir)` (overlays; no-arg restores);
  `staging_bdc._WRAPPER_DEFINITIONS_DIR` is read by `_load_staging_configs()`
  inside `_prepare_bdc`.
- Pilot wrapper first-commit dates: Ares, Fidelity 2026-06-01; BCRED, Stellus
  2026-06-04; Stepstone 2026-06-06; NexPoint, TCW, Onex 2026-06-11.
- Corrections: B2 leaves `data/overrides/agent_b2_corrections/{cik10}/
  {fix_class}.json` (`cik, mechanism, fix_class, scope{quarters} |
  template{report_date}, template, evidence_citations, confidence`);
  investigate rules `data/overrides/agent_investigate_rules/{cik_stripped}/
  {rule_id}.json` (`cik, rule_id, rule_type in {row_exclusion, row_add, dedup,
  value_rescale, value_expression}, action, scope{quarters}, predicate_sql |
  positions, evidence`). `_`-prefixed dirs and `.proposed.` names are not
  live. No `admission_manifest.json` exists, so `rule_admission.admitted`
  returns `allow_legacy=True` for every live file.
  `agent_promoted.load_promoted_corrections(dir) -> list[dict]`,
  `load_promoted_rules(dir) -> dict[cik10, list[dict]]`,
  `apply_promoted_plan(combined, corrections, rules_by_cik) -> (frame, audits)`,
  `apply_raw_staging_exclusions(con, exclusions)` (staging stage).
- `agent_rule._match_rows(work, predicate_sql, scope)` and
  `match_rows_outside_scope(work, predicate_sql, scope)` need `_rid` and
  `report_date` columns; `_REPORT_DATE_KEY = "substr(CAST(report_date AS
  VARCHAR), 1, 10)"`.
- Anchors: `data/overrides/agent_anchor/{cik_stripped}/{report_date}.json`
  with `grand_total, method, components[{label, value, source}], evidence,
  rationale, companyfacts_fv`.
- Rate grammars: `data/overrides/identifier_rate_grammars/{cik10}.json`
  (`extractors[{field, regex, group, type, map}], required_fields,
  invariants`); `identifier_rate.load_grammar(cik10)`,
  `apply_grammar(identifier, grammar)`, `evaluate_invariants(parsed, twins,
  grammar)`. 70 CIKs have one.
- `staging_bdc._prepare_bdc(bdc_df=None, bdc_file=None, raw_exclusions=None,
  raw_exclusion_audits=None) -> pd.DataFrame`.
- `unified_holdings.build_unified_holdings(bdc_df=None, nport_df=None, *,
  output_file=None, orphan_file=None, agent_rules_dir=None,
  b2_corrections_dir=None) -> pd.DataFrame`; `row_id` is appended by
  `_assign_row_ids` as the last step. Reads other inputs from disk when frames
  are not supplied; the conftest isolates the agent query and GICS label
  caches for tests only.
- `rate_convention._aggregate_signals(holdings, income) -> pd.DataFrame`
  computes S1-S4 (including the S2 income signal) per CIK over two frames.
- `programme/runner.heavy_lock(candidate)`: see the integration table.
- `tests/conftest.py`: autouse `_isolate_promoted_agent_stores` redirects
  `config.AGENT_*_DIR` (loaders with explicit dirs bypass it);
  `needs_cache` and `use_real_promoted_stores` markers are registered in
  `pytest.ini`; the write guard and native-IO inventory protect the
  importing checkout's `data/output/` and `frontend/public/data/` only.
- Synthetic instance helpers pattern: `tests/test_context_inventory.py`
  (HEADER, `context()`, `typed()`, `explicit()`, `fact()`).
- Tests import scripts as `from scripts.profile_pilot import ...`
  (`scripts/` is a namespace package; sub-packages carry `__init__.py`).
- DuckDB 1.4.3, jsonschema 4.24, lxml and psutil are installed.

## Files and artifacts

All new code is under scripts/profile_pilot/, with focused
tests/test_profile_pilot_*.py files. Task 1 also adds an explicitly loaded
pytest protection plugin in that package; it does not modify shared conftest.

| Module | Responsibility |
|---|---|
| paths.py, cohort.py, manifest.py | explicit paths, accession selection, frozen run dependencies |
| protection.py, pytest_plugin.py, verify.py | actual-root protection, shared lease and verification receipts |
| envelope.py, schemas/filer_profile_v0.schema.json | append-only assertions/retractions, two clocks, applicability |
| graduate.py | correction translation, exact origin fidelity, per-row evidence and M3 |
| census.py, schemas/census_v0.schema.json | complete bounded source collection and structural detectors |
| profile.py | Q1/same-era derivation, fixed wrapper-key comparisons and M1 |
| translate.py | profile-to-wrapper adapter and inherited/not-expressible accounting |
| contracts.py | partitioned Q1 expectations, Q2 evaluation and M2 |
| interpret.py, parity.py | connected D1-D3 execution and exact comparison |
| halflife.py | fixed-contract history, observation completeness and M5 |
| report.py, run.py | dependency-aware CLI, complete result accounting and write-up |

Within one run, retain manifest.json, inventories/, census/, profiles/,
contracts/, parity/, graduation/, halflife/, verification/ and results/.
Each result links its run manifest, source/config hashes and producing code
identity. A summary never merges files from different runs or versions.

## Task 1: Paths, frozen inputs and protection of real artifacts

Interfaces: PilotPaths with main_repo_root, code_root, data_root, run_root
and resolved protected_roots; fund_quarters; build_manifest; verify_inputs;
protected_session; shared_heavy_lease; guarded pytest/backstop launcher.

- [ ] Resolve explicit paths first and reject invalid supplied paths rather
  than falling back to another dataset. Confine every pilot output to the
  resolved run root, including symlink/junction resolution. Overrides are
  read from code_root and identified by content hash.
- [ ] Retain the eight CIKs and primary quarters from spec section 5. Pin
  each selected accession, form, filing date and source hash. Do not infer
  form from month or select the last filing automatically. The pipeline has
  no amendment-selection policy; reuse the evidenced policy in
  `scripts/run_context_census.py` by reference (read its selection rules,
  pin its git blob hash in the manifest, do not copy-edit it). Ambiguous
  selection is unavailable evidence with all candidates listed.
- [ ] Pin the exact wrapper version and evidenced authoring accession for
  same-era M1. A git add date is supporting metadata only. If the source
  quarter is unknown, record unavailable without selecting a convenient date.
- [ ] Freeze all inputs actually used: holdings, index, income, XML,
  wrappers, grammars, corrections, anchors/basis metadata, source mappings,
  tolerances and relevant code/schema versions. Record git HEAD plus a dirty
  source digest. Verify hashes before and after each stage; changed inputs
  invalidate that stage. Materialise boundary frames in the isolated run.
- [ ] Fix wrapper-key, correction, primary-quarter and contract inventories
  before their evaluations. Record empty/missing inputs explicitly. Cache
  identity includes all dependencies and completeness, not just XML hash.
- [ ] Protect BOTH the main data_root/output and main frontend/public/data
  and the worktree equivalents. Install the pytest plugin before collection
  imports pipeline code. Extend the existing guard roots without replacing
  them and snapshot native-IO artifacts before/after even on test failure.
  Ordinary execution uses equivalent preservation checks. Cache-backed
  tests write artifacts to temporary pilot roots, not prior measured runs.
- [ ] Invoke the existing semantic diff script in a read-only subprocess
  with main_repo_root as working directory after each pytest invocation.
  Capture command, exit code and logs under verification/. Do not refresh
  the baseline. Report pre-existing differences separately; any newly
  changed protected artifact or failed inspection fails preservation.
- [ ] Use the main programme lease, not a second lock in the worktree.
  The lease is `pipeline.programme.runner.heavy_lock(candidate)`; `ROOT`
  in that module resolves from its own file, so the adapter must bind the
  MAIN checkout root (import the module, then patch or pass the root the
  way its `contained()` helper expects; inspect before binding). `candidate`
  must be a directory under the main checkout's `data/programme/candidates/`;
  create `pilot-filer-profile-<run_id>/` there containing only `pilot.json`
  (run id, pilot root, git HEAD). Never create `attempts/` or `frozen/`
  under it. Acquire the lease exclusively for the whole heavy operation,
  with psutil discovery failures propagated as refusals. Retain the
  existing stale-lock and worker-telemetry protections. Heavy work runs in
  the owning process; no detached workers. The lock file and the
  pseudo-candidate directory are the only writes outside the pilot run root
  (spec 2). Remove the pseudo-candidate directory on clean release; leave it
  in place on failure for inspection.
- [ ] Test explicit-path rejection, output escape/junction rejection,
  populated primary plus cover-only amendment, ambiguous amendments,
  input changes during a run, collector-version cache invalidation, and
  missing historical wrapper evidence. Test protection against a separate
  fake main root while worktree outputs are empty, including native writes.
  Test an occupied lease, concurrent acquisition, discovery errors,
  exception cleanup and a stage that triggers heavy work through a cache miss.
- [ ] Run the focused path/protection tests and mandatory backstop through
  the launcher. Do not proceed to cache-backed measurement until the actual
  protected roots and coordination path are recorded and verified.

No --allow-heavy bypass. Inability to inspect or acquire the shared lease
blocks heavy work; it never becomes an empty running-process list.

## Task 2: Immutable temporal history and executable applicability

Interfaces: make_assertion, append_correction, append_change,
materialize_entries, validate_profile, resolve_for_row. The schema stores
immutable assertions and timestamped retractions; entry envelopes expose
recorded_until as a materialized view. All intervals are half-open.

- [ ] Implement retrospective correction at transaction time T by retracting
  the old assertion at T and appending a replacement with the same valid
  interval. Require new evidence; retain old evidence and value unchanged.
- [ ] Implement an effective change at Q, learned at T, by retracting the
  old unbounded assertion at T and appending two assertions: the old value
  on [old_from, Q), and the new value on [Q, old_to). Preserve finite ends.
  Queries before T must still see the original unsplit assertion.
- [ ] Generate unique assertion/event IDs across partitions, forms and
  versions. Reject invalid event references, non-monotonic transaction
  bounds, empty/reversed valid intervals and changes outside the old interval.
  Do not use calendar-day subtraction to express a quarter boundary.
- [ ] Evaluate a restricted structural predicate vocabulary against raw
  rows: axis/member QName, carrying concept, segment count, prefix and
  supported grammar dialect. Row ordinals and context lists are evidence,
  not reusable applicability predicates.
- [ ] Apply matching partition rules before null-partition fallbacks, then
  exact form before all-form fallback. Equally specific matches are errors.
  Check selection overlap, including predicates with different JSON shapes.
  Unknown predicates cannot silently return no match. Validate historical
  transaction slices as well as current entries.
- [ ] Test old and new beliefs before/at/after T for BOTH correction and
  genuine change, effective boundary Q, finite intervals, correction after
  change, duplicate IDs, reordered events and input immutability.
- [ ] Test two disjoint mixed-format partitions, default fallback,
  form-specific precedence, overlapping prefix/axis selectors and ambiguous
  matches. A test proving only correction history is insufficient.
- [ ] Run focused envelope tests and the backstop. Keep this a pure
  validator/resolver, not a new database service.

## Task 3: Graduation [E] first, with exact origin fidelity

Interfaces: correction_inventory; express_candidate; materialize_origin;
compare_effects; gather_witnesses; classify; run_graduation.

- [ ] Read the production-admitted correction inventory with explicit
  directories and hashes. Exclude retired/proposed artifacts using the
  existing loader contract. Freeze all live items in the M3 denominator.
- [ ] Translate only mechanisms with a defined structural representation.
  Separate effective scope from the predicate through a supported parser/
  template; never remove date strings with replacement heuristics. Preserve
  original null semantics, per-CIK restrictions and action type.
- [ ] Reconstruct the actual pre-correction origin frame and preceding
  correction order using pinned cached inputs and production functions.
  Compare original and candidate source-row MULTISETS and action/value
  effects on every origin quarter. Non-empty intersection is insufficient.
  Missing pre-correction evidence is insufficient_evidence; a demonstrated
  difference is not_expressible.
- [ ] Comparative declarations describe the current/prior-period views;
  they do not delete legitimate historical facts from the knowledge store.
  Test null/empty periods against the actual original applier.
- [ ] Evaluate out-of-scope quarters at the same stage. For each selected
  source observation require a mechanism-specific witness: exact economic
  date, a documented subtotal hierarchy, or a same-position alternate view
  with a retained counterpart. Include zero-FV observations and preserve
  position/tranche grain. Raw row keys, currencies and scope are retained.
- [ ] Independently require the existing gate's anchor basis and band,
  including cash, subsidiary and JV membership. Load the full anchor
  contract, not just grand_total. Never introduce a universal 1% band.
- [ ] generalises requires origin fidelity plus at least two supported
  out-of-scope quarters AND support for every touched quarter. Any known
  counterexample is conflicts. Any unassessed touched quarter, missing
  witness or scope mismatch is insufficient_evidence. No eligible holdout,
  including an all-quarters rule, is insufficient_evidence.
  quarter_bound requires actual assessed holdouts with no selected rows.
- [ ] Test partial origin overlap, already-deleted origin rows, null
  periods, an embedded date selector, two supported plus one unknown quarter,
  scope/currency mismatch, zero-FV wrong deletion, equal-FV distinct tranches
  and offsetting errors that improve the aggregate. Add positive witness-
  backed comparative and duplicate-view cases.
- [ ] Run focused tests/backstop, then the light M3 stage. Record unsupported
  candidates honestly; lack of new collectors is not permission to replace
  row witnesses with aggregate totals. If origin reconstruction or witness
  collection triggers heavy work, acquire the lease or leave it pending.

## Task 4: Complete bounded census collection

Interfaces: collect_instance; collect_facts; collect_text_and_footnotes;
classify_with_dependencies; detect_structure; validate_census.

- [ ] Parse each cached instance once with DTD/entity expansion and network
  access disabled, explicit byte/context/fact/text/time bounds and a source
  hash before/after. Enumerate instant AND duration contexts directly,
  including all comparative dates. DocumentPeriodEndDate is filing metadata.
- [ ] Retain each fact's source QName, context ID, raw and typed values,
  nil/invalid status, unit/currency, decimals, date/duration, dimensions and
  document identity. Preserve text/date/boolean facts and linked footnote
  resources, not only numeric investment concepts. Missing channels and
  truncated/incomplete collection invalidate absence claims.
- [ ] Map monetary, rate/spread/PIK, maturity, shares, industry/affiliation,
  status and fund-income fields using canonical names consistently. Record
  imported concept/role mappings as inherited dependencies. Retain unknown
  facts and unresolved contexts outside the recognised-position subset.
- [ ] Keep conflicting same-field facts as conflicts. Do not take the first
  or largest value. Decimal/currency equality is required for numerical
  comparisons; reported units and rounding metadata remain available.
- [ ] Derive subtotal candidates from demonstrated structural parent/child
  relationships on the same entity/date/currency/scope basis, plus heading
  evidence. No arbitrary subset-sum search. A borrower named Total Safety
  is a negative control, not a subtotal marker.
- [ ] Derive alternate-view candidates from same-position/tranche evidence,
  accounting scope and the differing presentation axis. Matching borrower,
  instrument type or balances alone is insufficient. Do not select a
  canonical view by context order or number of dimensions.
- [ ] Inspect concepts, identifiers, text and linked footnotes before
  reporting not_observed_in_complete_instance. Never claim full-filing
  non-disclosure from XBRL absence. Unsupported channels remain unresolved.
- [ ] Collect delimiter/segment modes and search structural discriminators
  learned from Q1. A second delimiter may be punctuation inside a borrower,
  not another dialect. Emit evidenced disjoint partition predicates or
  unresolved candidates; never generate row-range partitions.
- [ ] Test comparative contexts when DocumentPeriodEndDate contains only
  the current date; raw rate/spread/date/text/footnote and income facts;
  nil versus absent versus invalid; conflicting units; partial parsing;
  same-value distinct tranches/scopes; labelled coincidental sums; and
  true/false mixed-format partitions. Include positive, false-positive and
  insufficient-evidence controls for each detector.
- [ ] Run focused synthetic tests and backstop. Collector completeness is
  explicit in JSON and propagated to every dependent metric.

## Task 5: Cached-source validation and bounded performance

- [ ] Run source-pinned Stellus and NexPoint fixtures plus Fidelity as the
  low-history case. Verify actual identity axes and economic periods from
  XML; do not force expectations from the cohort table. Per-CIK explicit
  identity rules may apply only to earlier periods.
- [ ] Cross-check collected rates, comparative contexts and one text/
  footnote fact against identified raw source facts, not just row counts.
- [ ] Measure wall time and peak memory: the 1,000-position target is under
  60 seconds and 2 GiB. Bounded timeout/incomplete results are failures to
  assess, not complete censuses with fewer positions. Do not silently waive
  limits or parallelise around the shared lease.
- [ ] Cache only complete results keyed by source, collector/schema version,
  code digest and configuration dependencies. Force regeneration after any
  dependency change. Preserve failed run receipts separately.
- [ ] Run cache tests through the actual-root protection launcher and
  semantic backstop; record counts and limits actually measured.

## Task 6: Profile derivation and faithful M1 scoring

Interfaces: derive_profile; wrapper_key_inventory; canonical_value;
compare_to_wrapper; write_profile.

- [ ] Freeze the comparison keys and supported comparison semantics before
  census runs. Generate profiles without access to the comparison wrapper.
  Existing grammars/identity rules remain explicitly inherited.
- [ ] Create entries only from resolved evidence. Each carries its source
  dependency IDs, measured support, form, partition and two clocks.
  Incomplete collection blocks entries that depend on the missing channel.
  Unsupported profile sections become packet stubs.
- [ ] M1 exact means independently derived executable value equals the
  wrapper's complete value under a predeclared representation. Prefixes
  without their family mapping are not exact; a visible fund total does not
  reproduce an invariant's field, basis and tolerance. Compare both missing
  and extra values, with list order significant wherever behavior uses it.
- [ ] Distinguish exact, partial, inherited, unresolved, miss and
  not_derivable using the fixed denominator. A comparison or derivation
  omitted by this implementation is unresolved/not_implemented. It does
  not establish that the knowledge is inherently non-derivable.
- [ ] Record Q1 and same-era M1 in separately keyed results with their
  respective wrapper/source versions. Write profiles/{cik}/q1.json and
  profiles/{cik}/same_era.json. No wildcard scan may overwrite one with the
  other. Missing authoring evidence stays explicit.
- [ ] Test identical prefix sets with different mappings, wrong tolerance
  with the right anchor field, extra aggregate markers, inherited equality,
  unsupported key comparison, unresolved selectors and same-era separation.
- [ ] Run focused tests/backstop, then profile both evidenced eras for the
  light CIKs. Publish no claim of verified correctness from M1.

## Task 7: Profile-to-wrapper adapter

Interfaces: to_wrapper_v3(profile, base_wrapper, report_date, form_type);
write_overlay; restored_wrapper_context.

- [ ] Translate only sections the production wrapper schema can express.
  Resolve dates/forms/partitions using Task 2. If the wrapper cannot express
  a mixed partition or a presentation-view declaration, record
  not_expressible; do not flatten or drop it.
- [ ] Preserve unsupported base fields only as an explicit inherited
  overlay, listing each retained field and its hash. Report profile-driven
  coverage beside parity so a mostly copied wrapper cannot look like full
  replacement. Keep pilot metadata in a sidecar, not unknown schema keys.
- [ ] Scope loader changes to one isolated process/context and restore them
  even on failure. Direct every generated file to the run root.
- [ ] Test production schema/loader admission, inherited-field accounting,
  form/partition non-expressibility, unknown keys and restoration on errors.
- [ ] Run focused tests and backstop.

## Task 8: Partitioned contracts, scale and M2

Interfaces: learn_contracts; freeze_contracts; evaluate_contracts;
load_income_evidence. M2 and M5 consume the same frozen contract artifact.

- [ ] Learn source, fill, scale, format and range expectations from Q1
  within its evidenced partitions. Evaluate those fixed predicates on Q2
  before computing every statistic. Do not choose new partitions using Q2
  answers. Unresolved mixed formats are insufficient_evidence.
- [ ] Define scale using units plus a deterministic raw-to-canonical
  conversion supported by the source/declared convention. Namespace and
  magnitude alone are not scale evidence. Decimal, percent and basis-point
  examples using the same concept must be distinguished, or abstained on.
- [ ] Format grammar names the field and dialect and records violating
  source keys. Delimiter counts alone establish only identifier structure.
  Existing authored grammar use is inherited, with its hash pinned.
- [ ] Reuse the existing S2 income calculation through explicit input
  frames and versioned constants. Prove units, duration, scope, currency,
  principal/rated coverage and cash/all-in meaning before interpretation.
  Preserve tagged versus estimated income evidence. Unknown convention,
  inadequate coverage or unavailable S2 granularity is insufficient_evidence,
  not a new simplified FV-weighted rate formula.
- [ ] Freeze tolerances from spec 6.3 before evaluating Q2. Evaluation reads
  the frozen file, not a divergent in-code dictionary. Form qualifiers must
  already be evidenced; a 10-Q/10-K change is not automatic extra tolerance.
- [ ] Retain every expected contract in the denominator with holds,
  holds_with_form_type, breach or insufficient_evidence. Distinguish an
  observed missing field in a complete source from inability to observe it.
- [ ] Test true decimal/percent/bps changes within one namespace, namespace
  change with unchanged scale, two valid dialect partitions, ambiguous
  partition overlap, low-history bands, unapproved form relief, source
  incompleteness, absent versus zero fields, cash/all-in double-PIK controls,
  duration mismatch and insufficient rated-book coverage.
- [ ] Run focused tests/backstop and light Q1/Q2 evaluation.

## Task 9: Connected D1-D3 compatibility parity

Interfaces: run_extraction; run_staging; run_unified;
compare_typed_multisets; run_parity. Each boundary stores its complete frame,
input identities, lineage and inherited/unexpressible mechanisms.

- [ ] D1 uses the existing cache-only production parser
  (`bdc_filings._parse_single_filing` then `_deduplicate_bdc_holdings`) with
  explicit inherited mechanisms. The parser takes NO profile parameters, so
  the profile side equals production: D1 is a pinning boundary (spec 6.4),
  expected exact unless the pinned accession, cached instance or parser
  version differs from what built `bdc_holdings.csv`. Label it so in every
  result and in M4. Preserve all source periods and the extractor's dedup
  lineage. Compare to the selected pinned accession slice; do not
  reconstruct extraction from census role labels. Profile effects are first
  measurable at D2.
- [ ] D2 consumes the ACTUAL D1 frame. Independently materialise the
  reference staged frame from the pinned production raw slice. Run raw
  comparative selectors while period exists. Do not remove subtotals/views
  in D1 as a substitute for their true production-stage handling.
- [ ] D3 consumes the ACTUAL D2 frame through ordinary unified logic,
  including scope, classification, normalization, correction ordering and
  final ID assignment. Produce with-corrections and without-corrections
  branches from otherwise identical inputs. Use source keys and independently
  generated IDs; never join reference row IDs onto pilot rows.
- [ ] Invoke existing functions through an isolated adapter only after
  proving every write goes to the run root. Pin all supplementary inputs.
  If a safe exact integration cannot be invoked without a pipeline change,
  return an explicit integration-gap result, not approximate D3 success.
- [ ] Replay corrections at their own stage, including additions and
  all-quarter scopes, recording selected source-row multisets and effects.
  A D3 gap can also arise from ordinary unified logic or source-version
  mismatch; do not automatically attribute every gap to corrections.
- [ ] Compare typed ROW MULTISETS, not key sets. Duplicate, null and empty
  keys are reported and prevent exactness. Require exact per-row decimal FV,
  null/zero distinction and currency plus exact aggregate FV. No tolerance,
  rounding or many-to-many merge acceptance. Canonicalise BOTH sides the same
  way (spec 6.4): read reference CSV columns as VARCHAR (DuckDB
  `all_varchar=true`, never float inference), convert text with
  `decimal.Decimal(text).normalize()`, and convert pilot-side numeric output
  with `Decimal(str(value)).normalize()`; `0` and null stay distinct; a value
  that fails to parse on either side is `unkeyed/ambiguous`. Record the
  canonicalisation function name and version in the parity result.
  Report all other contracted column agreements separately.
- [ ] Test an upstream extraction difference propagating to D2/D3, extra
  zero-FV duplicates, offsetting per-row FV errors, sub-dollar differences,
  null versus zero, colliding source keys, legitimate comparative rows,
  raw-stage exclusion, classification, row additions and independent IDs.
  Compare two identical frames as the positive control.
- [ ] Run focused tests/backstop, then protected light-CIK parity. Keep all
  16 primary fund-quarters in the report, including unassessable boundaries.

## Task 10: M5 with real elapsed time and observation completeness

- [ ] Load the exact frozen Q1 contracts from M2, including range and
  partition expectations. Group by the declared profile section/partition
  unit before estimating survival; report constituent checks separately.
- [ ] Compute elapsed quarters from reporting dates and the pinned fund
  calendar. Missing cached filings do not compress elapsed time. Annual
  facts alone are not proof of quarterly observations.
- [ ] At each scheduled quarter, a section is assessably passing only when
  all its required checks can be evaluated and hold. A known breach is an
  event. Missing/insufficient evidence censors at the last continuously
  passing quarter; later observations remain diagnostics outside that
  survival observation. Never-assessable sections have a separate count.
- [ ] Estimate Kaplan-Meier from those event/censor observations. Report
  risk sets and the median only if survival reaches 0.5, otherwise not
  reached. Do not use the raw percentage of events as the median criterion.
  Explicitly state the correlated repeated-measurement limitation.
- [ ] Record coincidence with form changes and known events as descriptive
  labels, never causal proof or evidence of later-profile stability.
- [ ] Test a missing calendar quarter, always-unassessable contract,
  passing/unknown/later-breach sequence, value-range contract preservation,
  tied censor/event times, median reached after early censoring and median
  not reached. Verify both per-CIK and cohort aggregation.
- [ ] Run focused tests/backstop. Execute history scans only under the lease.

## Task 11: Dependency-aware runner and truthful summary

- [ ] Implement CLI stages manifest, graduate, census, profile, contracts,
  parity, halflife and summary, plus dependency-aware all. Accept --cik,
  --data-root, --run-id, --quarters first2|all and explicit output confined
  to the pilot root. Primary M2/M4 remain first2; all adds M5 observations,
  not a changed primary denominator.
- [ ] Check the shared lease at the operation that can trigger heavy work,
  not only at a top-level stage name. Profile/contracts/parity and cache
  misses cannot bypass census protection. Do not offer --allow-heavy.
- [ ] Check run identity and input hashes when loading any result. Do not
  reuse failed/incomplete results or silently overwrite frozen inventories.
  A changed dependency creates a new run/version with lineage.
- [ ] Assemble M1 by CIK AND era, M2 by frozen contract identity, M3 by
  frozen correction identity, M4 by all 16 primary quarters and boundary,
  M5 by the declared section/partition observation unit. Missing files
  yield explicit not_run/unassessable results, not smaller denominators.
- [ ] Require negative controls proving the summary cannot claim success
  for stale results, missing quarters or mis-keyed same-era artifacts.
  Keep machine-readable detailed findings available beside concise tables.
- [ ] Test ignored/unsupported CLI options, stale dependencies, skipped
  stages, absent artifacts, mixed run IDs, same-era isolation and failures
  before/during a nested heavy call.
- [ ] Run focused runner/report tests and backstop. Do not describe the
  implementation as covered until its adversarial acceptance cases pass.

## Task 12: Execute, preserve evidence and report

- [ ] Run the protected synthetic suite first. Use the verification launcher
  so actual-root protection and the semantic backstop run even on failure.
  Check for other long-running tests before a broad test job.
- [ ] Freeze inventories and run light M3, then light-CIK census/profile/
  contract/parity stages. Report any missing integration/evidence before
  spending time on the heavy stages.
- [ ] After the V13 lease is released, acquire it for Ares/BCRED and M5.
  Do not infer release from elapsed time or swallow process-inspection
  errors. Record measured runtime and memory against the declared bounds.
- [ ] Validate the 16-quarter primary ledger and all metric denominators.
  Source failures and compatibility divergences remain findings; they are
  not instructions to edit production data, widen filters or suppress checks.
- [ ] Run the complete pilot suite through the launcher, with cache cases
  identified. A claim of completion requires protection of the REAL output
  roots and the mandatory main-checkout semantic diff receipt. Empty
  worktree output directories are irrelevant to that check.
- [ ] Append the investigation to docs/investigations/filer_profile_pilot.md,
  then run the existing reindex script in the pilot worktree. Include the
  five metrics, explicit missing evidence, source-version divergences,
  actual profile-driven/inherited coverage and the decision-table reading.
- [ ] Append docs/agent_changelog.md with files/contracts changed, measured
  test and data counts, run manifest, preservation result and semantic
  backstop result. Report what was not run. Do not invent pass counts.
- [ ] Commit the implementation/results documentation with concise subject
  and body. Do not push, rebase, promote or write the migration spec here.

## Review closure checklist

| Review issue | Required evidence before reporting the metric |
|---|---|
| Incomplete census | source-pinned non-monetary, comparative and footnote fixtures plus completeness states (Tasks 4-5) |
| Fake scale / missing partitions | unit conversion and mixed-format positive/negative controls (Tasks 2, 8) |
| Weak graduation | exact origin effects and every touched row's witness/basis, including unknown quarters (Task 3) |
| Disconnected parity | actual D1-to-D2-to-D3 lineage and strict multiset/decimal controls (Task 9) |
| Rewritten temporal history | historical as-of tests for change AND correction, with immutable assertions (Task 2) |
| Misleading M1/M5 | executable-value comparisons, calendar time, unassessable observations and fixed summaries (Tasks 6, 10-11) |
| Empty-worktree protection loophole | actual-root write/native guards, shared lease and semantic backstop receipts (Tasks 1, 12) |

These are implementation acceptance requirements, not claims that the pilot
or source data has passed them.
