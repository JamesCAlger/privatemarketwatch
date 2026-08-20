param(
  [Parameter(Mandatory = $true)]
  [string] $PromptPath,

  [string] $WorkerHome = (Join-Path $env:TEMP 'codex-worker-home'),
  [string] $WorkerRunroot = (Join-Path $env:TEMP 'codex-worker-runroot'),
  [string] $CodexBin = 'codex.cmd',
  [switch] $NoSetup,
  # Skip post-run scratch cleanup (keep .sandbox-bin\codex.exe + .tmp\plugins for debugging).
  # Also skips the rollout-trace harvest, leaving the raw sessions\ layout in place.
  [switch] $NoCleanup,
  # Destination dir for the harvested rollout trace (the sessions\YYYY\MM\DD\rollout-*.jsonl
  # codex exec persists now that --ephemeral is gone). Dispatchers pass their batch logs dir;
  # default keeps the trace in <WorkerHome>\traces so no caller loses it.
  [string] $TraceDir = '',
  # Prefix prepended to the harvested trace filename (the worker id) so traces from many
  # workers can share one TraceDir without colliding or losing attribution.
  [string] $TracePrefix = ''
)

$ErrorActionPreference = 'Stop'

$CodexSessionSignals = @(
  'CODEX_THREAD_ID',
  'CODEX_MANAGED_BY_NPM',
  'CODEX_MANAGED_PACKAGE_ROOT'
) | Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }

if ($CodexSessionSignals.Count -gt 0) {
  throw @"
Refusing to launch a nested Codex worker from inside an active Codex session.

Detected Codex session environment variable(s): $($CodexSessionSignals -join ', ')

Use native Codex subagents from the active session, or run this script from an operator
PowerShell outside Codex. Nested codex exec can lose auth, trigger Windows sandbox helper
failures, and make process cleanup ambiguous enough to kill the parent Codex app.
"@
}

if (-not (Test-Path -LiteralPath $PromptPath -PathType Leaf)) {
  throw "Prompt file does not exist: $PromptPath"
}

if (-not $NoSetup) {
  & (Join-Path $PSScriptRoot 'setup_codex_worker_harness.ps1') `
    -WorkerHome $WorkerHome `
    -WorkerRunroot $WorkerRunroot | Out-Null
}

$ConfigPath = Join-Path $WorkerHome 'config.toml'
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
  throw "Worker config does not exist: $ConfigPath"
}

$PreviousCodexHome = $env:CODEX_HOME
$PreviousErrorActionPreference = $ErrorActionPreference
try {
  $env:CODEX_HOME = $WorkerHome
  # NOTE: codex >= 0.x dropped `--ask-for-approval` from `exec` (exec is non-interactive).
  # Autonomy is set by the worker config.toml (approval_policy = "never"); do NOT re-add the
  # CLI flag -- it makes every worker exit immediately with "unexpected argument".
  #
  # Codex can emit non-fatal startup warnings on stderr (for example model-cache refresh
  # timeouts) while still completing the worker turn. Under `$ErrorActionPreference = 'Stop'`,
  # Windows PowerShell turns native stderr into a terminating NativeCommandError and aborts the
  # parent dispatcher before it can run deterministic validation. Let the native process finish;
  # callers inspect `$LASTEXITCODE` and validate the worker artifact.
  $ErrorActionPreference = 'Continue'
  # --ephemeral was removed 2026-08-20 (one-worker canary: data\output\agent_b2\batch\
  # canary_trace_20260820\canary_report.md). It suppressed session persistence, so no
  # rollout trace (tool calls WITH arguments, tool outputs, reasoning items) survived any
  # worker run. Without it codex writes exactly one sessions\YYYY\MM\DD\rollout-*.jsonl
  # (~65 KB for a no-shell B2 packet), harvested in the finally block below. Reasoning
  # items carry encrypted_content only -- do not expect readable chain-of-thought.
  Get-Content -LiteralPath $PromptPath -Raw | & $CodexBin exec `
    --strict-config `
    --skip-git-repo-check `
    --ignore-rules `
    -C $WorkerRunroot `
    --json `
    -
} finally {
  $ErrorActionPreference = $PreviousErrorActionPreference
  if ($null -eq $PreviousCodexHome) {
    Remove-Item Env:\CODEX_HOME -ErrorAction SilentlyContinue
  } else {
    $env:CODEX_HOME = $PreviousCodexHome
  }
  # Harvest the rollout trace ahead of the scrub. Best-effort: harvest failure must
  # never fail the worker run, and warnings go to stderr only -- stdout is the JSONL
  # event stream dispatchers parse. Moving the rollout out of sessions\ (then removing
  # sessions\) keeps reused worker homes from accumulating per-run session state and
  # gives each run exactly one deterministic trace artifact.
  if (-not $NoCleanup) {
    try {
      $SessionsDir = Join-Path $WorkerHome 'sessions'
      if ([string]::IsNullOrWhiteSpace($TraceDir)) { $TraceDir = Join-Path $WorkerHome 'traces' }
      $Rollouts = @(Get-ChildItem -LiteralPath $SessionsDir -Recurse -Filter 'rollout-*.jsonl' -File -ErrorAction SilentlyContinue)
      if ($Rollouts.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $TraceDir | Out-Null
        foreach ($Rollout in $Rollouts) {
          Move-Item -LiteralPath $Rollout.FullName -Destination (Join-Path $TraceDir "$TracePrefix$($Rollout.Name)") -Force
        }
        Remove-Item -LiteralPath $SessionsDir -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
      } else {
        Write-Warning "No rollout trace found under $SessionsDir to harvest."
      }
    } catch {
      Write-Warning "Rollout trace harvest failed: $($_.Exception.Message)"
    }
  }
  # Codex copies its full binary, plugin caches, model caches, AND the operator's
  # logged-in auth.json into every fresh CODEX_HOME. The full waste allowlist lives
  # in codex_worker_waste_allowlist.ps1 (shared with sweep_worker_scratch_waste.ps1
  # so wrapper and sweeper cannot drift). 2026-08-20 expansion: the previous
  # two-item cleanup here missed plugins\cache (~26 MB / ~5,000 files per worker --
  # the dominant batch-scratch cost) and auth.json (live credentials in scratch).
  # Scrub runs on worker failure too (failed workers also hold credentials);
  # worker artifacts (logs, verdicts, sqlite state, and any sessions\rollout-*.jsonl
  # traces) are untouched. If the home is reused, Codex just re-copies what it needs.
  if (-not $NoCleanup) {
    . (Join-Path $PSScriptRoot 'codex_worker_waste_allowlist.ps1')
    Remove-CodexWorkerWaste -WorkerHome $WorkerHome
  }
}
