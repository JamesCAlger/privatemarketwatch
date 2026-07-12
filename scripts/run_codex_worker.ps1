param(
  [Parameter(Mandatory = $true)]
  [string] $PromptPath,

  [string] $WorkerHome = (Join-Path $env:TEMP 'codex-worker-home'),
  [string] $WorkerRunroot = (Join-Path $env:TEMP 'codex-worker-runroot'),
  [string] $CodexBin = 'codex.cmd',
  [switch] $NoSetup,
  # Skip post-run scratch cleanup (keep .sandbox-bin\codex.exe + .tmp\plugins for debugging).
  [switch] $NoCleanup
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
  Get-Content -LiteralPath $PromptPath -Raw | & $CodexBin exec `
    --ephemeral `
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
  # Codex copies its full ~300 MB binary into <WorkerHome>\.sandbox-bin and syncs a
  # ~40 MB / ~5,000-file plugin cache into <WorkerHome>\.tmp\plugins on every fresh
  # CODEX_HOME. Left in place, a 120-worker batch is ~40 GB of pure scratch (853
  # stale copies = 257 GB by 2026-07-10). Worker artifacts (logs, verdicts, sqlite
  # state) are untouched; if the same home is reused, Codex just re-copies.
  if (-not $NoCleanup) {
    Remove-Item (Join-Path $WorkerHome '.sandbox-bin\codex.exe') -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $WorkerHome '.tmp\plugins') -Recurse -Force -ErrorAction SilentlyContinue
  }
}
