param(
  [Parameter(Mandatory = $true)]
  [string] $B1BatchId,

  [Parameter(Mandatory = $true)]
  [string] $B2BatchId,

  [string] $FixClass = "comparative_period_filter",
  [int] $MaxParallel = 1,
  [int] $TimeoutMinutes = 45,
  [string] $CodexBin = "codex.cmd",
  [switch] $ArchiveExisting,
  [switch] $SkipDispatch,
  [switch] $SkipApplyGate
)

# Rerun one B2 fix_class from an existing B1 batch, then apply and B3-gate each selected
# packet. Existing correction files are keyed by corrections/<CIK>/<fix_class>.json; use
# -ArchiveExisting to move those files aside with CIK-preserving archive paths.

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

# Windows MAX_PATH guard. The worker sandbox nests under
# data/output/agent_b2/batch/<B2BatchId>/worker_home/<packet>/.sandbox-bin/<helper>.exe; a long
# B2BatchId pushes that past 260 chars and CreateProcessWithLogonW fails (ERROR_INSUFFICIENT_BUFFER
# 122 -> "MISSING correction file"). Cap the id (unique via a short hash) to keep paths well under 260.
$maxBatchLen = 40
if ($B2BatchId.Length -gt $maxBatchLen) {
  $md5 = [System.Security.Cryptography.MD5]::Create()
  $hash = (([System.BitConverter]::ToString($md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($B2BatchId)))) -replace '-', '').Substring(0, 6).ToLower()
  $shortId = $B2BatchId.Substring(0, 30).TrimEnd('_') + "_" + $hash
  Write-Host "[canary] B2BatchId '$B2BatchId' ($($B2BatchId.Length) chars) exceeds $maxBatchLen; using '$shortId' to stay under Windows MAX_PATH"
  $B2BatchId = $shortId
}

$b1Worklist = Join-Path $root "data/output/agent_b/batch/$B1BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $b1Worklist -PathType Leaf)) {
  throw "B1 worklist missing: $b1Worklist"
}

Write-Host "[canary] b1_batch=$B1BatchId"
Write-Host "[canary] b2_batch=$B2BatchId"
Write-Host "[canary] fix_class=$FixClass"

$discoverOutput = & python -m scripts.agent_b2.run_remediation discover $B2BatchId --source-worklist $b1Worklist
if ($LASTEXITCODE -ne 0) {
  throw "B2 discover failed: $($discoverOutput -join [Environment]::NewLine)"
}
$discoverText = ($discoverOutput | Out-String).Trim()
Write-Host $discoverText
$discover = $discoverText | ConvertFrom-Json

$worklistPath = [string]$discover.worklist
$rows = @(Import-Csv -LiteralPath $worklistPath | Where-Object { $_.fix_class -eq $FixClass })
if ($rows.Count -eq 0) {
  Write-Host "[canary] no packets selected for fix_class=$FixClass"
  exit 0
}

$correctionsDir = Join-Path $root "data/output/agent_b2/corrections"
if ($ArchiveExisting) {
  $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
  $archiveDir = Join-Path $root "data/output/agent_b2/corrections_archive/${B2BatchId}_${FixClass}_$stamp"
  New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
  $archived = 0
  foreach ($row in $rows) {
    $src = Join-Path $correctionsDir "$($row.cik)/$FixClass.json"
    if (Test-Path -LiteralPath $src -PathType Leaf) {
      $destDir = Join-Path $archiveDir $row.cik
      New-Item -ItemType Directory -Force -Path $destDir | Out-Null
      $dest = Join-Path $destDir "$FixClass.json"
      if (Test-Path -LiteralPath $dest) { throw "Archive destination already exists: $dest" }
      Move-Item -LiteralPath $src -Destination $dest
      $archived += 1
    }
  }
  Write-Host "[canary] archived existing corrections: $archived -> $archiveDir"
}

if (-not $SkipDispatch) {
  Invoke-Checked -Label "b2" -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/dispatch_agent_b2_workers.ps1",
    "-BatchId", $B2BatchId,
    "-FixClass", $FixClass,
    "-MaxParallel", [string]$MaxParallel,
    "-TimeoutMinutes", [string]$TimeoutMinutes,
    "-CodexBin", $CodexBin
  )
} else {
  Write-Host "[b2] skipped dispatch"
}

if ($SkipApplyGate) {
  Write-Host "[canary] skipped apply/gate"
  exit 0
}

$batchDir = Join-Path $root "data/output/agent_b2/batch/$B2BatchId"
$baselineHoldings = Join-Path $root "data/output/private_markets_holdings.csv"
$gateRows = @()

foreach ($row in $rows) {
  $cik = [string]$row.cik
  $stage = [string]$row.stage
  Write-Host "[apply] cik=$cik stage=$stage"
  $applyArgs = @("-m", "scripts.agent_b2.run_remediation", "apply", $B2BatchId,
                 "--cik", $cik, "--run")
  if (-not [string]::IsNullOrWhiteSpace($stage)) {
    $applyArgs += @("--stage", $stage)
  }
  & python @applyArgs
  if ($LASTEXITCODE -ne 0) { throw "apply failed for $cik with exit code $LASTEXITCODE" }

  $trialDir = Join-Path $root "data/output/bdc_xbrl_wrapper_trial/$cik/unified_trial"
  $trialCorrected = Join-Path $trialDir "private_markets_holdings.$cik.corrected.csv"
  $trialBase = Join-Path $trialDir "private_markets_holdings.$cik.csv"
  $trialHoldings = $trialCorrected
  if (-not (Test-Path -LiteralPath $trialHoldings -PathType Leaf)) {
    $trialHoldings = $trialBase
  }
  if (-not (Test-Path -LiteralPath $trialHoldings -PathType Leaf)) {
    throw "trial holdings missing for $cik in $trialDir"
  }

  $quarters = @([string]$row.quarters -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
  foreach ($q in $quarters) {
    $gatePath = Join-Path $batchDir "b3_gate.$cik.$q.json"
    Write-Host "[gate] cik=$cik quarter=$q -> $gatePath"
    $gateOutput = & python -m scripts.agent_b2.run_remediation gate `
      --cik $cik `
      --target-quarter $q `
      --baseline-holdings $baselineHoldings `
      --trial-holdings $trialHoldings
    $gateExit = $LASTEXITCODE
    $gateText = ($gateOutput | Out-String).Trim()
    Set-Content -LiteralPath $gatePath -Value $gateText -Encoding UTF8
    $verdict = "UNKNOWN"
    try {
      $gateJson = $gateText | ConvertFrom-Json
      $verdict = [string]$gateJson.verdict
    } catch {
      $verdict = "PARSE_ERROR"
    }
    $gateRows += [pscustomobject]@{
      cik = $cik
      quarter = $q
      fix_class = $FixClass
      gate_exit = $gateExit
      verdict = $verdict
      gate_path = $gatePath
      trial_holdings = $trialHoldings
    }
    Write-Host "[gate] verdict=$verdict exit=$gateExit"
  }
}

$summaryPath = Join-Path $batchDir "b3_gate_summary.$FixClass.csv"
$gateRows | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding UTF8
Write-Host "[canary] complete"
Write-Host "[canary] worklist: $worklistPath"
Write-Host "[canary] gate summary: $summaryPath"
