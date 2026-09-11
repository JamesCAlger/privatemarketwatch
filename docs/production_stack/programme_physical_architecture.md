# Programme physical storage and execution design

Date: 2026-09-09. Version: 0.3; clarified 2026-09-10. Status: proposed implementation design, reconciled with the later units/identity contract. [Overnight preparation](programme_spec_closeout_2026-09-09.md) instantiated isolated snapshots, stage manifests, a restored real bundle and a durable-ID reference prototype. The first implementation tranche subsequently exercised an isolated runner around the legacy builders. The target registries and release-adoption design remain unimplemented; see [specification status](programme_spec_status.md).

## 1. Decisions

Use the existing local cached sources, typed Parquet for durable analytical records, DuckDB for working tables, dbt for the agreed relational stages, and static files for the website. Use immutable registry snapshots and single-coordinator JSON control records; a separate operational database is unnecessary for the initial single-machine runner. A future scheduler may index these records without becoming the authority for their contents.

The [logical model](programme_data_model.md) defines what records mean. The [processing architecture](programme_processing_architecture.md) defines P00-P10 ownership. This document defines where records live, how a completed result becomes reusable, and how recovery avoids mixing releases. The [implementation plan](programme_implementation_plan.md) supplies work packages and launch conditions.

| Decision | Initial implementation |
|---|---|
| Bronze storage | Keep `data/raw/` in place. Inventory and hash selected cached files; do not relocate or duplicate the entire cache. |
| Candidate storage | New `data/programme/candidates/<candidate_id>/`, outside production output and frontend roots. Add its ignore rule in the isolation implementation package. This document creates no candidate directory. |
| Silver/gold | Typed Parquet boundary artifacts, with small diagnostic CSV/JSON where useful. One Parquet file per ordinary relation initially. |
| Working database | Candidate/attempt-local DuckDB, with one owning writer process. It is rebuildable working storage, not a release dependency. |
| Registries | Accepted entity, position and accounting-scope snapshots are immutable Parquet plus reviewed revision records. New assignments are candidate-local. |
| Run control | Immutable JSON input/output manifests, completion records and event files, written by one coordinator. A small replaceable status index is a convenience, not evidence. |
| Existing CSVs | `private_markets_holdings.csv` remains the canonical compatibility artifact. Preserve the existing eleven CSV/Parquet companions and the separate, gated reader migration. |
| Serving | Immutable JSON/contributor shards and cached document renditions built from one sealed data release. Keep the Next.js static-site pattern. |
| Adoption | One accepted-release pointer binds data, registry snapshots, evidence and delivery. Programme completion produces a ready candidate; it does not change that pointer. |

## 2. Physical layout and authority

Proposed paths are relative to the repository unless an explicit configured storage root replaces them. Manifests use logical root names plus relative paths; machine-specific absolute paths belong in local runtime configuration.

```text
data/raw/                                      existing cached source authority
data/reference/, data/overrides/                existing governed reference/decision homes
data/programme/
  cache/extraction/<input_fingerprint>/         reusable P01 bundle + completion manifest
  candidates/<candidate_id>/
    inputs/                                    frozen P00 manifest and small input snapshots
      source_inventory.parquet
      decisions/                               admitted exact payloads + review references
      registries/                              pinned parent registry snapshots
      code/                                    HEAD, dirty patch, used untracked files
      environment/                             Python/dbt/Node/viewer locks and identities
    attempts/<attempt_id>/
      work/<stage>/<partition>/                DuckDB, dbt target/logs, temporary files
      results/<stage>/<partition>/             completed boundary bundles and manifests
      events/                                  one immutable coordinator event per file
      logs/                                    process output and bounded progress records
    seals/<seal_id>/                            immutable data/evaluation/delivery manifests
    review/                                    review-pack versions + unresolved decisions
  releases/<release_id>/                        immutable release descriptor and events
  pointers/accepted.json                        sole adopted data + registry generation
  pointers/published.json                       published approved bundle, if deployed
  operations/                                  leases and disposable status indexes
```

Release descriptors reference sealed candidate artifacts rather than moving an open working directory or copying every source. Once referenced, those artifacts are retained immutable release dependencies. A backup/export package must include their full dependency closure; a descriptor alone is not a backup. Reusable cached artifacts also become protected dependencies when a seal references them.

Keep `data/output/`, `frontend/public/data/`, the active baseline and the existing registry path untouched by candidate work. Compatibility export into those paths is a separately authorized adoption operation, after checks against the actual bundle. Existing scripts must accept explicit input/output context before they can serve as isolated adapters; changing the working directory cannot redirect imported global paths.

Resolve every declared write path against its permitted root, including filesystem links; reject path traversal and an absolute path that escapes the candidate. Give a source-cache writer only its explicitly claimed extraction-cache key, not unrestricted access to production roots. Test the resolved paths, not just a string prefix.

Source bytes and admitted decision payloads are authoritative inputs. Parquet projections of JSON decisions are generated inputs to dbt, not another editable correction store. The final CSV and its strict typed companion are one governed projection. Registry snapshots, assignment history and evidence sidecars are part of the same seal, never whichever file happens to be newest.

A source file that changes at its old cache path must fail the pinned hash check. Preserve the old bytes before adopting the changed source into a new candidate. Paths and mtimes can accelerate inventory, but are not evidence that bytes stayed unchanged. No automatic network recovery is permitted.

## 3. Materialization map

Use the exact relation names and keys in the logical catalogue. A family below is a directory/model group, not a proposal to join all of its records into one wide file. Release-independent source facts can be shared through an admitted manifest; release-bound relations carry `release_id` in their typed schema.

| Family / producer | Durable physical records | Working / serving treatment |
|---|---|---|
| Reference / P00-P02 | `fund`, `cohort_member`, `fund_quarter`; frozen taxonomy, FX, metric definitions and display bindings | Small single-file Parquet relations; source-status and eligibility frame exist even when holdings are empty. |
| Sources / P01 | `filing`, `source_document`, `source_context`, `source_unit`, `source_occurrence`, `source_evidence` | Per-document extraction bundles keyed by bytes, parser/config/taxonomy versions. Read through explicit manifest file lists, never an unrestricted cache glob. |
| Selection / P02-P03 | `source_selection`, `source_selection_member`, `occurrence_disposition`, `scope_assignment` | Single-file Parquet boundary outputs. Keep alternative, failed and untagged-row dispositions. |
| Accounting / P02, P08 | `accounting_scope`, `holding_relationship`, `reconciliation_anchor`, `anchor_member` | Independent anchors originate upstream; final membership is built against sealed observations. Missing basis is an issue, not an inferred zero. |
| Holdings / P03-P07 | Normalized matching-input projection; final `holding_observation`, `holding_source`, observation metadata companion | P03 intermediates are typed and explicit. P07 writes the canonical CSV/Parquet plus metadata keyed by row ID; no extra shared CSV columns beyond the ten already proposed. |
| Identity / P04 | `entity`, `entity_alias`, `entity_relationship`, `position`, `identity_revision` and typed revision members; `entity_assignment`, `position_assignment`, `position_link` | Registry snapshots and release assignments separate. Existing match/edge CSVs remain supported projections. No matcher writes the final holdings file. |
| Evidence / P03-P07 | `field_state`, `field_input`, `decision`, `decision_review`, `release_decision`, `correction_application` | Typed sidecars; normalized decision/review tables project the pinned payloads. A field-input union has enforced typed foreign keys. |
| Enrichment/status / P05-P06 | `enrichment_assignment`, `holding_status`, `taxonomy_term`, `fx_quote` | Separate classification decision from its affected rows; retain PIK meanings and legacy provenance gaps. |
| Metrics / P08 | `metric_definition`, `population`, `population_member`, `metric_result`, `metric_input`, `display_binding` | dbt models over sealed data; source-reported fund metrics needed by earlier stages are already available from P02. Export small summaries and complete contributor shards. |
| Control / P00-P10 | `release`, `release_artifact`, `stage_checkpoint`, `release_event`, `validation_result`, `quality_issue` | JSON manifests/events are operational authority; typed projections support audit queries. Full evaluation failures are archived independently of dbt failure-table limits. |

### File sizes and dbt materializations

Preserve the [phase-1 decision](phase1_parquet_migration_plan.md): ordinary core artifacts start as single files; do not create hundreds of fund/quarter partitions without measured need. Partitioning an expanded relation above roughly ten million rows is a review trigger, not an automatic change. Benchmark actual scan time, peak memory, file count and restore cost before selecting partitions. P01 document caching and P09 browser sharding have distinct purposes and do not imply partitioning the canonical holdings CSV.

Inside an attempt, use views for light staging projections over pinned Parquet, and tables for expensive reused transformations. At every Python/dbt boundary, export an explicitly typed, checked Parquet bundle before marking the stage complete. Start with full model reconstruction over the pinned scope; incremental models require equality to a full build under amendments, rule changes and older-quarter additions. Use exact manifest paths and candidate-local dbt targets, database files, logs and failure tables.

For field metadata, store reusable state profiles plus `(release_id, row_id, field_name)` assignments and exceptions when this is smaller than a fully expanded relation. Provide one governed expansion view that yields exactly one logical state per governed field, including missing fields. Profile sharing cannot inherit an unrelated row's source locator, value hash or inference. Always persist individual input edges needed for a donor, FX conversion, denominator or decision.

The candidate preflight measures capacity; this design makes no new disk-size estimate. Reserve space for one complete candidate, its largest in-progress replacement bundle, validation/export outputs and database spill. Fail before dispatch if the measured reserve is unavailable. Do not delete old releases or the baseline to make a build fit.

## 4. Schemas, serialization and exact totals

Extend `pipeline/output_schemas.py` deliberately for physical boundary schemas, retaining one authority for each artifact's ordered fields/types. Applicability, enums and financial rules remain in the governed field contract and validators. New sidecars use explicit schemas; inference from whichever values appear in the first file is insufficient. A schema fingerprint includes field order, types, nullability/constraints and versioned contract references.

**Isolation must not weaken schema checks.** Currently `pipeline.utils.write_parquet_companion()` defaults to strict contract handling only inside the real output directory. Candidate adapters must request `strict=True` for governed companions and fail if a required companion is absent. Moving a file into a trial directory must not silently turn it into an untyped all-text companion.

Until the separately approved reader transition, finalization writes the CSV and produces its Parquet by strictly casting the persisted CSV tokens, following the existing writer contract. Enforce row count, unique keys, ordered columns and typed value equality before sealing. Null and numeric zero remain distinct. Source numeric tokens are retained separately from current `DOUBLE` values; this design does not introduce a new money-rounding policy.

Define the public aggregation convention as follows:

1. Interpret each finalized finite USD FV token as a base-10 number, including scientific notation. The token is the value actually persisted in the canonical CSV, not an earlier in-memory float.
2. For a public quarter population, select a common exact decimal scale sufficient for all its tokens and an accumulator width sufficient for the sum of absolute amounts. Record both in the arithmetic manifest. DuckDB decimal execution must fit its supported precision; a non-exact cast, overflow or unsupported scale fails this arithmetic check rather than rounding or falling back to binary summation.
3. Compute the headline, instrument groups and industry groups from that identical membership and decimal representation, including unknown classifications and valid negative values. Assert exact equality of the unrounded sums. Rounding for compact labels follows the pinned display binding; independently rounded labels are not the equality test.
4. Carry exact amounts as decimal strings in new metric payloads, alongside numeric chart coordinates where needed. Client-side binary floating-point arithmetic must not recalculate authoritative totals. A shared formatter controls display units and rounding.

Derive scale/width once with bounded SQL profiling of the persisted tokens, not a Python loop over the holdings. WP-09 must demonstrate this convention on the actual candidate, including sub-cent/scientific tokens and overflow rejection. Failure exposes an explicit serialization design issue; it does not permit widening tolerances. Source-precision accuracy checks remain separate.

DuckDB's documented decimal precision limit is 38 digits; decimal addition can be exact within that limit, while decimal division returns an approximate floating-point result. The exact-total contract therefore governs monetary reductions; ratios have their own formula/rounding contract. Verify behavior against the pinned runtime, not a bare default decimal cast. [DuckDB numeric types](https://duckdb.org/docs/current/sql/data_types/numeric).

## 5. Registry persistence and concurrent candidates

The initial durable registry is a sealed set of typed Parquet relations, not a writable global service. P04 loads a pinned accepted-parent snapshot into its working database, calculates proposed changes, and emits a new snapshot with assignments and revision evidence. P07 binds the complete registry output hash. Acceptance checks compare it to the input registry, not to a mutable latest lookup.

Retain existing IDs only where their uniqueness, scope and provenance can be established. The current opt-in position registry is an implementation starting point: its source key includes principal/shares and its collision behavior needs migration review. Do not turn it on as a substitute for SPEC-ID. Produce a legacy-to-new mapping, explicitly representing ambiguous mappings and corrected merges/splits.

For newly minted IDs, follow the later [units/identity contract](programme_units_fx_identity_contract.md#persistent-identity-migration): UUIDv5 allocation from identity kind, governed scope and immutable creation-decision ID, under a fixed programme namespace. Source occurrences and disclosed-lot anchors support that decision; do not allocate directly from the lexically first current member of a source component. Persist the creation decision permanently. Existing accepted IDs take precedence over recomputing allocation from a changed member set. The first migration must pin exact byte serialization, namespace constants and counterexample fixtures before IDs are admitted; the preparation allocator is reference code, not an already adopted production registry.

Mint IDs in the Python registry adapter and persist the exact versioned string representation as `VARCHAR`, preserving established legacy strings unchanged. This does not introduce a DuckDB UUID physical type or allow allocation inside dbt. The first registry migration pins the namespace constants, serialization and encoding fixtures before any new IDs are admitted.

This is an allocation mechanism, not entity-resolution or matching evidence. Conflicting creation decisions or ambiguous source assignments fail admission; mutable issuer names, amounts and CSV ordering cannot disambiguate them. Namespaces, encoding and creation-decision versions are pinned inputs. New concurrent lots require distinct source occurrence/disclosed-lot evidence and distinct creation decisions. Merges/splits use reviewed revision members; do not overwrite a registry row to pretend the old identity never existed.

Store completed allocation bundles under P04 results and reuse them on a valid retry. If interrupted before commit, replay deterministically from the same pinned parent/inputs. Adding an older observation to an established accepted position retains its ID. Repeated cold builds use the same namespace/inputs and must yield the same identities; semantic twin-build comparison includes IDs rather than ignoring them.

Only one coordinator can finalize a candidate. Different candidates can read the same parent but cannot both adopt against it without checking the pointer. Adoption requires the expected parent still to be current. If it has changed, freeze the stale candidate for review and build a new candidate against the new accepted registry; never silently merge its allocations into accepted state. Published rollback never reuses retired IDs for unrelated positions.

## 6. Manifest and checkpoint protocol

Separate `candidate_id` (frozen input/decision selection), `attempt_id` (execution attempt), `evaluation_id` (one evaluation run) and `seal_id` (an immutable complete bundle). A data `release_id` binds P07 data; a delivery revision may reference unchanged data with new viewer/display inputs, under a new candidate and P10 seal. Changing a financial/source/identity input requires a new data release. Operational times, process IDs and elapsed costs are not part of semantic data identity.

| Record | Required fields |
|---|---|
| Input manifest, P00 | Format version; candidate and intended data release; accepted parent reference; scope/roles; code HEAD + patch + required untracked contents; environment locks; explicit source, decision, rules, schema, taxonomy, FX, registry, metric/display, benchmark and threshold manifests; permitted read/write roots; execution-budget reference. |
| Artifact entry | Logical key; root and relative path; SHA-256; byte length; media type; ordered schema fingerprint and rows for tabular data; producer stage/partition/version; input fingerprint; immutable dependency references. |
| Stage result | Candidate/attempt/stage/partition; start/end UTC; process ownership; execution outcome; quality outcome; complete output-manifest hash; checks and issue references; resource use; exact next action on failure. |
| Completion record | Stage input fingerprint; result-manifest hash; required artifact list; successful integrity-check references; committed time and writer identity. Presence alone is insufficient without verifying its references. |
| Adoption event | Actor; explicit approval reference; expected accepted parent; complete release descriptor hash; evaluation/delivery seal references; old/new pointer hashes. Programme work prepares this record but does not fabricate owner approval. |

JSON uses UTF-8, fixed key ordering, explicit nulls and versioned canonical encoding for fingerprints. Hash the canonical record content without a self-hash field. Artifact SHA-256 covers exact bytes; a separate semantic table fingerprint uses declared column order/types, stable key order and versioned numeric/null encoding. ZIP/Parquet metadata, operational timestamps and absolute machine paths must not create false data differences. Byte verification protects reuse; semantic comparison establishes twin-build equality. Save both.

Stage commit procedure:

1. Acquire candidate/task ownership; check PID, process creation time, command identity and lease. A stale heartbeat alone does not authorize a duplicate long job.
2. Verify all pinned inputs and declared predecessor completion records. Fingerprints include producer code, schemas, environment, rule plan and registry inputs, not merely file names.
3. Write outputs into an attempt-local temporary bundle. Close writers, reopen and verify types, keys, counts and hashes. Save complete diagnostics even when the quality result is FAIL.
4. Finalize the bundle to a new, unused results path. Write and flush the result manifest; publish its small completion record last using same-volume replacement under the coordinator lock. Readers consult committed manifests, never partially populated directories.
5. Record the event and update the disposable progress index. Recovery can reconstruct the index from verified manifests/events.

Do not assume several file renames are one filesystem transaction. An absent/invalid completion record means the entire bundle is incomplete, even if individual files look usable. A disk-full, sharing violation or failed final replacement leaves the old accepted state intact. Test these cases on the Windows execution environment before claiming interruption safety.

Shared extraction-cache insertion uses the same manifest-last protocol and a per-fingerprint writer claim. A competing producer verifies and reuses a completed matching bundle; it does not overwrite it. Different results for the same fingerprint are a determinism failure. An interrupted producer's temporary files are never visible as a cache hit.

Execution states are `pending/running/complete/failed/interrupted`; quality states are `not_evaluated/pass/fail/unassessable`. A complete FAIL evaluation is reusable evidence. It is not permission to run accepted-release delivery. Diagnostic previews have an explicit diagnostic role and cannot satisfy the ready gate.

## 7. Environment, resume and agent work records

Freeze the exact code used, including relevant dirty and untracked files; the current worktree cannot be reconstructed from HEAD alone. Use an isolated checkout/source snapshot for execution while preserving the user's tree. Pin Python packages, DuckDB/dbt adapter, Node lockfile, offline Arelle/taxonomy/plugins if evaluated, and viewer assets. Save the environment verification output. Do not silently upgrade dependencies on resume; the earlier dbt spike's environment findings still apply.

Task records live durably with the run, including objective, allowed paths, input hashes, hypotheses attempted, patch/artifact locations, validation results, next safe action and stop reason. Save after each meaningful result and before external work; checkpoint a short progress record at most five minutes apart while actively working. Long deterministic processes emit separate progress/ownership records so their existence can be checked after a conversation ends.

On restart, load the task record and verified stage manifests first, then only the source files needed by the next action. Reuse existing source extraction and admitted enrichment results. If a model request was dispatched, retain its request/input identity and response or `outcome_unknown`; an unknown outcome is not an automatically free retry. No model work happens within a deterministic candidate build.

The design assumes the agent or local process can disappear. It does not depend on a promise about usage-window pause/termination behavior. Lost uncheckpointed reasoning cannot be recovered; persisted code, evidence, completed stage bundles and task decisions can be.

## 8. Acceptance, publication and restore

P07 seals data and identities. P08 emits an immutable evaluation bundle against that seal. P09 prepares the static site and document/contributor assets. P10 verifies the actual delivery, binds it to the data/evaluation seals and prepares the review pack. Ready requires approved gate definitions, complete assessability accounting and passing mandatory data/delivery/regression checks. A missing reference measurement does not become a pass because the build ran successfully.

Adoption and publication are separate events after programme completion. Under the single integration lock, verify approval, the expected current parent and every release dependency, then replace the small accepted pointer last. Registry adoption follows this same pointer. A deployment changes the published pointer only to an approved, complete delivery descriptor. Keep the previous complete descriptor for rollback. Frontend assets use immutable release-qualified paths so a stale page cannot fetch a newer generation's shards.

The current static exporter does not implement these pointers. Its migration must stage the complete deployable output and exercise mixed-generation rejection before any production transition. Keep compatibility copies under existing paths consistent under the integration lock; they are not a safe concurrent publication protocol by themselves. Do not present a new JSON metadata flag as proof that existing consumers obey the seal.

Retain accepted release descriptors, registry/revision history, reference/decision versions and every referenced source/evidence/delivery artifact. Do not automatically expire failed candidates in the initial implementation: first produce a dependency-aware retention report, protect reproducibility and any active investigations, then apply a separately established retention policy. Scratch remains disposable and must not hold the only copy of a release dependency.

Extend the existing R2 plan to cover the complete dependency manifest, including accepted registries and relevant code/environment snapshots. Cloudflare setup and backup verification remain outstanding; no backup is claimed by this design. Preserve the [phase-1 exception and gates](phase1_parquet_migration_plan.md): additive companions/reader work may precede R2, but CSV retirement/baseline refresh cannot bypass the required backup and restore drill. The canonical holdings CSV remains supported.

A restore drill uses a separate directory and verifies manifest closure, hashes, registry IDs, one replayed stage, a complete sealed data query and representative source/citation navigation. A rollback points to the previous complete approved bundle. Neither operation refreshes the official baseline to hide a discrepancy.

## 9. Required implementation proofs

| Scenario | Required outcome |
|---|---|
| Trial path with wrong column order/type | Hard failure, including strict Parquet companion handling outside production roots. |
| Crash after one output or after allocation | No partial stage reuse; same valid IDs on retry; accepted files unchanged. |
| Input edited with the same name/size | Hash change prevents checkpoint reuse and requires a new candidate. |
| Two candidates based on the same parent | Only the first approved adoption can advance it; stale-parent adoption fails. |
| Old-quarter insertion or source amendment | Correct invalidation of histories/donors/evidence; accepted IDs retained or explicit revision. |
| Missing benchmark / complete failing evaluation | Explicit unassessable/FAIL and residual evidence; never ready. |
| Corrupted cached blob or missing release dependency | Reuse/restore/adoption fails before serving mixed or incomplete data. |
| Exact totals and malformed monetary token | All public partitions agree exactly; unsupported numeric representation fails visibly. |
| Stale frontend page | Uses its complete old bundle or reports unavailable; never mixes data and citation generations. |
| Clean twin build and protected-output inspection | Equal semantic data/IDs; no production artifact drift from trials. |

This records the proposed physical design. FX/date and identity conventions are supplied by the later units/identity contract. Full production migration, automated reference admission, real-rate integration, complete runtime/recovery verification and final acceptance remain implementation obligations. Current progress and the withdrawn specification-readiness claim are recorded in [specification status](programme_spec_status.md). Documentation completion is not a production readiness verdict.
