param(
  [Parameter(Mandatory = $true)]
  [string] $TargetsPath,

  [string] $B1BatchId = "",
  [string] $B2BatchId = "",
  [int] $Limit = 0,
  [string[]] $Engine = @("conservation"),
  [string[]] $RuleName = @("fv_conservation"),
  [string] $Lane = "blocker",
  [string] $FixClass = "subtotal_filter",
  [int] $B1MaxParallel = 2,
  [int] $B2MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string] $CodexBin = "codex.cmd",
  [switch] $BuildOnly,
  [switch] $SkipB1Dispatch,
  [switch] $SkipB2Dispatch
)

# Reviewed B1 -> B2 dispatcher.
#
# This is the default path for CIK-quarter fixes. It refuses to let B2 start from raw
# residuals: a target CSV is first mapped to B1 review queue rows, B1 adjudicates them,
# and B2 packets are derived only from B1 real_error verdicts.
#
# Input CSV columns:
#   cik,target_quarter
# or:
#   review_id
#
# Example:
#   powershell -File scripts/dispatch_b1_to_b2_workers.ps1 `
#     -TargetsPath data/output/agent_investigate/canary_worklist.csv `
#     -Limit 5 -TimeoutMinutes 45

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

if ($Limit -lt 0) { throw "Limit must be >= 0." }
if ($B1MaxParallel -lt 1) { throw "B1MaxParallel must be >= 1." }
if ($B2MaxParallel -lt 1) { throw "B2MaxParallel must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }

Assert-OutsideCodexSession

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path -LiteralPath $TargetsPath -PathType Leaf)) {
  throw "Targets CSV does not exist: $TargetsPath"
}
$resolvedTargets = (Resolve-Path -LiteralPath $TargetsPath).Path

if ([string]::IsNullOrWhiteSpace($B1BatchId)) {
  $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
  $B1BatchId = "b1_to_b2_$stamp"
}
if ([string]::IsNullOrWhiteSpace($B2BatchId)) {
  $B2BatchId = $B1BatchId
}

Write-Host "[reviewed] targets=$resolvedTargets"
Write-Host "[reviewed] b1_batch=$B1BatchId b2_batch=$B2BatchId"

$buildArgs = @("-m", "scripts.agent_b2.reviewed_workflow", "build-b1-batch", $B1BatchId,
               "--targets", $resolvedTargets, "--lane", $Lane)
foreach ($one in $Engine) {
  if (-not [string]::IsNullOrWhiteSpace($one)) { $buildArgs += @("--engine", $one) }
}
foreach ($one in $RuleName) {
  if (-not [string]::IsNullOrWhiteSpace($one)) { $buildArgs += @("--rule-name", $one) }
}
if ($Limit -gt 0) { $buildArgs += @("--limit", [string]$Limit) }

$buildOutput = & python @buildArgs
if ($LASTEXITCODE -ne 0) {
  throw "B1 batch build failed: $($buildOutput -join [Environment]::NewLine)"
}
$buildText = ($buildOutput | Out-String).Trim()
Write-Host $buildText
$build = $buildText | ConvertFrom-Json

if ($BuildOnly) {
  Write-Host "[reviewed] build-only complete. Dispatch B1 next with scripts/dispatch_agent_b_workers.ps1 -BatchId $B1BatchId"
  exit 0
}

if (-not $SkipB1Dispatch) {
  Invoke-Checked -Label "b1" -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/dispatch_agent_b_workers.ps1",
    "-BatchId", $B1BatchId, "-MaxParallel", [string]$B1MaxParallel,
    "-TimeoutMinutes", [string]$TimeoutMinutes, "-CodexBin", $CodexBin
  )
} else {
  Write-Host "[b1] skipped dispatch; using existing B1 verdicts"
}

$b1Worklist = Join-Path $root "data/output/agent_b/batch/$B1BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $b1Worklist -PathType Leaf)) {
  throw "B1 worklist missing after build: $b1Worklist"
}

$b2Output = & python -m scripts.agent_b2.run_remediation discover $B2BatchId --source-worklist $b1Worklist
if ($LASTEXITCODE -ne 0) {
  throw "B2 discover failed: $($b2Output -join [Environment]::NewLine)"
}
$b2Text = ($b2Output | Out-String).Trim()
Write-Host $b2Text
$b2 = $b2Text | ConvertFrom-Json

if ([int]$b2.n_actionable -eq 0) {
  Write-Host "[b2] no actionable B2 packets from B1 real_error verdicts. Nothing to fix."
  exit 0
}

if (-not $SkipB2Dispatch) {
  $b2Args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/dispatch_agent_b2_workers.ps1",
              "-BatchId", $B2BatchId, "-MaxParallel", [string]$B2MaxParallel,
              "-TimeoutMinutes", [string]$TimeoutMinutes, "-CodexBin", $CodexBin)
  if (-not [string]::IsNullOrWhiteSpace($FixClass)) {
    $b2Args += @("-FixClass", $FixClass)
  }
  Invoke-Checked -Label "b2" -FilePath "powershell.exe" -ArgumentList $b2Args
} else {
  Write-Host "[b2] skipped dispatch. Packet worklist: $($b2.worklist)"
}

Write-Host "[reviewed] complete"
Write-Host "[reviewed] B1 worklist: $($build.worklist)"
Write-Host "[reviewed] B2 worklist: $($b2.worklist)"
