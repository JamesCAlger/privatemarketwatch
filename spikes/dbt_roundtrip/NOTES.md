# Spike ergonomics log (kill-criterion-3 evidence)

Append one line at start/end of each task: [YYYY-MM-DD HH:MM] Task N start|end - note.
Record every framework workaround (dbt quirk, config fight, docs gap) as its own line.

[2026-09-02 20:35] Task 1 workaround: dbt-duckdb install would upgrade protobuf 5.29.5->6.33.6 (major breaking version). Installed dbt-duckdb (1.11.0) + dbt-core (1.12.3) in isolated .venv/ instead of shared conda env to avoid conflict with pytest suite. dbt --version confirmed both plugins working.
[2026-09-02 21:10] Task 2 start - ground-truth extractor; parquet input confirmed 2026-09-02 20:19
[2026-09-02 21:46] Task 2 end - exit 0; staged 576590 rows in 2141s (slow: concurrent Q1 pass); top CIKs 0000017313/0001959604/0001959568; dup groups 1000; dropped rows 1004; empty-ctx 0
[2026-09-02 21:46] Task 2 sanity check - top CIK-quarter: 0001959604 / 2026-03-31 / 96 dropped rows
[2026-09-02 22:58] Task 2 review audit: three concurrent instances launched (PIDs 21060, 17624, 8780). All instances deterministic and produced identical output. PID 17624 crashed (OOM/tee issue, no artifacts). PIDs 21060 and 8780 both wrote artifacts; artifact internal consistency verified post-hoc (1000 groups; sum(group_size-1)=1004=dropped rows). No stray process remains.
[2026-09-02 21:54] Task 3 start
[2026-09-02 21:56] Task 3 friction: dbt models default to VIEW not TABLE; spike.duckdb ends up with views + stored-failure audit tables only (no materialized tables). Not a problem for this spike but differs from production pattern.
[2026-09-02 21:56] Task 3 friction: python -c with nested double-quotes fails in PowerShell 5.1 due to quote-mangling. Workaround: wrote temp .py script, ran python <script>, deleted script.
[2026-09-02 21:56] Task 3 end - 2 models OK; duplicate_dimension_paths FAIL 2004 (expected); dedup_output_unique PASS; provenance source_row_id all populated as src:{acc}:{ctx}; kill criterion 1 CLEAR
[2026-09-02 23:30] Task 4 start
[2026-09-02 23:30] Task 4 TDD RED - import error (expected): ModuleNotFoundError: No module named 'failures_to_packet'
[2026-09-02 23:31] Task 4 TDD GREEN - 4/4 passing (test_one_packet_per_group, test_packet_contents_and_provenance, test_deterministic_order, test_missing_table_raises)
[2026-09-02 23:31] Task 4 real-run result - wrote 1000 packets (expected: dup groups == packet count); sample packet has real src:{accession}:{context} ids; deterministic, correct schema
[2026-09-02 23:31] Task 4 end - commit 984783c
[2026-09-02 23:40] Task 5 start - equality proof + twin-build hash + incumbent comparison
[2026-09-02 23:40] Task 5 friction: script must run from spikes/dbt_roundtrip/ cwd; spike.duckdb views resolve parquet path relative to that dir; running from repo root gives IO Error. Not a dbt bug -- VIEW re-executes at query time against relative path baked in at dbt run time.
[2026-09-02 23:41] Task 5 Step 2 result - groups_match: True (packet 1000 vs ground truth 1000); dropped_row_identity_match: True; exit 0; incumbent mechanisms for spike CIKs: ['blocking_source_position_like_parser_mismatch', 'documented_jv_lookthrough_axis', 'blocking_source_pct_leaf_parser_mismatch']
[2026-09-02 23:43] Task 5 Step 3 twin-build hashes - hash1 (pre-dbt-run): bf8de820f32778e3553bd9531edf773c; dbt run PASS=2; hash2 (post-dbt-run): bf8de820f32778e3553bd9531edf773c; IDENTICAL - determinism confirmed.

## Task 5 Step 4 - Kill-criterion-2 incumbent comparison

Spike CIKs: 0000017313, 0001959568, 0001959604.
Incumbent artifact (source_reconciliation_residual_classification.csv) records 12 rows for these CIKs under mechanism=documented_duplicate_dimension_path / status=collapsed_duplicate_dimension_path. That is the full extent of the incumbent's localization: a post-hoc label applied at reconciliation time, with no boundary_model attribution, no downstream_fix_model pointer, and no per-group source_row_ids. The packet produced by this spike provides boundary_model=bdc_dim_ranked (the exact dbt model where dedup occurs), downstream_fix_model=bdc_dim_deduped (the model to patch), and the full set of source_row_ids per duplicate group -- directly actionable for a targeted dbt model fix. For the spike CIKs' duplicate-dimension rows, boundary_model + downstream_fix_model + per-group source_row_ids are strictly more actionable than the incumbent mechanism label: the incumbent identifies that dedup happened; the packet identifies where to intervene and which rows to inspect. The incumbent also carries 5,068 rows of blocking_source_position_like_parser_mismatch for these same CIKs -- a separate defect class outside the dbt dedup scope, confirming the spike is scoped correctly and is not over-claiming coverage.

[2026-09-02 23:50] Task 5 end - commit below
