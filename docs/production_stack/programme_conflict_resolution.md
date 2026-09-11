# Programme conflict resolution and validation trace

Date: 2026-09-09. Status: engineering resolutions specified; implementation and
acceptance are pending. All D01-D13 owner decisions remain closed.

This connects the twelve findings in the
[holdings crosswalk](../reference/unified_holdings_contract_crosswalk.md) to
their current writers, checks, consumers and required changes. It supplements the
[target contract](programme_target_contract.md) and
[measurement register](programme_measurement_register.md). Existing tests are
evidence of implemented behaviour, not automatic authority for the target meaning.

No production code, rules, thresholds, data, baseline or frontend payloads were
changed in preparing this document. Numerical tolerances still require measured
calibration under D12. The cache assessment accompanying this document measures
saved artifacts; it is not a synchronized rebuild or a source-accuracy benchmark.

## 1. What the trace establishes

The twelve findings need engineering work under the accepted choices. They do not
currently require twelve further owner decisions. The most consequential boundary
problems are:

- A spread override writes decimal fractions into a percentage-point field after
  staging normalization. Its isolated test uses the same decimal convention.
- B2 verification and production use different correction ordering.
- Unified schema checks log warnings before the final enrichment/key overlays;
  a successful write does not establish that the final artifact passed validation.
- Entity and position stages can rewrite the holdings CSV after its Parquet
  companion was written. A current CSV and an older companion are possible within
  an apparently successful workflow.
- A bridge file named `.proposed.json` is eligible for the HTML bridge loader.
  The filename is not an effective promotion boundary.

These are code-path findings. Saved-data measurements and limits are recorded in
[the assessment report](programme_contract_assessment_2026-09-09.md). A potential
interaction between rules is not proof that their selected rows overlap or that
they caused a particular published error.

## 2. Current execution order and target ownership

Order below is within `build_unified_holdings`, unless explicitly marked as an
upstream or subsequent CLI stage. Source line references refer to the code hashes
in the assessment input manifest, including local changes.

| Order | Current writer / selector | Current authority and dependency | Target treatment / findings |
|---|---|---|---|
| Upstream | `bdc_filings.py`, wrappers, cached extractor outputs | Extracted facts, unit IDs, contexts, dimension paths, extraction dedup and provenance | Retain source observations and rejected-fact dispositions. Resolve units from documents. F03/F09/F10. |
| S01 | `staging_bdc._prepare_bdc`, raw promoted comparative exclusions | Excludes scoped raw CIK/report-date rows before staging | Retain only evidenced comparative exclusions; legitimate prior-period facts remain eligible. F06/F10. |
| S02 | `_prepare_bdc`: scale correction, `no_amendments` CTE | Latest filing date/accession by CIK/report date/base form among accessions with extracted rows | Pin selection and record rejected candidates/coverage changes. F06. |
| S03 | Wrapper staging config, identifier parser, aggregate-header flags | CIK-specific normalization and roster rules before field output | Retain evidence-backed rules; expose scope and accounting disposition. F01/F07/F09/F10. |
| S04 | `_prepare_bdc` final SQL | Rate magnitude heuristics, currency token cleanup/FX join, maturity parsing, missing booleans to false | Replace incompatible field semantics; retain source interpretation evidence. F01/F03/F07/F08. |
| S05 | Static HTML bridge, then iXBRL field-status overlay | Matching source keys; applicable recovered maturity/reference/lien values; field-specific overwrite rules | Explicit accepted-input manifest and evidence keys; preserve overlay guards. F05/F07/F09. |
| S06 | `identifier_spread_corrections.apply_spread_corrections` | Exact CIK/date/normalized identifier; writes `new_value_decimal` directly after S04 | Convert once to declared output unit; literal disclosed spread must support correction. F01/F05. |
| U01 | Unified relational roster/dedup and classification | Dimension/name/instrument rules; shared BDC/N-PORT frame | Preserve position/lot grain and independent roster residuals; no borrower merge. F10/F12. |
| U02 | `with_cost`, `with_shares_fix` CTEs | Full-history first nonzero FV; issuer-level historical share-price anomaly repair | Move cost after identity; preserve reported zero. Share repair needs facility-safe scope. F02/F06/F12. |
| U03 | `_apply_universe_gate` | Existing exclusions and source/universe restrictions | Preserve shared pipeline scope; explicit public cohort and obligation records. F10. |
| U04 | Existing `entity_lookup` and industry lookup joins | Prior saved lookups; potential multiplicity if join key is not unique | Pin lookup version; require unique assignment or explicit unresolved state. F06/F11/F12. |
| U05 | `_stabilize_classification`, `_restore_deterministic_classification_rules` | History-wide class stabilization followed by deterministic restoration | Versioned classification decisions and dependencies, with explained temporal revisions. F06/F11. |
| U06 | `_correct_pct_of_net_assets` | Replaces selected percentages using saved fund NAV when sum exceeds 200% and decreases | Keep reported percentage; separate calculated ratio and denominator lineage. F04. |
| U07 | `_apply_row_corrections` | Exact composite key; CSV order; duplicate source matches can all change | Preserve narrow correction mechanism, require unique/evidenced selectors and explicit precedence. F05/F09. |
| U08 | `_apply_fund_strategy_corrections`, asset-class override | Prefer pinned candidates if present; otherwise live candidates; fund strategy source | Always bind selected input to candidate; keep fund strategy separate from borrower GICS. F06/F11. |
| U09 | `agent_promoted.apply_promoted_stage2_corrections` | CIK/BDC and quarter scope; alphabetical `fix_class` order; transient row IDs for selectors | One shared ordered execution plan with verifier; structural changes precede value changes. F01/F05/F10/F12. |
| U10 | `agent_promoted.apply_promoted_rules` | Layer C after B2; sorted filenames within CIK; scoped predicates and audits | Explicit dependencies and compatible semantics; deterministic order shared with evaluation. F05/F10. |
| U11 | `_enforce_schema` | Warns about violations; does not reject write; before U12-U15 | Retain early diagnostics, add final structural/semantic gate after all mutations. F05/F11. |
| U12 | `_apply_gics_cache`, `_apply_lien_cache` | Existing caches; lien loader is a no-op when its configured file is absent | Pin decision inputs; source/inference distinctions; validate final values. F05/F11. |
| U13 | `_apply_unclassified_cache` | Reviewed classifications on UNCLASSIFIED rows; separate JV flags | Keep applicability restrictions; consolidate classification ownership/evidence. F05/F10/F11. |
| U14 | `_apply_wrapper_position_keys`, duplicate lot suffixes | Wrapper keys override generic keys for position leaves | Preserve distinct lots; prove key stability under additions/corrections. F12. |
| U15 | `_apply_re_fund_gics_overrides` | Fund-strategy override of GICS following company cache | Make economic subject and final authority explicit; do not relabel fund strategy as borrower-source GICS. F11. |
| U16 | Application audit; `_assign_row_ids`; CSV then Parquet | Audit write condition checks raw exclusions or Layer C, omitting B2-only case; IDs assigned on final frame | Always record every enabled decision store; assemble compatible immutable bundle. F05/F12. |
| Later | `entity_resolution.build_entity_lookup` / `_enrich_holdings` | Can replace holdings CSV with new entity assignments after companion creation | Emit versioned assignments; finalizer owns canonical write. F06/F12. |
| Later | `position_matching` and CLI/rebuild return stages | Matches write companions, then position-ID stages rewrite CSVs; registry is opt-in | Stage candidate identity outputs and finalize once, including companions. F12. |
| Later | `index_returns.compute_returns` | Coupon-convention file, implied benchmark, filer median and PIK addition | Atomic all-in/no-inference migration with upstream rate semantics. F01/F02. |
| Later | PIK builders and frontend exporters | Run-local PIK row keys; independent reads of holdings and other saved artifacts | Durable joins and release-bound metrics; preserve current/terms distinction. F08/F12. |
| Later | Validation / quarter acceptance | Rebuild script can export before its final validation call; standalone export has no release gate | Produce candidate bundle, evaluate it, then mark ready for owner approval. F05/F10. |

The [correction instance ledger](programme_contract_evidence_2026-09-09/correction_instances.csv)
records path hashes, loader-path eligibility, selectors, scopes and payloads for
B2, Layer C, anchors and static bridges. The
[existing asset inventory](../reference/architecture_rule_assets.csv) also covers
wrappers, grammars and other stores. Neither file proves that every rule matched
rows or was applied successfully. Full runtime rule coverage still needs isolated
stage traces, including embedded global rules and row-level cache decisions.

The required target order is: pinned source/selection -> normalization and roster
accounting -> promoted corrections/enrichment -> entity/position assignments ->
identity-dependent cost and metric derivations -> final validation -> one complete
candidate artifact bundle. Independent fund financials must be ready before
calculations using NAV. No stage may quietly consume a previous run's output.

## 3. Resolutions of F01-F12

### F01: Coupon, spread units and downstream income

**Current trace.** BDC staging scales rates by magnitude, retains different
concept meanings in `interest_rate`, and can infer SOFR/LIBOR from spread/date.
The Agent A spread override then writes `new_value_decimal` without conversion;
the unified select does not normalize that field again. B2 all-PIK templates can
explicitly set `interest_rate` to the cash leg. `index_returns.compute_returns`
uses a CIK-level convention file, estimates absent coupons from implied SOFR or
filer medians, and adds PIK depending on that convention. Public fund exposure
and portfolio-characteristic exports directly use holdings rates. The separate
`timeseries_exports._export_fund_index_returns` reads fund financials/NAV returns;
it is not evidence that every public fund return uses position-income estimates.

**Resolution (D01).** Store supported all-in contractual coupon, with separate
reported meaning and cash/PIK components. Effective yield remains a distinct
reported kind. Eliminate unsupported coupon/benchmark inference and downstream
median/implied-benchmark fallbacks. Arithmetic from adequately disclosed terms is
allowed with input evidence. Normalize every writer to percentage points once;
convert Agent A decimal payloads at their boundary and revalidate their cited
spread, rather than retaining an estimate solely because it reconciles better.
Replace cash-writing B2 template semantics and the income formula in the same
migration. Incomplete inputs yield explicit unavailable income, not zero income.

**Validation and measurement.** Reuse rate/parser, B2 and return tests; change
`tests/test_identifier_spread_corrections.py` expectations to the declared output
unit and add a staging-to-unified test. Cover 475 bps / 4.75 pp / 0.0475 fraction,
cash+PIK, all-PIK, disclosed all-in with unknown cash split, effective yield, and
missing rates. Check both matching and nonmatching selectors. Report source-kind
and affected row/absolute-FV counts, eligible coupon coverage and income deltas.
Links: B1/B2/B5/E2/F6. Packet CR-02; depends on CR-01/CR-03 unit boundaries.

### F02: Reported cost and first-observed-FV proxy

**Current trace.** `with_cost` treats zero as missing and selects first nonzero
FV over the full history of `(CIK, issuer, normalized instrument, CUSIP)`.
It labels the proxy, but fund exposure and credit-risk consumers generally read
`cost` without separating proxy contributions. Current keys do not establish
that concurrent facilities or lots are the same investment.

**Resolution (D02/D05).** Preserve reported cost including zero. Select the
earliest nonmissing comparable FV of the established same position from the
pinned latest-best history; a disclosed zero FV must not be silently skipped.
Record donor row, source amount/unit, observation date, release, conversion and
whether the donor observation postdates the recipient. Do not infer original
investment cost or principal. If continuity, economic meaning or unit comparison
is unresolved, leave the proxy unresolved. Cost proxy must not determine the
identity that justified its donor. Analysts can use analytical cost, with proxy
coverage shown separately from reported-cost coverage.

**Validation and measurement.** Preserve `TestCostProxy.test_bdc_keeps_real_cost`
and provenance assertions. Replace
`TestCostProxy.test_cost_proxy_fill_fires_on_zero_cost`: its present expected
behaviour conflicts with D02. Add different same-name tranches/lots, zero donor,
later first observation, correction of donor and foreign-currency cases. Measure
source-zero overwrites, proxy donors, ambiguity and metric contributions; filled
cost is not source-verified cost. Links: B1/B2/D1/D2/E2. Packet CR-04 after CR-05.

### F03: Currency identity and FX

**Current trace.** Staging mostly strips a unit-token prefix and joins FX on the
remaining text/date. It recognizes blank/USD differently from column validation,
which also recognizes forms such as `U_USD`. Principal conversion status can
conflate reported USD and assumed USD. The configured FX CSV has only a header.
The target's common-USD FV/cost is a proposed semantic change requiring actual
unit evidence, not an assumption that all currently unusual tokens are foreign.

**Resolution (D03).** Resolve each monetary fact's XBRL unit ID through the cached
document's unit definition. Preserve original amount and resolved currency.
Only absent currency evidence may receive the approved USD default; an unresolved
nonempty token remains unresolved. Explicit foreign currency takes precedence.
Keep reported USD, assumed USD, converted foreign and unresolved FX distinct.
For a genuinely non-USD valuation, define and pin the FX source and date policy
before common-USD summation; do not install or fetch a provider in this exercise.
No supported rate means an explicit coverage failure, not a USD relabeling.

**Validation and measurement.** Reuse existing non-USD principal conversion and
missing-FX tests, plus column-validation FX02/FX03 cases. Add cached unit-ID
resolution tests for opaque USD IDs, real foreign units, blank evidence and invalid
tokens. Measure needs by field/quarter after semantic unit resolution. The saved
token inventory is a worklist, not a foreign-currency count. Links: B1-B4/D1.
Packet CR-03; SPEC-FX remains open until source units/date inputs are pinned.

### F04: NAV percentage versus portfolio weight

**Current trace.** `_correct_pct_of_net_assets` can overwrite a source percentage
with FV/NAV when the old total exceeds 200% and the replacement total decreases.
The fund NAV file may be from an earlier pipeline stage/run. Public portfolio
weights have a different denominator.

**Resolution (D04).** Preserve source-reported NAV percentage. Write a separate
calculated NAV percentage using aligned, versioned fund-quarter NAV. Retain the
existing portfolio-weight display from its declared holdings population. A range
check may flag an anomaly; it cannot choose which financial meaning is correct.
Keep zero/negative exposures and legitimate leverage effects explicit.

**Validation and measurement.** Reuse percentage-correction and column checks
as diagnostics; revise overwrite expectations. Test reported/derived disagreement,
missing/zero NAV, negative FV, leverage and display denominator consistency. Save
affected rows, source/derived deltas and NAV alignment. Links: B1/B3/B4/E2.
Packet CR-04, independent of cost changes where dependencies allow.

### F05: Validation authority, precedence and promotion

**Current trace.** `_enforce_schema` and `column_validation` disagree on some
enums/ranges (for example `html` source and `Variable` coupon); one logs warnings
before final overlays, the other assigns issue actions. Typed companion schemas
are physical contracts. Quarter acceptance is a separate aggregate gate.
Production B2 sorts by `fix_class`, while `run_corrections` sorts by precedence
stage. Loader path placement is treated as promotion authority for several
stores. Static bridge loading does not exclude `.proposed.json`. The audit write
condition omits a B2-only store, despite collecting its application records.

**Resolution (D12/D13).** Maintain one versioned field contract with explicit
applicability, nullability, units and enums. Project it into physical schemas and
validation, without turning every numeric anomaly into a structural rejection.
Keep early diagnostics but gate the final candidate after all overlays/IDs.
Use one versioned correction execution plan in verifier and production, structural
before value stages with explicit within-stage dependencies. Make accepted-input
manifests/status explicit; filenames alone must not promote proposed content.
Emit application/no-op/failure audit entries for every enabled store, including
B2-only and empty-frame scenarios. Existing proposals are not implicitly revoked;
they need compatible target semantics and re-verification before migration.

**Validation and measurement.** Reuse `test_agent_promoted.py`, correction-leaf,
column and output-schema suites. Add overlapping stage-1/stage-2 selectors,
disjoint-quarter counterexamples, rejected proposed inputs, malformed/missing
scope, B2-only audit, invalid final-cache value and partial-write failures.
Measure actual selected rows and before/after values in isolated stage replay;
static order inversion is insufficient. Links: B1/F1/F3/F5/F6. Packet CR-01 first.

### F06: Historical revisions and reproducibility

**Current trace.** Amendment selection uses latest extracted accession by filing
date/base form. Cost, shares and classification can use full-history information.
Entity, GICS and strategy inputs can come from mutable current caches; pinned
strategy candidates are preferred when present. These are not a release manifest.

**Resolution (D05).** Latest-best history is intentional. Pin source-selection
rules, source documents, corrections, identities, cache decisions and code into
each candidate. Retain previous releases and truthful decision dates. Source
selection must account for absent or partial amended schedules rather than
assuming an amendment's smaller roster is correct. Preserve legitimate comparative
observations with their own context date and filing provenance. Remove accidental
dependencies on an unrecorded previous run.

**Validation and measurement.** Reuse amendment/comparative/tie-break tests.
Add full/partial/no-holdings amendment cases, later enrichment, unchanged-input
repeat, changed-input invalidation and rollback. Historical donor use must be
reproducible and visible, not presented as knowledge available then. Links:
A3/C4/D2/F2/F4. Packet CR-01 manifest work and CR-05 identity work.

### F07: Maturity precision

**Current trace.** Staging prioritizes structured dates, then identifier parsing,
including month-end for month/year. It filters dates outside 1950-2098; some
validation paths separately recognize a 9999 perpetual sentinel. Precision can
be lost even when the parsed date is correct. Matcher maturity vetoes and weighted
maturity analytics consume the normalized date.

**Resolution (D06).** Preserve valid exact dates and existing month-end convention
with `maturity_precision=month`. Keep year-only evidence without inventing a month;
missing dates remain missing. Record explicit perpetual/invalid/unknown status
from evidence, rather than deriving perpetual status from a rejected date alone.
Matching uses compatible date intervals for partial precision; analytics disclose
the convention and exclude unsupported exact-duration calculations.

**Validation and measurement.** Retain structured-priority and valid-date tests;
replace sentinel-only assumptions with evidence-backed status cases. Add leap-year
February, exact versus month-only within-month match, real maturity conflict,
year-only and explicit perpetual. Measure source precision and changes in maturity
veto decisions. Links: B1/B2/C3/E2. Packet CR-05 with the normalization boundary.

### F08: PIK and non-accrual evidence

**Current trace.** Missing BDC non-accrual flags become false. Terms flags derive
from PIK rate and can read unknown terms as false. The PIK pipeline already
separates current paying/not-paying/unknown and terms-started, but aggregates
evidence concepts that must retain their period and economic meaning. Its
`holding_row_id` is a frame ordinal, not canonical `row_id`.

**Resolution.** Keep detection flags as legacy evidence inputs; add explicit
non-accrual status. Preserve current PIK, contractual PIK terms and terms-started
as separate claims. Absence of evidence is unknown. Interpret zero/positive PIK
evidence only for the source concept and period it supports; a stock of capitalized
PIK or cumulative duration is not automatically quarterly PIK income. No confirmed
distress-amendment claim without that evidence. Join using candidate row identity.

**Validation and measurement.** Reuse `test_pik_status.py` cases for fund-only
income, terms/current separation, transitions and scoped evidence. Add mixed
duration/instant concepts, cumulative intervals, missing source, zero evidence and
reordered holdings joins. Measure status coverage by evidence class, not merely
PIK flag fill. Links: B5/D1/E2/F2. Packet CR-06 after CR-02/CR-05 boundaries.

### F09: Raw identifiers and click-through citations

**Current trace.** `bdc_investment_identifier` has undergone prefix/text cleanup;
it is not necessarily raw source wording. Context IDs and `src_facts` are useful
anchors, but do not provide every displayed field's exact passage or aggregate
contributors. HTML bridge records contain useful document hashes/table/row keys.

**Resolution (D10).** Preserve the working normalized identifier, and separately
retain verbatim source wording in source evidence. Field evidence joins document,
context/fact or passage locator, reported value, transformation and correction.
A displayed aggregate resolves to its exact contributor set and formula. HTML/
iXBRL highlighting is required; PDF can be deferred. Evaluate Arelle against
cached dependencies, without assuming that a viewer reconstructs missing lineage.

**Validation and measurement.** Extend source-link/provenance and bridge tests.
Navigation cases include repeated identical numbers, footnotes, multiple facts in
one context, derived/proxy values, invalidated document hash and unavailable
evidence. Score locator reachability separately from semantic correctness.
Links: D1/D4/D5/E1/E2. Packet CR-07; SPEC-VIEW remains open.

### F10: Retained observations, reconciliation and the public total

**Current trace.** Holdings retain subsidiary rows, while conservation excludes
them. Some B2/Layer C mechanisms remove rows or choose parent versus look-through
representations; correctness depends on the specific source accounting scope.
Public GICS export can prefer filing/reconciled sector totals and scale them,
instead of grouping the same holdings used for the headline.

**Resolution (D08/D11).** Preserve legitimate cash/JV/subsidiary/underlying
observations and explicit relationships/accounting membership. Exclude proven
duplicates/subtotals from holdings with retained source disposition evidence;
do not globally remove subsidiaries. Re-verify each exclusion against its scope.
Reconciliation uses a declared comparable anchor and membership bridge. Public
headline, instrument and sector totals use exactly the same canonical holding
population, including an unknown sector bucket. Remove scaling/reconciled
substitution from those public aggregates. The owner's tolerance for source error
does not relax exact consistency between charts using the same data.

**Validation and measurement.** Reuse subsidiary and conservation tests and add
same-borrower different facilities, parent/underlying scopes, legitimate prior
periods, zero/negative FV and unknown sectors. Independently assess complete
schedules, not only residuals. Measure omitted/extra positions separately from
absolute comparable-FV discrepancy and internal exact totals. Links:
A1/A2/A5/B3/B4. Packets CR-01/CR-07; numerical reconciliation targets remain D12.

### F11: Evidence scope, GICS and descriptions

**Current trace.** Current numeric provenance replay covers eight named fields,
not all 88 holdings fields. `gics_sub_industry` is the stored classification field;
sector coverage often derives from it. Cache application, reviewed fallback and
real-estate overrides have distinct authorities. The configured lien cache may
be absent. Reported BDC unrealized-gain/loss text is distinct from FV minus cost.

**Resolution (D09).** Keep the exhaustive field map. Add sector-level assignment
without requiring finer GICS; unknown is counted in coverage. Label inferred/
mapped/enriched values with method, taxonomy, evidence, input and decision
versions. Current replay status certifies only its tested field/meaning. Preserve
reported UGL and label any calculated mark separately, including proxy cost.
Align descriptions and tests with the final field contract, without overstating
the number of source-verified fields.

**Validation and measurement.** Reuse cache/schema/provenance tests; add sector-
only assignment, cache conflict/abstention, changed issuer evidence and source-
versus-inferred cases. Independent GICS benchmark reports sector accuracy,
assessability and row/absolute-FV/unique-decision coverage. A cached label's
presence does not establish correctness. Links: B1/D1/D3/F1. Packet CR-06 and
SPEC-REF; no new enrichment calls authorized by this document.

### F12: Row, borrower and position identity; final writes

**Current trace.** Row IDs use source anchors when possible; collision suffixes
are ranked using mutable amounts/text. Fallback natural keys are content-sensitive.
Entity IDs are sequentially allocated on rebuild. Wrapper position keys and
production position IDs have different guarantees; the persistent position
registry remains opt-in. Entity/position stages and PIK ordinals can therefore
break cross-artifact or cross-rebuild joins even if one file's IDs are unique.

**Resolution (D07).** Distinguish source observation, borrower and within-filer
facility/lot identity. Reuse stable source anchors, add immutable source-lot
discriminators or aliases for collisions, and keep persistent entity/position
registries with merge/split/retirement history. Trial registry state is isolated
and committed with the candidate. Uncertain continuation stays uncertain; an
unmatched row is not automatically a new investment. The finalizer writes holdings,
matches, PIK joins and companions from compatible snapshots exactly once.

**Validation and measurement.** Reuse registry, matching, row-ID, resolver and
typed-companion tests. Add insertion/reorder/corrected-amount collision cases,
concurrent facilities/lots, ambiguous merges/splits, amendment aliases, partial
write/retry and rollback. Measure entity accuracy on an independent pair frame;
measure continuation and complete-chain correctness separately from edge precision.
Unique IDs in today's file are not rebuild-stability evidence. Links: C1-C4/F2/F4.
Packet CR-05, coordinated with CR-01 finalization.

## 4. Bounded implementation packet specifications

These define boundaries and required evidence for later execution. They are not
permission to rebuild or replace production artifacts during this spec exercise.
Each execution packet must pin the independent examples and numerical gate first.
These seven packets address the contract conflicts. The dbt/production-stack
migration remains a separate programme workstream under the target contract;
it must preserve these measured boundaries and does not replace their validation.

| Packet | Allowed change boundary | Dependencies | Concrete completion evidence |
|---|---|---|---|
| CR-01: candidate and rule execution | Unified coordinator, shared correction runner/loaders, audit writer, orchestration, manifest/schema validators; matching and financial formulas unchanged in this packet | Pin starting tree/source/rules; SPEC-RULES scoped replay and final schema projection | Identical verifier/production selected rows and order; B2-only audit; proposed input rejection; final overlay validation; candidate interruption/rollback; source-accounting and exact-total checks remain visible. |
| CR-02: rates and income | BDC/N-PORT rate normalization, Agent A/B2 rate payload adapters, convention evidence, returns formula and directly affected analytics/tests | CR-01; resolved rate/unit examples; SPEC-REF | Declared-unit fixtures, cash/PIK truth table, no implicit rate inference, atomic consumer deltas, signed-quarter re-attestation. No isolated storage-only flip. |
| CR-03: currency evidence | Cached unit resolver, normalization/FX reference contract, original/USD evidence and affected consumers | Source unit inventory and source/date FX policy for actual foreign amounts | Source-backed unit resolution, no false foreign labels from opaque USD tokens, missing/assumed/converted distinctions and explained public-sum delta. |
| CR-04: cost and percentages | Donor selection, reported/analytical cost, reported/calculated NAV fields and their analytic consumers | CR-05 identity; CR-03 comparability; pinned fund NAV upstream | Reported-zero preservation, unique donor evidence, proxy contribution, separate denominator reproduction and missing-NAV cases. |
| CR-05: identities and maturity | Row/source-lot mapping, entity and position registries/matcher, maturity precision, compatible PIK/evidence joins | CR-01 isolated registry/finalizer boundaries; held-out identity cases | Addition/reorder/correction/merge/split/retry stability, precision-aware vetoes, calibrated continuation/chain metrics, no CSV/companion divergence. |
| CR-06: evidence and enrichment | Field-evidence records, PIK status semantics, versioned GICS/other cache assignments | CR-02 coupon meaning; CR-05 identity; independently governed labels | Current/terms/unknown distinctions, period-aware evidence, sector-only GICS, accuracy/coverage/abstention by evidence category. |
| CR-07: serving and citations | Shared metric definitions, exports, complete holdings/history access, HTML/iXBRL resolver/UI | Final candidate schema/evidence; SPEC-VIEW inventory; CR-01 release boundary | Exact contributor totals, complete accessible rows, correct highlights/formulas, disclosure and browser scenarios; PDF explicitly delivered or deferred. |

For every packet: write only isolated trial artifacts during development; record
source-backed expected deltas; preserve source-selected counterexamples; run
targeted tests then the required integration/full checks at handoff; rebuild from
cache only when executing the approved implementation; inspect semantic diff and
re-attest signed quarters. Failed verification keeps the packet incomplete.
Do not refresh the active baseline to erase a failure. Rollback restores the prior
complete artifact/registry bundle, not individual files from different candidates.

## 5. What is still needed before the numerical gate

1. Adjudicate the obligation frame and select independent complete source schedules,
   field examples, entity/position labels and sector labels. A missing output is
   not proof that the fund was ineligible.
2. Replay scoped rule interactions in isolated stage snapshots, completing active
   rule and post-overlay ownership coverage. Static loader eligibility is already
   recorded; runtime application and expected meaning remain separate checks.
3. Implement the missing evaluators against frozen references, measure all required
   quarters and report uncertainty/assessability. Keep dated saved-artifact profiles
   separate from results on a synchronized candidate.
4. Present the owner with calibrated thresholds and any material evidence/scope
   exceptions, then the execution budget/control proposal. There is no new policy
   question merely because an old test encodes a now-rejected behaviour.

Verification for this specification: source and test-definition inspection,
bounded DuckDB/config assessment, input stat guards, document/artifact consistency
and link checks. No pytest, frontend build, correction replay, source benchmark,
rebuild, export, download, model enrichment or agent fleet was run.
