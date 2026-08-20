param(
  [Parameter(Mandatory = $true)]
  [string] $BatchId,

  [string] $FixClass = "subtotal_filter",
  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string] $CodexBin = "codex.cmd"
)

# Agent B2 remediation dispatcher. The B2 analog of dispatch_agent_b_workers.ps1: run the
# deterministic preflight (manifest + per-packet remediation prompts), launch one sandboxed
# Codex worker per (cik, fix_class) packet (write-grant scoped to the corrections dir),
# validate each correction leaf. The heavy apply (trial rebuild) + B3 gate are run AFTER by
# the operator via scripts.agent_b2.run_remediation.
#
# Prerequisite: the B2 packet worklist must exist --
#   python -m scripts.agent_b2.run_remediation discover <BatchId> --source-worklist <B1 worklist.csv>
#
# Shares run_codex_worker.ps1 + setup_codex_worker_harness.ps1 with A/B1 (env fixes:
# absolute interpreter, import-dir read grants, inherit=all, user site). Loop duplicated on
# purpose for now. Run from an operator shell OUTSIDE Codex.

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $signals = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($signals.Count -gt 0) {
    throw "Refusing to dispatch external Codex workers from inside an active Codex session: $($signals -join ', ')"
  }
}

function Quote-ForWrapper { param([string] $Value) return "'" + ($Value -replace "'", "''") + "'" }

function Get-SourceCodexHome {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { return $env:CODEX_HOME }
  return Join-Path $HOME ".codex"
}

function Invoke-Preflight {
  $args = @("-m", "scripts.agent_b2.dispatch_preflight", "--batch-id", $BatchId, "--reserve")
  if (-not [string]::IsNullOrWhiteSpace($FixClass)) { $args += @("--fix-class", $FixClass) }
  $json = & python @args
  if ($LASTEXITCODE -ne 0) { throw "Agent B2 dispatch preflight failed." }
  return $json | ConvertFrom-Json
}

function Invoke-ReleaseManifest {
  param([string] $ManifestPath)
  & python -m scripts.agent_b2.dispatch_preflight --release-manifest $ManifestPath | Out-Null
}

function New-WorkerWrapper {
  param($Row, [string] $WorkerHome, [string] $WorkerRunroot, [string] $WrapperPath,
    [string] $TraceDir, [string] $TracePrefix)
  $runScript = Join-Path $PSScriptRoot "run_codex_worker.ps1"
  $content = @"
`$ErrorActionPreference = 'Stop'
& $(Quote-ForWrapper $runScript) ``
  -PromptPath $(Quote-ForWrapper $Row.prompt_path) ``
  -WorkerHome $(Quote-ForWrapper $WorkerHome) ``
  -WorkerRunroot $(Quote-ForWrapper $WorkerRunroot) ``
  -CodexBin $(Quote-ForWrapper $CodexBin) ``
  -TraceDir $(Quote-ForWrapper $TraceDir) ``
  -TracePrefix $(Quote-ForWrapper $TracePrefix) ``
  -NoSetup
exit `$LASTEXITCODE
"@
  Set-Content -LiteralPath $WrapperPath -Value $content -Encoding ASCII
}

function Invoke-ValidateCorrection {
  param($Row, [string] $LogPath)
  if (-not (Test-Path -LiteralPath $Row.correction_path -PathType Leaf)) {
    Set-Content -LiteralPath $LogPath -Value "MISSING correction file: $($Row.correction_path)" -Encoding ASCII
    return 1
  }
  & python -m scripts.agent_b2.validate_corrections `
    --correction $Row.correction_path `
    --expected-cik $Row.cik `
    --expected-fix-class $Row.fix_class *> $LogPath
  return $LASTEXITCODE
}

function Stop-TrackedProcessTree {
  param([int] $ProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) { Stop-TrackedProcessTree -ProcessId ([int]$child.ProcessId) }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if ($MaxParallel -lt 1) { throw "MaxParallel must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }

Assert-OutsideCodexSession

$sourceHome = Get-SourceCodexHome
$sourceAuth = Join-Path $sourceHome "auth.json"
$hasFileAuth = Test-Path -LiteralPath $sourceAuth -PathType Leaf
$hasApiKey = -not [string]::IsNullOrWhiteSpace($env:CODEX_API_KEY)
if (-not ($hasFileAuth -or $hasApiKey)) {
  throw "No Codex auth found. Expected $sourceAuth or CODEX_API_KEY for single-run auth."
}

$preflight = Invoke-Preflight
$manifestPath = $preflight.manifest_path
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$batchDir = Split-Path -Parent $manifestPath
$correctionsDir = $manifest.corrections_dir
$logDir = Join-Path $batchDir "logs"
$wrapperDir = Join-Path $batchDir "wrappers"
$homeDir = Join-Path $batchDir "worker_home"
$runrootDir = Join-Path $batchDir "worker_runroot"
New-Item -ItemType Directory -Force -Path $logDir, $wrapperDir, $homeDir, $runrootDir | Out-Null

# Read-grant the interpreter's import roots so the worker can run python with project deps.
$readGrants = @()
if (-not [string]::IsNullOrWhiteSpace($manifest.worker_python)) {
  $readGrants += (Split-Path -Parent $manifest.worker_python)
}
if ($manifest.worker_read_dirs) { $readGrants += @($manifest.worker_read_dirs) }
$readGrants = @($readGrants | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)

if (($manifest.rows | Measure-Object).Count -eq 0) {
  Write-Host "Agent B2 dispatch: nothing to dispatch."
  Invoke-ReleaseManifest -ManifestPath $manifestPath
  exit 0
}

$queue = New-Object System.Collections.Queue
foreach ($row in $manifest.rows) { $queue.Enqueue($row) }
$running = @()
$failures = @()

try {
  while (($queue.Count -gt 0) -or ($running.Count -gt 0)) {
    while (($queue.Count -gt 0) -and ($running.Count -lt $MaxParallel)) {
      $row = $queue.Dequeue()
      $idSafe = "$($row.cik)__$($row.fix_class)"
      $workerHome = Join-Path $homeDir $idSafe
      $workerRunroot = Split-Path -Parent $row.correction_path
      New-Item -ItemType Directory -Force -Path $workerHome, $workerRunroot | Out-Null

      & (Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1") `
        -WorkerHome $workerHome `
        -WorkerRunroot $workerRunroot `
        -WriteDirs @($workerRunroot) `
        -ReadDirs $readGrants `
        -EnvInherit "all" `
        -AllowUserSite | Out-Null

      if ($hasFileAuth) {
        Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $workerHome "auth.json") -Force
      }

      $wrapperPath = Join-Path $wrapperDir "$idSafe.ps1"
      New-WorkerWrapper -Row $row -WorkerHome $workerHome -WorkerRunroot $workerRunroot -WrapperPath $wrapperPath `
        -TraceDir $logDir -TracePrefix "${idSafe}__"
      $stdout = Join-Path $logDir "$idSafe.stdout.jsonl"
      $stderr = Join-Path $logDir "$idSafe.stderr.txt"
      $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$wrapperPath`"") `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
      $null = $proc.Handle
      $running += [pscustomobject]@{ Row = $row; Process = $proc; Started = Get-Date; Stderr = $stderr }
      Write-Host "launched $idSafe pid=$($proc.Id)"
    }

    Start-Sleep -Seconds 2
    $nextRunning = @()
    foreach ($job in $running) {
      $proc = $job.Process
      $idSafe = "$($job.Row.cik)__$($job.Row.fix_class)"
      $elapsed = (Get-Date) - $job.Started
      if (-not $proc.HasExited -and $elapsed.TotalMinutes -ge $TimeoutMinutes) {
        Stop-TrackedProcessTree -ProcessId $proc.Id
        $failures += "${idSafe}: TIMEOUT after $TimeoutMinutes minute(s)"
        continue
      }
      if (-not $proc.HasExited) { $nextRunning += $job; continue }
      $ec = $proc.ExitCode
      if ($null -ne $ec -and $ec -ne 0) {
        $failures += "${idSafe}: worker exit $ec; stderr=$($job.Stderr)"
        continue
      }
      $validationLog = Join-Path $logDir "$idSafe.validate.txt"
      $validationExit = Invoke-ValidateCorrection -Row $job.Row -LogPath $validationLog
      if ($validationExit -ne 0) {
        $failures += "${idSafe}: correction validation failed; log=$validationLog"
      } else {
        Write-Host "validated $idSafe"
      }
    }
    $running = $nextRunning
  }

  if ($failures.Count -gt 0) {
    $failurePath = Join-Path $batchDir "dispatch_failures.txt"
    Set-Content -LiteralPath $failurePath -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
    throw "Agent B2 dispatch completed with $($failures.Count) failure(s); see $failurePath"
  }
  Write-Host "Agent B2 dispatch complete. Corrections in: $correctionsDir"
  Write-Host "Next (operator): run_remediation apply --cik <CIK> --run ; then run_remediation gate ..."
} finally {
  foreach ($job in $running) {
    if (-not $job.Process.HasExited) { Stop-TrackedProcessTree -ProcessId $job.Process.Id }
  }
  if ($manifestPath) { Invoke-ReleaseManifest -ManifestPath $manifestPath }
}
