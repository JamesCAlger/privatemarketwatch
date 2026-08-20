# Dispatching sandboxed Codex worker fleets

How to run fleets of sandboxed Codex agents from the terminal (the pattern behind Agents A/B and the
anchor adjudicator). Task-agnostic: copy this for any new agent set. Run from an OPERATOR shell --
conda-activated, `codex login` done, OUTSIDE a Codex session (the runner refuses to dispatch from
inside one, to avoid recursion).

## The two reusable primitives

- **`scripts/setup_codex_worker_harness.ps1`** -- builds a sandboxed worker home + runroot and the
  filesystem ACLs:
  - `-WorkerHome` / `-WorkerRunroot` -- per-worker scratch (CODEX_HOME) and the `-C` / apply_patch
    project boundary. Keep them SHORT (Windows MAX_PATH; see gotchas).
  - `-WriteDirs <string[]>` -- the only dirs the worker may write to. Must CONTAIN the dir the worker
    is told to write its output to (e.g. the rules/leaf dir), or the patch tool says "outside project
    boundary".
  - `-ReadDirs <string[]>` -- extra read grants: the repo root PLUS the worker interpreter's install +
    ALL its site-packages roots.
  - `-EnvInherit core|all` -- `all` carries the operator PATH (conda/venv) so the named interpreter's
    DLLs resolve; `core` is a minimal env.
  - `-AllowUserSite` -- keep `%APPDATA%\Python\...\site-packages` on `sys.path` (where project deps
    often live). Off by default.
- **`scripts/run_codex_worker.ps1`** -- runs Codex against a prompt file:
  - `-PromptPath` (required), `-WorkerHome`, `-WorkerRunroot`, `-CodexBin` (default `codex.cmd`),
    `-NoSetup` (skip the setup call when you've already run it).
  - `-TraceDir` / `-TracePrefix` -- where the harvested rollout trace lands (see "Rollout
    traces" below). Dispatchers pass their batch logs dir + a per-worker prefix; default is
    `<WorkerHome>\traces` so no caller loses the trace.

## The dispatch loop (per target)

Mirror `scripts/dispatch_investigation.ps1` -- the cleanest end-to-end example. Per target it:

1. **Build the prompt** to a file (the agent's whole instruction + the absolute tool paths it may call).
2. **Resolve read grants** -- repo root + the interpreter's site-packages, via
   `scripts/agent_b/dispatch_preflight._worker_read_dirs` (do NOT hand-roll the list; PowerShell
   quoting mangles it). Emit one path per line and collect into a flat `string[]`.
3. **Set up the sandbox:**
   `& setup_codex_worker_harness.ps1 -WorkerHome $wh -WorkerRunroot $base -WriteDirs @($base) -ReadDirs $grants -EnvInherit all -AllowUserSite`
4. **Copy auth:** `Copy-Item <operator CODEX_HOME>\auth.json $wh\auth.json` (the worker gets a FRESH
   CODEX_HOME -> without this it hits 401 Unauthorized). Or set `CODEX_API_KEY`.
5. **Run the worker:** `& run_codex_worker.ps1 -PromptPath $prompt -WorkerHome $wh -WorkerRunroot $base -NoSetup *> $log`
   (`*>` captures the JSONL trace; note PowerShell 5.1 writes that file UTF-16 -- decode accordingly).
6. **Validate the output** deterministically afterward (the worker writes a leaf/rules file; a parent
   re-validates + gates it; the worker NEVER writes production).

## Four traps that cost real debugging time (all baked into the scripts)

1. **User site-packages read grant.** If `-ReadDirs` omits `%APPDATA%\Python\PythonXYZ\site-packages`,
   the worker's `python` exits 1 (can't import deps). Use `_worker_read_dirs` + `-AllowUserSite`.
2. **Runroot/patch boundary.** `-WorkerRunroot` (the apply_patch `-C` boundary) must CONTAIN the dir
   the worker writes to. Set the runroot to the per-target scratch dir and put the output dir inside it.
3. **Windows MAX_PATH (260).** Worker homes nest deep
   (`.../batch/<id>/worker_home/<packet>/.sandbox-bin/<helper>.exe`); a long batch id pushes past 260
   and `CreateProcessWithLogonW` fails with ERROR_INSUFFICIENT_BUFFER (122). Keep batch/worker ids short.
4. **Auth into the fresh home.** Copy `auth.json` into each `-WorkerHome` (or set `CODEX_API_KEY`), or
   every worker 401s.

## Disk hygiene (added 2026-07-10)

Codex copies its full ~300 MB binary into `<WorkerHome>\.sandbox-bin\codex.exe` and syncs a
~40 MB / ~5,000-file plugin cache into `<WorkerHome>\.tmp\plugins` for EVERY fresh CODEX_HOME.
A 120-worker batch is therefore ~40 GB of pure scratch; by 2026-07-10 stale fleets had
accumulated 853 codex.exe copies (257 GB) under `data/output`.

- `run_codex_worker.ps1` now deletes both after each run (pass `-NoCleanup` to keep them for
  debugging a single worker). Worker artifacts (logs, verdicts, sqlite state) are untouched.
- `scripts/cleanup_worker_scratch.ps1` sweeps orphans from killed dispatchers or pre-change
  batches: `.\scripts\cleanup_worker_scratch.ps1 [-Root <dir>] [-WhatIfOnly]`. It refuses to
  run while any codex process is alive.

## Rollout traces (added 2026-08-20)

Workers no longer pass `--ephemeral` to `codex exec` (removed after the one-worker canary in
`data/output/agent_b2/batch/canary_trace_20260820/canary_report.md`). Codex therefore persists
one `sessions\YYYY\MM\DD\rollout-*.jsonl` per run under the worker CODEX_HOME: the full agent
trace -- tool calls WITH arguments (complete apply_patch bodies), tool outputs, and
session/turn metadata that the `--json` stdout stream does not carry (its `file_change` items
omit patch content entirely). ~65 KB for a no-shell B2 packet.

- The runner's finally block HARVESTS the rollout: moves it to `-TraceDir` (renamed
  `<TracePrefix><original-name>`) and prunes `sessions\`, so reused homes never accumulate
  session state. All fleet dispatchers pass their batch `logs\` dir + a per-worker prefix
  (`<id>__` for A/B1/B2/bdc_review, `iter<i>__` / `attempt<i>__` for the investigation and
  anchor loops, the per-cik `logs\worker.<quarter>.` for convention, whose worker homes are
  discarded TEMP scratch).
- `-NoCleanup` skips the harvest too (raw sessions layout kept for debugging one worker).
- Reasoning items in the rollout carry `encrypted_content` with EMPTY summaries -- readable
  chain-of-thought is NOT recoverable. Do not build tooling that expects reasoning text.
- The scratch sweepers explicitly KEEP `sessions\**\rollout-*.jsonl` (see
  `codex_worker_waste_allowlist.ps1`), so unharvested traces from killed dispatchers survive
  until collected.

## Higher-level orchestration (for reference, not templates)

These chain the primitive above into multi-agent pipelines; read them for parallelism/iteration
patterns, but they're remediation-specific: `dispatch_agent_a_workers.ps1`,
`dispatch_agent_b_workers.ps1` (B1), `dispatch_investigation.ps1` (B2 loop),
`dispatch_anchor_workers.ps1` (anchor), and the canaries `run_full_remediation_canary.ps1` /
`run_fresh_cik_trial.ps1`.
