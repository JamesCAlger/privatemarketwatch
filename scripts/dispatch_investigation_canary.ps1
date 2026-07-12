param(
  [Parameter(Mandatory = $true)]
  [string] $WorklistPath,

  [int] $Limit = 10,
  [int] $TimeoutMinutes = 45,
  [string] $RunId = "",
  [switch] $Resume,
  [switch] $ArchiveExisting,
  [switch] $PrepOnly,
  [switch] $AllowUnreviewedRawResidual
)

# Serial canary runner for the agentic investigation path.
#
# Input CSV columns:
#   cik,target_quarter
#
# This wrapper is intentionally conservative:
# - runs one CIK-quarter at a time;
# - enforces a parent-side timeout;
# - refuses stale per-CIK scratch dirs unless -Resume or -ArchiveExisting is supplied;
# - re-runs deterministic status after each worker and writes CSV/JSON summaries.
#
# This raw path is diagnostics-only by default. For normal B1-gated remediation, run:
#   powershell -File scripts/dispatch_b1_to_b2_workers.ps1 `
#     -TargetsPath data/output/agent_investigate/canary_worklist.csv `
#     -Limit 5 -TimeoutMinutes 45
#
# Diagnostics-only run from an operator PowerShell outside Codex:
#   powershell -File scripts/dispatch_investigation_canary.ps1 `
#     -WorklistPath data/output/agent_investigate/canary_worklist.csv `
#     -Limit 5 -TimeoutMinutes 45 -AllowUnreviewedRawResidual

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $signals = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($signals.Count -gt 0) {
    throw "Refusing to dispatch external Codex workers from inside an active Codex session: $($signals -join ', ')"
  }
}

function Stop-TrackedProcessTree {
  param([Parameter(Mandatory = $true)][int] $ProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Stop-TrackedProcessTree -ProcessId ([int]$child.ProcessId)
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Assert-PathInside {
  param(
    [Parameter(Mandatory = $true)][string] $Path,
    [Parameter(Mandatory = $true)][string] $Root
  )
  $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
  $pathFull = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
  if (-not ($pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
            $pathFull.StartsWith($rootFull + '\', [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Resolved path is outside expected root. path=$pathFull root=$rootFull"
  }
}

function Get-Field {
  param($Row, [string[]] $Names)
  foreach ($name in $Names) {
    if ($Row.PSObject.Properties.Name -contains $name) {
      $value = [string]$Row.$name
      if (-not [string]::IsNullOrWhiteSpace($value)) { return $value.Trim() }
    }
  }
  return ""
}

function Read-Status {
  param([string] $Cik, [string] $TargetQuarter, [int] $Iteration)
  $output = & python -m scripts.agent_investigate.run_investigation status `
    --cik $Cik --target-quarter $TargetQuarter --iteration $Iteration 2>&1
  $text = ($output | Out-String).Trim()
  if ([string]::IsNullOrWhiteSpace($text)) {
    return [pscustomobject]@{ Raw = ""; Json = $null; ExitCode = $LASTEXITCODE }
  }
  try {
    return [pscustomobject]@{ Raw = $text; Json = ($text | ConvertFrom-Json); ExitCode = $LASTEXITCODE }
  } catch {
    return [pscustomobject]@{ Raw = $text; Json = $null; ExitCode = $LASTEXITCODE }
  }
}

Assert-OutsideCodexSession

if ($Limit -lt 1) { throw "Limit must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }
if ($Resume -and $ArchiveExisting) { throw "Use either -Resume or -ArchiveExisting, not both." }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $AllowUnreviewedRawResidual) {
  throw @"
dispatch_investigation_canary.ps1 is disabled by default because it runs B2-like fixes from raw residuals without B1 adjudication.
Use scripts/dispatch_b1_to_b2_workers.ps1 -TargetsPath <csv> instead. That path maps targets to B1 review IDs, dispatches B1, derives B2 packets only from B1 real_error verdicts, and then dispatches B2.
For diagnostics only, rerun this script with -AllowUnreviewedRawResidual.
"@
}

if (-not (Test-Path -LiteralPath $WorklistPath -PathType Leaf)) {
  throw "Worklist does not exist: $WorklistPath. Build one with: powershell -File scripts/build_investigation_canary_worklist.ps1 -Limit $Limit"
}
$resolvedWorklist = (Resolve-Path -LiteralPath $WorklistPath).Path
$rows = @(Import-Csv -LiteralPath $resolvedWorklist)
if ($rows.Count -eq 0) { throw "Worklist is empty: $resolvedWorklist" }

if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
}

$agentRoot = Join-Path $root "data/output/agent_investigate"
$runDir = Join-Path $agentRoot "canary/$RunId"
$logDir = Join-Path $runDir "logs"
$statusDir = Join-Path $runDir "status"
$archiveDir = Join-Path $runDir "archived_existing"
New-Item -ItemType Directory -Force -Path $logDir, $statusDir | Out-Null
if ($ArchiveExisting) { New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null }

$dispatch = Join-Path $PSScriptRoot "dispatch_investigation.ps1"
$summary = New-Object System.Collections.Generic.List[object]
$selected = @($rows | Select-Object -First $Limit)

Write-Host "[canary] run_id=$RunId rows=$($selected.Count) worklist=$resolvedWorklist"
Write-Host "[canary] output=$runDir"

$index = 0
foreach ($row in $selected) {
  $index += 1
  $cikRaw = Get-Field $row @("cik", "Cik", "CIK")
  $targetQuarter = Get-Field $row @("target_quarter", "TargetQuarter", "report_date", "ReportDate")
  if ([string]::IsNullOrWhiteSpace($cikRaw) -or [string]::IsNullOrWhiteSpace($targetQuarter)) {
    throw "Worklist row $index missing cik or target_quarter."
  }
  $cik = $cikRaw.TrimStart('0')
  if ([string]::IsNullOrWhiteSpace($cik)) { $cik = "0" }
  $id = "{0:D2}_{1}_{2}" -f $index, $cik, $targetQuarter
  $cikDir = Join-Path $agentRoot $cik
  $rulesDir = Join-Path $cikDir "rules"
  $stdout = Join-Path $logDir "$id.stdout.txt"
  $stderr = Join-Path $logDir "$id.stderr.txt"
  $statusPath = Join-Path $statusDir "$id.status.json"

  $rowStatus = "UNKNOWN"
  $reason = ""
  $residualPct = $null
  $gateVerdict = ""
  $nRules = 0
  $started = Get-Date

  try {
    if ((Test-Path -LiteralPath $rulesDir -PathType Container) -and -not $Resume -and -not $ArchiveExisting) {
      $rowStatus = "SKIP_STALE"
      $reason = "rules dir already exists; rerun with -Resume or -ArchiveExisting"
      Write-Host "[canary][$index/$($selected.Count)] SKIP $cik $targetQuarter - $reason"
    } else {
      if ((Test-Path -LiteralPath $cikDir -PathType Container) -and $ArchiveExisting) {
        Assert-PathInside -Path $cikDir -Root $agentRoot
        $dest = Join-Path $archiveDir $cik
        if (Test-Path -LiteralPath $dest) { throw "Archive destination already exists: $dest" }
        Move-Item -LiteralPath $cikDir -Destination $dest
      }

      Write-Host "[canary][$index/$($selected.Count)] RUN $cik $targetQuarter"
      $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$dispatch`"",
                "-Cik", $cik, "-TargetQuarter", $targetQuarter, "-TimeoutMinutes", "$TimeoutMinutes",
                "-AllowUnreviewedRawResidual")
      if ($PrepOnly) { $args += "-PrepOnly" }
      $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList $args `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
      $null = $proc.Handle

      while (-not $proc.HasExited) {
        $elapsed = (Get-Date) - $started
        if ($elapsed.TotalMinutes -ge $TimeoutMinutes) {
          Stop-TrackedProcessTree -ProcessId $proc.Id
          $rowStatus = "TIMEOUT"
          $reason = "timeout after $TimeoutMinutes minute(s)"
          break
        }
        Start-Sleep -Seconds 3
      }

      if ($rowStatus -ne "TIMEOUT") {
        $exitCode = $proc.ExitCode
        if ($null -ne $exitCode -and $exitCode -ne 0) {
          $rowStatus = "WORKER_FAIL"
          $reason = "dispatcher exit $exitCode"
        } elseif ($PrepOnly) {
          $rowStatus = "PREP_ONLY"
          $reason = "prompt generated"
        } else {
          $statusIteration = 1
          $manifestPath = Join-Path $cikDir "manifest.json"
          if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            try {
              $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
              if ($manifest.iteration) { $statusIteration = [int]$manifest.iteration }
            } catch {
              $statusIteration = 1
            }
          }
          $status = Read-Status -Cik $cik -TargetQuarter $targetQuarter -Iteration $statusIteration
          Set-Content -LiteralPath $statusPath -Value $status.Raw -Encoding ASCII
          if ($null -eq $status.Json) {
            $rowStatus = "STATUS_PARSE_FAIL"
            $reason = "could not parse status JSON"
          } else {
            $residualPct = $status.Json.residual_pct
            $gateVerdict = [string]$status.Json.gate_verdict
            $nRules = [int]$status.Json.n_rules
            if ($status.Json.decision.success -eq $true) {
              $rowStatus = "PASS"
            } else {
              $rowStatus = "FAIL"
            }
            $reason = [string]$status.Json.decision.reason
          }
        }
      }
    }
  } catch {
    $rowStatus = "ERROR"
    $reason = $_.Exception.Message
  }

  $ended = Get-Date
  $summary.Add([pscustomobject]@{
    index = $index
    cik = $cik
    target_quarter = $targetQuarter
    status = $rowStatus
    reason = $reason
    n_rules = $nRules
    residual_pct = $residualPct
    gate_verdict = $gateVerdict
    seconds = [math]::Round(($ended - $started).TotalSeconds, 1)
    stdout = $stdout
    stderr = $stderr
    status_json = $statusPath
  })

  Write-Host "[canary][$index/$($selected.Count)] $rowStatus $cik $targetQuarter - $reason"
}

$summaryCsv = Join-Path $runDir "summary.csv"
$summaryJson = Join-Path $runDir "summary.json"
$summary | Export-Csv -LiteralPath $summaryCsv -NoTypeInformation -Encoding ASCII
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryJson -Encoding ASCII

$counts = $summary | Group-Object status | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Count)" }
Write-Host "[canary] complete: $($counts -join ', ')"
Write-Host "[canary] summary: $summaryCsv"

if (($summary | Where-Object { $_.status -ne "PASS" -and $_.status -ne "PREP_ONLY" }).Count -gt 0) {
  exit 1
}
exit 0
