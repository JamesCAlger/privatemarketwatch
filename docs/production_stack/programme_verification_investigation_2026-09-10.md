# Why verification stopped

Investigation requested by the owner after the eight-hour tranche stopped. This is a separate, bounded diagnostic exercise. The completed candidate remains sealed; its financial acceptance and recovery checks remain unfinished.

**Outcome: the original failures are explained, the test isolation and stale expectations are repaired, and one production-validator correction remains.** The final selection completed with 61 passes and that one known failure. Production pipeline code and wrapper rules were not changed. The [commentable review page](programme_tranche_review.html) carries the short version; [retained results](programme_tranche_evidence_2026-09-10/verification-investigation-v1/result.json) contain the counts, timings and preserved failed attempts.

## The failure count needs correcting

The original log contains **four failure markers**, not one. The earlier handoff miscounted them. The original log and the preserved forensic copy have the same SHA-256 (`a33962c7113d6504c2aed3c23ed39201fab0b04f70b9f6e1833d0262abc48cb5`). The old sealed handoff is retained as historical evidence, with this explicit correction.

Fresh collection found 5,110 tests. Removing the one regression test added after the original run gives an inferred original collection of 5,109. Mapping the 4,093 saved progress symbols identified four candidate failures; all four subsequently reproduced with saved tracebacks. The mapping depends on unchanged collection order because the original run did not preserve its collection manifest.

Three tests expected old wrapper rule IDs: Trinity V3 instead of V5, BlackRock Direct Lending V1 instead of V2, and Silver Point Specialty Credit V1 instead of V2. Those wrapper versions changed in committed repair `6b4391a` on 7 September. Updating the four stale expected IDs made all three complete tests pass, including their classification assertions. No wrapper was changed.

## The fourth failure checks the wrong regex language

The wrapper-consistency validator uses Python's `re.compile` for staging expressions that actually execute in DuckDB. The Goldman Sachs BDC issuer expression contains `\x{2013}`, `\x{2014}` and `\x{FFFD}` escapes: valid DuckDB syntax, rejected by Python.

The read-only inventory checked all 77 version-2/version-3 wrappers. Goldman Sachs was the only wrapper with a hard coherence error. A separate probe compiled 106 staging expressions through DuckDB. All compiled after applying the pipeline's existing Unicode decoding. Four separator variants extracted the expected issuer; malformed expressions, lookbehind and backreferences were rejected.

That preprocessing is essential. SCP's raw expression uses `\u` escapes that DuckDB initially rejects, but the existing staging code decodes them before execution. It is not another production failure. Simply swapping `re.compile` for a raw DuckDB call would introduce a false alarm there. The syntax probe leaves industry placeholder tokens symbolic; representative staging tests exercise actual expansion and SQL execution.

**Required correction:** keep Python validation for dispatch expressions; validate staging expressions using DuckDB after the same preprocessing used at runtime. Retain rejection tests for malformed expressions and Python-only constructs. Do not weaken the coherence test or alter a working financial wrapper to satisfy the wrong validator. This production-validator correction is not applied during this investigation.

## Why tests wrote six files into production output

Investigation preparation calls `agent_data_query.describe()` to prewarm a query cache. Its cache directory is a separate module-level setting. The orchestration tests redirected their own output directory but missed this cache setting and continued using real default source files.

DuckDB writes the Parquet cache through native code. That bypassed pytest's Python `open()` guard. Pytest's final metadata check never ran because the suite timed out; the outer controller still detected the six additions. The files are empty query caches for synthetic CIKs 666 and 999, totalling 9,580 bytes. This incident did not overwrite existing holdings files according to the recorded size/mtime inventories; those inventories are not complete content-hash verification.

The prepared repair redirects every test's query cache into its temporary directory. Orchestration-only fixtures also provide empty synthetic query sources. A separate real file-backed test proves that temporary cache materialization and CIK filtering still work.

The new diagnostic controller adds a preventive native-write boundary, a positive/negative Python/DuckDB/Arrow canary, immediate per-test tracebacks and progress, process/memory/time limits, and full outer before/after inventories. It does not rely solely on Python file interception. Stable unreadable historical worker-secret directories are disclosed by the restricted worker and checked by the full-access parent; no secret contents are read.

## Why the test run was slow

The two representative synthetic BDC tests each took about 170 seconds under profiling. The production field-status overlay is 295,981,590 bytes. Both fixtures reached its loader and processed the large unrelated dataset: the profile records 4,273,203 calls to the bridge's text normalizer and 157.5 cumulative seconds inside the overlay function across the two tests. This is a measured contributor, not a claim that it explains every second of the full-suite timeout.

A class-scoped test fixture now points the 59 synthetic BDC staging tests to an absent temporary field-status artifact. The dedicated integration test still supplies a real synthetic CSV and checks both filling a blank lien and preserving an existing keyword-derived lien. Production overlay code is unchanged. The first two repaired staging cases still took 65.6 and 81.9 seconds under profiling. The 59-case diagnostic attempt therefore could not fit its 15-minute budget: it was stopped after 574 passing test calls, with completed per-test results retained, and verification narrowed to four representative staging/integration cases. The whole class has not passed as a completed job.

The two original examples subsequently passed in **80.7 seconds instead of 169.5**, and **74.1 seconds instead of 169.6**, with cProfile enabled in both runs. The remaining parse/deduplicate phase took **68.7 and 63.3 seconds**, even for three input rows; filtering took 9.7 and 8.3 seconds, and final classification 0.5 and 0.6 seconds. This localizes the residual staging cost. It does not distinguish SQL planning from SQL execution or prove that the old 90-minute full-suite allowance is now adequate. A future optimization must preserve filer/global-rule behavior, or verification needs a sufficiently measured allowance.

The Goldman Sachs staging case passed in 75.1 seconds. The overlay integration case passed in 224.5 seconds; only 64.8 seconds were logged inside its BDC staging phases. Its remaining time was not separately diagnosed.

The verification controller also inventories roughly 238,000 protected files. Its overhead needs a separate time allowance. Collection alone is not free, and profiling adds overhead of its own. None of these observations justifies declaring a partially completed suite a pass.

The broad `diff_outputs.py --semantic` command first hashes and byte-compares the full baseline manifest, then performs semantic comparisons. Its earlier timeout therefore did not establish a failed semantic comparison. The new bounded attempt invoked that existing CLI in a child process, but the child failed while importing DuckDB (`DLL load failed`) before comparison began. The exact child-loader cause was not diagnosed; this is a diagnostic execution limitation, not evidence of a financial-data difference. The existing five-artifact semantic comparator subsequently completed in the main restricted worker. The retained records distinguish that narrower completion from the failed full command; there is no full byte-scan pass.

## A further reporting defect found during diagnosis

In the reproduction job the sandbox launcher returned zero while the durable pytest worker record returned one and JUnit contained four failures. The first diagnostic controller recorded only the launcher's code. That original record is preserved and explicitly qualified; the job is a reproduced failure, never a pass.

The corrected controller reads the worker's saved result and JUnit as well as the launcher result. A missing completion record or missing test report cannot count as success. Failure tracebacks are flushed as each test finishes, so a later timeout cannot erase earlier evidence. The final run verified failure propagation: the launcher returned zero, the worker returned one, JUnit recorded one failure, and the controller correctly returned one.

The first repair-verification attempt then exposed a diagnostic progress-file problem: Windows denied `os.replace` of the frequently updated `current_test.json` after 144 tests passed. A reader holding that file can prevent replacement; the exact holder was not established. The worker recorded an internal error, and the corrected controller returned a failure. Progress now uses append-only events, eliminating this replacement operation. The failed attempt and executed controller source are retained.

## Results and next action

The final selected test run completed **61 passed / one failed**. All 54 cache/query and orchestration tests passed, as did the three repaired wrapper-version cases, the two original staging examples, Goldman Sachs staging, and the real file-backed overlay integration case. The only failure is the unchanged production regex validator. That negative result also checks that the diagnostic controller does not mislabel a failing test run as a pass. The separate broader attempt retained 574 passing calls but was stopped and is not a completed-suite result.

All seven diagnostic attempts ended with their workers stopped and no further changes among **237,627 protected output files**, measured by size/mtime inventories. Native canaries verified permitted scratch writes and denied writes, deletion and renaming outside that boundary. The six original cache files retain their incident hashes.

The [post-test preservation check](programme_tranche_evidence_2026-09-10/investigation-preservation-v1/result.json) passed in 77.6 seconds: **1,117 frozen pipeline/data/control inputs**, **1,605 matching-reference files**, original gold and both source-reference freezes retain their hashes. The five-artifact semantic comparison found no material change from preparation under the unchanged numeric-noise rule. Existing official-baseline differences remain: holdings 11 groups, matches 7, position returns 7, index returns 6, fund financials zero. This is not a clean-baseline or complete historical-tree content-hash claim.

The original full suite remains incomplete. The investigation does not establish portfolio accuracy, calibrate the 50 programme metrics, or complete the candidate recovery drill. No production rebuild/export, frontend application build, downloads, paid enrichment, adoption or delegated agents ran. The existing full-suite harness still needs the diagnostic boundary and durable reporting integrated before another unattended run.

The next full verification run should use preventive native isolation, persistent failure reports and a measured time allowance. After that, reuse the sealed candidate only if its recorded dependencies still match, and finish integrated financial measurement and recovery verification. Test-fixture repairs alone do not require another holdings build.

The updated commentable review passed browser checks: 32 comment boxes, 39 local links, bracket/Unicode/literal-newline preservation, save/download, mobile layout and print, with no external requests or browser errors. Native save-writer and cancellation paths used stubs; the operating-system dialog was not automated. The owner's saved comments file retains its original hash.

The six cache files remain in place. Automatic approval review previously rejected their removal as **"blocked by policy"**, without a further reason. This investigation did not retry removal or use an alternative cleanup route.
