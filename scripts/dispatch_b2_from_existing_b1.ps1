param(
  [Parameter(Mandatory = $true)]
  [string] $B1BatchId,

  [string] $B2BatchId = "",
  [string] $FixClass = "subtotal_filter",
  [int] $MaxParallel = 1,
  [int] $TimeoutMinutes = 30,
  [string] $CodexBin = "codex.cmd",
  [switch] $DiscoverOnly
)

# Re-run Agent B2 from an already completed B1 batch. This does not rebuild or dispatch B1.
# It regenerates the B2 packet worklist strictly from the selected B1 batch worklist, then
# launches the existing B2 dispatcher.
#
# Example:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dispatch_b2_from_existing_b1.ps1 `
#     -B1BatchId canary_b1_to_b2_20260626T125839Z `
#     -B2BatchId canary_b1_to_b2_20260626T125839Z `
#     -FixClass subtotal_filter `
#     -MaxParallel 1 `
#     -TimeoutMinutes 45

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $signals = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($signals.Count -gt 0) {
    throw "Refusing to dispatch external Codex workers from inside an active Codex session: $($signals -join ', ')"
  }
}

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][string] $Label,
    [Parameter(Mandatory = $true)][string] $FilePath,
    [Parameter(Mandatory = $true)][string[]] $ArgumentList
  )
  Write-Host "[$Label] $FilePath $($ArgumentList -join ' ')"
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

if ($MaxParallel -lt 1) { throw "MaxParallel must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }

Assert-OutsideCodexSession

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($B2BatchId)) {
  $B2BatchId = $B1BatchId
}

$b1Worklist = Join-Path $root "data/output/agent_b/batch/$B1BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $b1Worklist -PathType Leaf)) {
  throw "B1 worklist missing: $b1Worklist"
}

Write-Host "[b2-rerun] b1_batch=$B1BatchId"
Write-Host "[b2-rerun] b2_batch=$B2BatchId"
Write-Host "[b2-rerun] source_worklist=$b1Worklist"

$discoverOutput = & python -m scripts.agent_b2.run_remediation discover $B2BatchId --source-worklist $b1Worklist
if ($LASTEXITCODE -ne 0) {
  throw "B2 discover failed: $($discoverOutput -join [Environment]::NewLine)"
}
$discoverText = ($discoverOutput | Out-String).Trim()
Write-Host $discoverText
$discover = $discoverText | ConvertFrom-Json

if ([int]$discover.n_actionable -eq 0) {
  Write-Host "[b2-rerun] no actionable B2 packets from B1 real_error verdicts. Nothing to dispatch."
  exit 0
}

if ($DiscoverOnly) {
  Write-Host "[b2-rerun] discover-only complete. B2 worklist: $($discover.worklist)"
  exit 0
}

$b2Args = @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/dispatch_agent_b2_workers.ps1",
  "-BatchId", $B2BatchId,
  "-FixClass", $FixClass,
  "-MaxParallel", [string]$MaxParallel,
  "-TimeoutMinutes", [string]$TimeoutMinutes,
  "-CodexBin", $CodexBin
)
Invoke-Checked -Label "b2" -FilePath "powershell.exe" -ArgumentList $b2Args

Write-Host "[b2-rerun] complete"
Write-Host "[b2-rerun] B2 worklist: $($discover.worklist)"
