# Offline programme candidate runner

The supported entry point is `python -m pipeline.programme.runner`. It builds an isolated candidate from frozen cached inputs, verifies each completed stage, and leaves production adoption to a separate decision. Financial correctness is evaluated separately from successful execution.

**10 September run status: three stages complete; tranche stopped during full-suite verification.** The stronger environment inventory and real preflight passed. Candidate `t1-runtime-20260910-v5` has sealed unified, identity and evidence stages, with all 11 typed pairs matching. Full pytest timed out and created six empty native query-cache files in protected output directories. The agreed stop rule applies; the cache-isolation fix has since passed 54 query/orchestration tests in a separately authorized bounded investigation; the production regex-validator correction and full-suite verification remain open. Integrated financial measurement and the actual recovery drill remain unrun. See the [handoff](programme_tranche_handoff_2026-09-10.md) and [authorized resume proposal and outcome](programme_tranche_resume_proposal_2026-09-10.md). Earlier v3 output remains unsealed and cannot be reused.

This first implementation supports the existing holdings, identity and PIK builders. It establishes their execution boundary; it does not implement the target schema, dbt migration, durable position registry, all-in rate migration or public citation product.

## Run and recover

Use the same Python environment as the frozen runtime. Windows requirements are listed in `requirements-programme-windows.txt`; the installed native Codex CLI supplies its **command-only** sandbox. These commands do not invoke an agent or model. The current workstation can start this sandbox from its ordinary terminal; administrator access does not fix a blocked input or invalid artifact.

```powershell
python -m pipeline.programme.runner snapshot --candidate my-candidate
python -m pipeline.programme.runner canary --candidate my-candidate
python -m pipeline.programme.runner preflight --candidate my-candidate
python -m pipeline.programme.runner run --candidate my-candidate --stage unified
python -m pipeline.programme.runner run --candidate my-candidate --stage identity
python -m pipeline.programme.runner run --candidate my-candidate --stage evidence
python -m pipeline.programme.runner verify --candidate my-candidate --stage evidence
python -m pipeline.programme.runner restore --candidate my-candidate --stage evidence
```

The default starting snapshot is `spec-close-20260909-v2`. A new source population requires a new frozen input producer; pointing this adapter at arbitrary current files is not a supported substitute. Candidate names are unique and cannot replace existing snapshots.

Repeat a `run` command to reuse a completed stage after verification. A missing completion marker means incomplete work, even if CSVs exist. A failed worker must be stopped before retry; the controller permits an initial attempt and one retry within a candidate. Preserve failures and count retries across replacement candidates in the tranche ledger as well. Changing names is not a retry-budget reset.

`restore` creates a verified local copy under the same candidate. It does not publish, refresh a baseline or switch an active release. `canary --timeout-probe` exercises worker termination and verifies that protected scratch files survive.

For the dated integrated evaluation:

```powershell
python -m scripts.programme_tranche.measure_candidate --candidate my-candidate --evaluation evaluation-v1
```

Use a fresh evaluation name. This command is tied to the current tranche's obligations, reference pack and frozen starting candidate. The reusable evaluator is `pipeline.programme.measurement.evaluate`; new measurement producers must supply their own pinned observations and evidence.

## What completion proves

Each candidate records the complete file inventory of its frozen inputs and the content of the installed Python runtime and distributions. Each stage binds that snapshot, runtime, typed artifact contract, controller code, parent result and exact parent holdings. The controller and frozen worker code have separate identities, so a later controller is never described as the code that produced an earlier worker result.

The worker writes to a new attempt directory. A required preflight executes the actual three builders on small cached samples, including cross-quarter matching, in the same boundary. Its separately hashed outputs are never accepted as completed candidate stages. After each full worker exits, the controller verifies termination, read-only input preservation, the complete runtime identity, consumed runtime dependencies, required files, ordered columns, strict types and CSV/Parquet equality including duplicate multiplicity. It rejects correction-audit execution errors from every admitted store. It flushes the bundle, records hashes, and writes the completion marker last. Empty required outputs still need typed companions.

Completed execution can have financial quality `FAIL` or `UNASSESSABLE`. It grants no release approval. Missing source facts, unreviewed labels and missing measurements cannot become a passing result merely because a process finished.

## Isolation and limits

The worker uses the installed Windows Codex sandbox, disabled network access, a low-integrity Windows token, and a one-process job with a 12 GiB private-memory ceiling. Only new candidate output, bundle, temporary and telemetry directories receive low-integrity write labels. The original project, references and baseline are never relabeled.

This extra Windows integrity boundary is necessary on the tested installation: the base sandbox denied write opens but did not stop Arrow's failed-write cleanup from deleting a disposable protected canary. The combined boundary must pass Python, DuckDB, Arrow, deletion and rename canaries before a build. These checks target scratch files, not production assets. Windows' default no-write-up policy is described in [Microsoft's integrity-control documentation](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control); the command sandbox is documented in [OpenAI's Windows guide](https://learn.chatgpt.com/docs/windows/windows-sandbox).

Python auditing and locked DuckDB settings provide additional restrictions. They are not the native security boundary. Legacy configuration receives pre-created cache directories and an explicitly empty candidate-local `.env`; it cannot obtain ambient credentials through an upward dotenv search. No source downloads or enrichment calls are permitted.

Worker ceilings are 90 minutes for unified holdings, 60 for identity, and 15 for evidence. Runtime fingerprinting, copying and controller verification add overhead and are reported separately. `--deadline` performs a remaining-time preflight; the tranche operator must also reserve verification and handoff time. A global heavy-job lock prevents overlapping builds, matching jobs or a full pytest suite. A stale lock never implies its worker has stopped.

The backend currently supports this Windows environment only. It fails closed when its sandbox dependencies are unavailable. Runtime content pinning deliberately rejects environment changes and currently adds substantial startup work. Operating-system identity is its Windows build, not a hash of every operating-system file. Native runtime loading remains within the trusted installed OS/runtime boundary.

## Measurement and review controls

`contracts/working-v1.json` contains the owner's amendable numerical targets. It is separate from the live quarter-acceptance thresholds. The catalogue includes all 28 programme criteria. Every missing metric emits a non-pass state; partial-quarter and selected-example results cannot pass a whole-history requirement.

Observations retain candidate identity, population, units, formula, counts, uncertainty where applicable and hashed evidence. Reference-dependent accuracy also requires an independent reviewer, a version-bound attestation and suitable exposure status. Previously exposed examples remain development evidence; they cannot certify sampled population accuracy.

`compare_amendment` evaluates old and proposed numerical contracts on the same candidate and observations, retaining the old contract identity, rationale, evidence and both results. A population change requires new observations. A comparison does not approve a material change in accepted risk.

The controller and evaluator are trusted code under owner control. Review attestations are auditable files, not cryptographic proof of a human's identity. A worker cannot promote its own labels or edit the controller-owned completion files; owner review remains a real governance step.

Current results and limitations are recorded in [the tranche work record](programme_tranche_2026-09-10_work_record.md). Do not infer a successful full run or full test suite from this usage document.
