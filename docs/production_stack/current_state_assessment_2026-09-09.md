# Programme current-state assessment — 2026-09-09

The platform has substantial extraction, correction, reconciliation and agent-operation infrastructure. The main readiness problem is that those components do not yet produce one reproducible, consistently validated public release. Refactoring alone would preserve several unresolved semantic and publication defects.

This assessment supports a programme specification, not an approval to publish or a pipeline implementation change. End-state: release candidate ready for owner approval. Required history: Q1 2023–Q1 2026; a separately validated Q4 2022 opening snapshot; Q2 2026 as a conditional forward-processing test. Matching, entity resolution, inferred-value evidence and source click-through are in scope. Public indices and non-BDC vehicles remain out of scope.

## Evidence and limits

Inspected working tree at HEAD `2e0491a45d1493e7a3ee329aee52ec96bb34986c`, including existing dirty changes. Used source tracing, changelog/investigation review, configuration inventory and bounded read-only DuckDB profiles of cached artifacts on 2026-09-09. No SEC/model calls, production writes, rebuilds or validation reruns occurred.

- [Architecture](../reference/current_architecture.md): responsibilities, ordering, dependencies and active versus planned components.
- [Source inventory](../reference/architecture_source_inventory.csv): 123 pipeline files, 234 scripts, 143 test files; hashes and static inventory.
- [Rule/config inventory](../reference/architecture_rule_assets.csv): 534 assets with loader/stage/disposition. This does not certify every embedded rule or resolve overlapping rules.
- [Evidence snapshot](current_state_evidence_2026-09-09.json): measured counts, artifact timestamps, saved gate and supplemental profiles. Temporary diagnostic scripts/logs are in `scratch/2026-09-09_architecture_assessment/`.
- [Existing crosswalk](../reference/unified_holdings_contract_crosswalk.md) and [consolidation preparation plan](consolidation_readiness_plan.md): retain and extend these rather than start duplicate schema/planning work.

Saved gate results below are historical artifact observations, not a fresh attestation. Matching accuracy, source completeness, legal-entity correctness, PDF availability and remote backup status were not independently recertified. The source inventory covers files; deep inspection concentrated on execution paths, dependencies and known risk areas.

## Measured snapshot

| Measure | Observation |
|---|---|
| Canonical unified holdings | 780,425 rows; 88 columns; CSV modified 2026-09-08 15:49:07 UTC. |
| Source population | 560,263 BDC rows / 192 CIKs; 220,161 N-PORT rows / 146 CIKs; one null-source row. This is broader than public v1. |
| Public cohort | Manifest contains 70 CIKs; Q1 2026 holdings contain 69. |
| Q1 2026 public holdings | 30,067 rows; FV **381,537,030,207** across all classifications, with subsidiary rows retained. |
| Q4 2025 public holdings | 28,938 rows / 67 funds; FV 374,335,565,067. |
| Q1 2026 entity IDs | 29,207 populated; fill does not prove correct resolution. |
| Q1 2026 position IDs | **Zero populated**; position keys populated on 30,062 rows. |
| Q1 2026 source anchors | Row IDs on all 30,067; context IDs on 30,028; saved source facts on 26,876. |
| Q1 2026 GICS | 15,041 populated rows; FV 278,502,213,593, approximately 73% of FV. |
| Q1 2026 other fields | Issuer missing on 402 rows; CUSIP and LEI populated on zero rows; maturity on 26,009; interest rate on 21,213. |
| Q1 2026 principal | Principal amount on 24,229 rows versus USD principal on 10,771. Eligibility/currency reasons require separate assessment. |

Fill rates are descriptive, not eligibility-adjusted accuracy scores. The null-source row is CIK `0001954360`, 2024-03-31, FV 745,000; its cause was not investigated or corrected.

## Findings that materially affect the programme

### 1. The public artifacts disagree with current canonical holdings

| Artifact/value | Saved value | Difference from current cohort CSV |
|---|---:|---:|
| Canonical Q1 2026 FV | 381,537,030,207 | — |
| `metadata.totalAum` | 381,907,021,055 | +369,990,848 |
| `portfolio_characteristics.portfolioFv` | 382,151,960,774 | +614,930,567 |
| Sum of `gics_sector_breakdown.totalFv` | 382,151,960,774 | +614,930,567 |

The JSON files were modified around 07:38 UTC on September 8, before the afternoon holdings rebuild. Metadata still reports 30,083 holdings. The homepage actually prefers `portfolioFv`; reporting only the metadata mismatch would miss the displayed total. The portfolio characteristics `totalFv` field is a narrower direct-lending measure, not the all-portfolio headline.

There is also a code-level conflict: GICS sector export uses reconciled source-sector overlays and scaling, and the homepage constructs instrument slices through layered lien calculations. Current AGENTS requires direct aggregation of the same holdings for both donuts and the headline. Merely refreshing JSON would not resolve that conflict. Historical comments documenting an earlier sector-overlay decision do not supersede the current product contract.

**Required outcome:** a common release snapshot and exact same-holdings public aggregation, with reconciliation overlays separately identified if retained for diagnostic purposes. Export must consume a reviewed acceptance verdict for the same inputs.

### 2. Mixed artifact generations undermine reproducibility

`position_matches.csv` has **497,456 rows** (September 8, 08:17 UTC), while its Parquet companion has **536,455** (08:12 UTC). This is a measured content-count discrepancy, not just timestamp lag. A complete semantic comparison was not run.

Unified construction writes CSV and Parquet; later entity and return/matching stages can rewrite the CSV without refreshing its companion. Matching also writes intermediate companion data before later CSV finalization. These write paths provide a plausible mechanism for divergence; no isolated reproduction was performed.

Other saved products have different input vintages: strict PIK and match-quality metrics date from September 5, while holdings were rebuilt September 8. The current holdings rebuild has blank Q1 position IDs despite saved position returns/matches. The existence of those files therefore does not demonstrate an integrated current matching result.

**Required outcome:** one declared writer per artifact, explicit stage dependencies, run/input/schema/rule versions, companion parity and refusal to serve inconsistent dependencies. The Parquet reader flip needs these controls before declaring parity.

### 3. The current saved quality gate fails, despite strong numeric provenance

Saved `quarter_acceptance.json`, generated **2026-09-08 16:31:46 UTC**, evaluates Q1 2026 under provisional v3: **FAIL, 4/9 checks pass**.

| Check | Saved value | Verdict |
|---|---:|---|
| Fund coverage | 69 | Pass |
| Reconciliation rate | 80.882% (55/68) | Fail |
| Flagged FV share | 25.715% | Fail |
| Source-blocking FV share | 0.259% | Pass |
| Verified FV share | 60.254% | Fail |
| Promoted-rule drift | 15 | Fail |
| Promoted-rule health | 0 | Pass |
| Over-inclusion FV share | 0.883% | Fail |
| Unfinished investigations | 0 | Pass |

The 15 drift observations consist of 14 scope-carryover and one row-drift observation; they are not 15 execution errors. Application audit has 175 records across anchor, B2 and Layer C families. Historical Q4/Q1 v2 signoffs remain historical; they do not establish current v3 acceptance. Provisional rollout/calibration decisions remain open.

Joining the active provenance ledger to current Q1 cohort rows yields 30,026 FV raw matches, representing 380,589,786,729 FV (approximately 99.75%). Another 39 lack provenance and two are marked corrected/not checked. This is compatible with a failing quality gate: copying the right number from a subtotal or duplicated source context can still create the wrong holdings dataset. Numeric provenance is not a substitute for completeness and economic-row validation.

Latest residual artifact headers, September 8 around 16:13 UTC, report **9,335 blocking source-only rows out of 15,338 reviewed**. These are the artifact's full population, not a Q1 cohort-only count. The separate residual artifact reports 440 blocking groups out of 8,950 and uses another row denominator. Do not mix these measures or use the retired 25-bundle review queue.

**Required outcome:** freeze approved per-quarter acceptance definitions and denominators, strengthen genuinely independent reference checks, and remediate against those gates without weakening them to accommodate current output.

### 4. Historical scope needs eligibility and disclosure-time rules

The preceding cached coverage investigation found only **39 cohort funds with current-period Q1 2023 holdings coverage**, versus a current fixed gate floor of 60 funds. A fixed present-day cohort denominator cannot decide whether a historical absence is legitimate, a missing filing, or an extraction failure.

Q4 2022 has broader comparative-period presence but only three funds in current unified output. The approved opening snapshot requires deliberate comparative selection, accession precedence, deduplication and disclosure-availability rules. Removing the current-period filter globally is not an adequate historical reconstruction design.

**Required outcome:** a fund-quarter obligation matrix covering formation/operation, filing availability, extraction eligibility, source coverage and exceptions. Preserve reporting date and disclosure date separately. Q2 2026 forward-test sufficiency remains to be assessed from the cache.

### 5. Identity work exists, but stable identity is not yet a contract

Production matching already uses contested assignment with a maturity veto. Gold-set, pair review, chain auditing and continuation tooling exist. The opt-in position registry is not the production default. Entity resolution also reallocates its sequential IDs during rebuild, a separate stability problem from position renumbering.

Current entity resolution combines names, structured identifiers, fuzzy matching and cross-source clustering over all dates. It does not establish a versioned legal-entity hierarchy or temporal identity graph. The public Q1 cohort has no populated CUSIP/LEI values, so structured-identifier support alone does not establish usable cohort coverage.

Historical gold-set outcomes are useful development evidence, but several precede recent matching changes, depend on a particular adjudicator/sample, or omit zero-FV cases. No new precision/recall or chain-completeness attestation was run here.

**Required outcome:** separate entity, within-filer position, cross-quarter chain and optional cross-filer instrument contracts. Define identifier persistence, split/merge/version behavior, false-match versus missed-match tolerances and independently reviewed evaluation samples. Cross-filer tranche identity needs an explicit scope decision; it is not implied by borrower entity resolution.

### 6. Enrichment is a substantive subsystem with incomplete lineage

The company GICS cache contains **184,708 records**, including 128,241 labelled `llm`; it also contains keyword, reported-industry and other sources. The separate industry-label cache has 2,502 mappings: exact 157, alias 508, fuzzy 193, aggregate 223 and LLM 1,421. Neither total is a count of current cohort holdings or independently correct assignments.

Company-cache decisions are keyed by normalized name and retain limited evidence fields. Holdings do not retain the full decision provenance; cache-save timestamps are not original decision timestamps. Taxonomy, prompt/model, source text, identity binding and effective date are not comprehensively versioned. Existing GICS gate/review/quarantine machinery is valuable but not a mandatory end-to-end publication gate.

Unclassified-instrument review evidence and late fund-specific industry remaps also belong in the inventory. The configured lien enrichment cache is absent, so support in code must not be described as active coverage.

**Required outcome:** field-level reported/calculated/enriched evidence records, versioned enrichment inputs and decisions, confidence calibration on reviewed samples, abstention and stale-inference handling. Display an inference as an inference even when its business-description evidence comes from a filing.

### 7. PIK and rate semantics remain material gaps

All **30,083** Q1 cohort rows in the saved September 5 strict-PIK artifact have `unknown` current status. Other sources/periods in the full artifact do contain paying/not-paying evidence. Unknown must not become no PIK; disclosed schedule terms remain a separate usable proxy.

The all-in-rate decision is documented but storage still carries the cash leg. Income calculations and storage must migrate together. Principal versus USD principal, currency, cost source and rate source also need explicit schema semantics rather than a fill target alone.

**Required outcome:** approve the existing crosswalk's financial decisions, then implement atomic semantic changes with source-grounded regression checks and historical reattestation.

### 8. Click-through requires a larger serving contract than a viewer

There are useful XBRL fact/context references, raw XML reverification, HTML hashes/table/row/cell anchors and inline-XBRL status records. There is already a quality UI. These should be reused.

However, current fund holdings exports expose only the latest positive-FV top 20 and omit durable row/source identifiers. The filings tab links to a filer search, not the exact supporting document. No full historical position browsing or inline PDF citation path was found.

**Required outcome:** complete schedule/history access; citation identifiers on displayed values; aggregate calculation lineage; exact-document passage anchoring; clear enriched-value evidence; and an explicit fallback for sources available only as HTML/XBRL. PDF coverage and mapping must be measured before promising every number a PDF highlight.

### 9. dbt migration must preserve correction and validation boundaries

The existing spike has two models, tests and packet-conversion machinery, tested on three CIKs for one dimension-deduplication defect. Its documented round trip is useful feasibility evidence, not a completed migration or data-quality certificate. Production orchestration still lives in Python/scripts.

Rules are spread across 77 v3 wrappers, grammars, anchors, promoted correction families, inline code/SQL and mutable output-directory caches used as inputs. Simply transferring transforms would miss precedence, exceptions and feedback dependencies. The new 534-asset inventory makes those dependencies visible but does not settle semantic overlap.

**Required outcome:** complete the preparation plan's rule/financial/acceptance mapping; migrate bounded transforms behind measured gates; preserve evidence, promotion controls and signed-quarter checks. Avoid a broad rewrite before the data contract is approved.

### 10. Long-running execution needs durable task state

Quarter passes already checkpoint stages and preserve evidence. The worker runner's normal cleanup harvests traces and removes resumable sessions. A retained transcript is not necessarily a resumable worker state. `-NoCleanup` is available, but quota-interruption/resume behavior was not tested and provider behavior was not researched in this assessment.

**Required outcome:** persisted work packets and input fingerprints, bounded attempts, idempotent stages, explicit completion/blocking reasons and safe restart from the last verified stage. The programme should not depend on an agent remembering work or recreating unrecorded decisions after a usage-window interruption.

## Recommended programme structure

| Workstream | Reuse | Completion evidence to specify |
|---|---|---|
| Release/schema contract | Crosswalk, thresholds, manifest, signed quarters | Approved financial semantics, historical obligations, consistent release/input manifest. |
| Coverage and correctness | Reconciliation, oracles, shadow ledger, correction verification | Per-quarter source-grounded coverage and error measures; independent sample review; no signed-quarter regression. |
| Identity and temporal matching | Existing resolver, matcher, gold tooling, registry | Stable identity lifecycle; measured false/missed links and chain coverage; explicit cross-filer instrument boundary. |
| Enrichment and evidence | GICS caches/gates, review caches, provenance/HTML anchors | Traceable decisions, calibrated sampled accuracy, abstentions and public evidence labels. |
| Production transformation | Parquet schemas, dbt spike, preparation plan | Versioned dependencies, bounded migration parity, single-writer artifacts and resumable runs. |
| Product access and citations | Existing Next.js UI, quality surfaces and exports | Complete required holdings/history, exact FV aggregation and tested value-to-source navigation. |

Start with the release/schema/acceptance contract and a frozen input snapshot. Identity and evidence design can proceed alongside that work; dbt implementation should follow the agreed semantics. Publication integration is a final acceptance exercise across workstreams, not a substitute for their individual gates.

No numerical accuracy targets are silently approved by this assessment. The next specification step is an acceptance matrix defining metric, eligible denominator, source of truth, threshold, exception policy and saved evidence for each outcome. Existing gate thresholds are starting evidence, not automatically suitable for every historical quarter.

## Verification performed

Read-only diagnostics completed with bounded runtime/memory and no persistent diagnostic job. Source and rule inventories were generated; documentation links and whitespace were checked. No pytest, frontend build, rebuild, export, semantic output diff, baseline refresh or signed-quarter reattestation was run. Those would test or mutate a different scope than this documentation assessment. Production artifacts and pre-existing working-tree changes were left in place.
