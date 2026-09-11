# One additional candidate attempt: strengthened and authorized

Owner authorization, 10 September 2026: **"update your proposal and run it"**, following the dependency-completeness discussion. This authorizes the stronger preflight and one additional fresh unified attempt. The original deadline remains 16:43:01 UTC. Independent source-review authority remains unassigned.

## Execution outcome and remaining correction

The authorized additional attempt **succeeded**. The complete 247,333-file runtime inventory, native canary and real three-stage preflight passed. Fresh candidate `t1-runtime-20260910-v5` completed unified holdings (780,425 rows), entity/position matching (497,451 assigned pairs) and PIK evidence (780,425 statuses). All 11 typed pairs agreed and each stage was sealed after its dependency checks. The original omitted-metadata defect is resolved for these exercised workloads; this is not a claim to inventory the trusted Windows OS boundary or prove every possible future branch.

**The tranche subsequently stopped during full-suite verification.** The suite reached its 90-minute controller allowance before finishing, with one failure marker and no final traceback. Its outer guard found six newly created, zero-row DuckDB cache files under `data/output/agent_investigate/_qcache/666/` and `/999/` (9,580 bytes total). All 237,621 original protected files retained size and modification time. No original file was deleted or overwritten by this observed incident; these checks do not hash every protected file.

The mechanism is specific: `prep()` prewarms `agent_data_query.describe()`. Orchestration tests mocked one output root but left the query module's separate cache root and real default sources active. Native DuckDB `COPY TO` bypasses the Python file-open guard. The full-suite timeout prevented pytest's own session-finish inventory check; the outer controller still detected the writes.

The concrete fix now prepared in `tests/conftest.py` redirects that cache to each test's temporary folder. `tests/test_investigation_orchestration.py` supplies an empty synthetic source map for orchestration-only prewarming; `tests/test_agent_data_query.py` adds a file-backed regression case retaining CIK filtering and a real temporary cache. Production query behavior is unchanged. **The fix is untested:** no pytest or candidate workload runs after the stop. The earlier 68 passing focused tests predate it.

This fixes the observed path. The existing full-suite harness still detects other native writes after execution; it does not provide the same preventive native write boundary as the candidate worker. Retain that limitation explicitly. A further unattended test run should add preventive protection for the production roots, preserve per-test progress and failure details as they occur, and retain the outer inventory check. Neither the fixture change nor the earlier passing preflight proves all tests are isolated.

After the stop is resolved, verify these two test files with protected-output checks, identify the earlier full-suite failure, and finish full-suite verification with adequate measured time. Preserve each failed result. Then validate the existing sealed candidate identities and perform integrated comparisons, programme measurement and the actual timeout/reuse/restore drill. Rebuilding holdings is only necessary if relevant frozen inputs or execution code changed; test-fixture changes alone do not justify repeating it. Do not silently increase a time allowance, drop cache-dependent tests or treat incomplete verification as a pass.

This new stop follows the existing [approved tranche](programme_execution_tranche_2026-09-09.md) instruction: **"Stop the tranche for attempted writes to protected production/reference/baseline assets"**. The authorization above addressed the earlier dependency-identity stop and one additional attempt; it did not remove this separate boundary. The [handoff](programme_tranche_handoff_2026-09-10.md) records completed work and the evidence still missing.

Automatic approval review rejected removal of the six cache files as **"blocked by policy"** and supplied no further reason. No cleanup occurred or alternate removal was attempted; all six files and their forensic copies remain.

## Strengthened dependency checks

Inventory the complete installed Python environment and user package tree by actual file content, including package data, native libraries and configuration, rather than relying on package file lists or selected suffixes. Exclude only bytecode caches that execution explicitly redirects into a fresh candidate-local directory. Retain the trusted Windows operating-system boundary explicitly; this does not claim to hash every Windows system file.

Before the expensive build, run bounded representative workloads for unified holdings, entity/position matching and PIK evidence through the same frozen bootstrap, write boundary and dependency checks. Keep their outputs separate from real candidate results. Capture their actual Python/runtime reads and verify them against the pre-run inventory; imports alone are insufficient. Retain full runtime checks during and after the real stages. Any unrecorded input remains a failure.

The preliminary workloads establish exercised-path coverage, not proof of every possible branch. Full environment capture and continued enforcement address paths that those workloads do not exercise. Preserve explicit evidence of what each preflight ran and its limits. No third-party downloads or package installs are needed.

Hashing uses eight threads with at most 512 queued files at a time. This overlaps Windows file-open latency while retaining a content hash and before/after change check for every file. A preliminary sequential snapshot was stopped before its ten-minute ceiling; the single diagnosed snapshot retry uses this bounded implementation. No holdings build was started in that preliminary snapshot.

Reserve at least 90 minutes for the full suite and the final hour for integration/preservation/handoff. Use measured runtimes to bound the remaining stages; start no job that cannot fit the remaining original window. Stop on a new unexplained dependency or exhausted additional attempt rather than retroactively certifying it.

The authorized tranche stopped at 10:38 UTC. This is a runtime inventory defect, not an administrator-permission problem. The remaining original time window ends at **16:43:01 UTC on 10 September**.

The worker completed 780,425 holdings and its two typed output pairs in 39.91 minutes, then exited successfully. The controller found that `setuptools-78.1.1-py3.13.egg-info/entry_points.txt` had been read without a recorded pre-run content hash. It correctly wrote no completion marker. Matching, PIK, programme measurements and recovery tests were not started. The unsealed output is retained for diagnosis, not adopted or passed to descendants.

## Concrete correction

The local change in [`pipeline/programme/native.py`](../../pipeline/programme/native.py) inventories the complete physical Python environment and user package tree, including arbitrary data/configuration and legacy metadata. The measured tree contains 247,333 files and 11.97 GiB. Worker executable/DLL search paths are restricted to the pinned Python and sandbox locations plus the explicit trusted Windows boundary. Python opens reject existing runtime files absent from the inventory; complete content checks run before and after full stages. Inventory limits are 20 GiB, 300,000 files and ten minutes per check.

[`tests/test_programme_runtime_metadata.py`](../../tests/test_programme_runtime_metadata.py) covers legacy manifests with empty file inventories, arbitrary physical assets, both package roots, changed and added metadata, and immediate rejection of undeclared runtime inputs. [`pipeline/programme/preflight.py`](../../pipeline/programme/preflight.py) executes real small holdings, identity and evidence workloads under the same worker boundary. It caps input/output rows and excludes promoted correction stores from its small sample; the real unified stage must still execute and audit every admitted correction. The final handoff records actual test and execution outcomes.

The old executed controller source, original runtime manifest and read ledger remain available in the [failure evidence](programme_tranche_evidence_2026-09-10/runtime-failure-v1/result.json) and original candidate. Current hashes of the omitted file are diagnostic only; they cannot establish its pre-run state.

## Authorized exception

The owner authorized **one additional unified build attempt**, beyond the initial execution and one diagnosed retry already consumed. Use a fresh snapshot with the corrected inventory, a fresh native canary and a verified three-stage preflight. Keep the original 16:43:01 UTC deadline, 90-minute unified worker ceiling, 12 GiB memory ceiling, one heavy job, and zero SEC/paid calls. Start dependent stages only when they and required verification/handoff can fit the remaining time. The existing incomplete attempt must not be retroactively sealed.

If this additional attempt fails, retain it and stop. Full pytest, the actual timeout/reuse/restore proof, integrated measurements and preservation checks remain prerequisites to claiming the engineering tranche complete. Independent reference review remains separately pending.

The original authority boundary comes from the [approved tranche](programme_execution_tranche_2026-09-09.md): **"One diagnosed execution retry per job"** and **"Stop the tranche for ... missing input identity"**. The owner's subsequent instruction above grants this one additional attempt with stronger preflight; other limits remain in force.
