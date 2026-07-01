param(
  [Parameter(Mandatory = $true)]
  [string] $Quarter,

  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string] $BatchId = "",
  [string[]] $Cik = @(),
  [switch] $Remediation,
  [string] $CodexBin = "codex.cmd",
  [string] $WorkerRoot = (Join-Path $env:TEMP "agent-a-codex-workers")
)

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $signals = @(
    "CODEX_THREAD_ID",
    "CODEX_MANAGED_BY_NPM",
    "CODEX_MANAGED_PACKAGE_ROOT"
  ) | Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }

  if ($signals.Count -gt 0) {
    throw "Refusing to dispatch external Codex workers from inside an active Codex session: $($signals -join ', ')"
  }
}

function Quote-ForWrapper {
  param([Parameter(Mandatory = $true)][string] $Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

function Get-SourceCodexHome {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    return $env:CODEX_HOME
  }
  return Join-Path $HOME ".codex"
}

function Invoke-Preflight {
  $args = @("-m", "scripts.agent_a.dispatch_preflight", "--quarter", $Quarter, "--reserve")
  if ($Remediation) {
    $args += @("--remediation")
  }
  if (-not [string]::IsNullOrWhiteSpace($BatchId)) {
    $args += @("--batch-id", $BatchId)
  }
  foreach ($OneCik in $Cik) {
    $args += @("--cik", $OneCik)
  }
  $json = & python @args
  if ($LASTEXITCODE -ne 0) {
    throw "Agent A dispatch preflight failed."
  }
  return $json | ConvertFrom-Json
}

function Invoke-ReleaseManifest {
  param([Parameter(Mandatory = $true)][string] $ManifestPath)
  & python -m scripts.agent_a.dispatch_preflight --release-manifest $ManifestPath | Out-Null
}

function New-WorkerWrapper {
  param(
    [Parameter(Mandatory = $true)] $Row,
    [Parameter(Mandatory = $true)][string] $WorkerHome,
    [Parameter(Mandatory = $true)][string] $WorkerRunroot,
    [Parameter(Mandatory = $true)][string] $WrapperPath
  )

  $runScript = Join-Path $PSScriptRoot "run_codex_worker.ps1"
  $content = @"
`$ErrorActionPreference = 'Stop'
& $(Quote-ForWrapper $runScript) ``
  -PromptPath $(Quote-ForWrapper $Row.prompt_path) ``
  -WorkerHome $(Quote-ForWrapper $WorkerHome) ``
  -WorkerRunroot $(Quote-ForWrapper $WorkerRunroot) ``
  -CodexBin $(Quote-ForWrapper $CodexBin) ``
  -NoSetup
exit `$LASTEXITCODE
"@
  Set-Content -LiteralPath $WrapperPath -Value $content -Encoding ASCII
}

function Invoke-ValidateProposal {
  param(
    [Parameter(Mandatory = $true)] $Row,
    [Parameter(Mandatory = $true)][string] $LogPath
  )
  & python -m scripts.agent_a.validate_proposal --cik $Row.cik --bundle $Row.bundle_path *> $LogPath
  return $LASTEXITCODE
}

function Stop-TrackedProcessTree {
  param([Parameter(Mandatory = $true)][int] $ProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Stop-TrackedProcessTree -ProcessId ([int]$child.ProcessId)
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if ($MaxParallel -lt 1) {
  throw "MaxParallel must be >= 1."
}
if ($TimeoutMinutes -lt 1) {
  throw "TimeoutMinutes must be >= 1."
}

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
$logDir = Join-Path $batchDir "logs"
$wrapperDir = Join-Path $batchDir "wrappers"
$homeDir = Join-Path $batchDir "worker_home"
$runrootDir = Join-Path $batchDir "worker_runroot"
New-Item -ItemType Directory -Force -Path $logDir, $wrapperDir, $homeDir, $runrootDir | Out-Null

$queue = New-Object System.Collections.Queue
foreach ($row in $manifest.rows) {
  $queue.Enqueue($row)
}

$running = @()
$failures = @()

try {
  while (($queue.Count -gt 0) -or ($running.Count -gt 0)) {
    while (($queue.Count -gt 0) -and ($running.Count -lt $MaxParallel)) {
      $row = $queue.Dequeue()
      $cikSafe = $row.cik
      $workerHome = Join-Path $homeDir $cikSafe
      $workerRunroot = Join-Path $runrootDir $cikSafe
      New-Item -ItemType Directory -Force -Path $workerHome, $workerRunroot | Out-Null

      & (Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1") `
        -WorkerHome $workerHome `
        -WorkerRunroot $workerRunroot | Out-Null

      if ($hasFileAuth) {
        Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $workerHome "auth.json") -Force
      }

      $wrapperPath = Join-Path $wrapperDir "$cikSafe.ps1"
      New-WorkerWrapper -Row $row -WorkerHome $workerHome -WorkerRunroot $workerRunroot -WrapperPath $wrapperPath

      $stdout = Join-Path $logDir "$cikSafe.stdout.jsonl"
      $stderr = Join-Path $logDir "$cikSafe.stderr.txt"
      $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$wrapperPath`"") `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

      # Touch .Handle so the Process object caches the OS handle; without this, a
      # Start-Process -PassThru object frequently returns $null for .ExitCode after the
      # process exits (a well-known PowerShell gotcha), which made the dispatcher mark every
      # worker -- even successful ones -- as "worker exit " and skip finalize/gate.
      $null = $proc.Handle

      $running += [pscustomobject]@{
        Row = $row
        Process = $proc
        Started = Get-Date
        Stdout = $stdout
        Stderr = $stderr
      }
      Write-Host "launched $($row.cik) pid=$($proc.Id)"
    }

    Start-Sleep -Seconds 2

    $nextRunning = @()
    foreach ($job in $running) {
      $proc = $job.Process
      $elapsed = (Get-Date) - $job.Started
      if (-not $proc.HasExited -and $elapsed.TotalMinutes -ge $TimeoutMinutes) {
        Stop-TrackedProcessTree -ProcessId $proc.Id
        $failures += "$($job.Row.cik): TIMEOUT after $TimeoutMinutes minute(s)"
        continue
      }
      if (-not $proc.HasExited) {
        $nextRunning += $job
        continue
      }
      # Only a CONFIRMED non-zero exit is a hard failure. A $null exit code means the handle
      # didn't capture it; do NOT auto-fail on that -- fall through to validate_proposal, which
      # is the authoritative deterministic check (it re-parses the staged proposal).
      $ec = $proc.ExitCode
      if ($null -ne $ec -and $ec -ne 0) {
        $failures += "$($job.Row.cik): worker exit $ec; stderr=$($job.Stderr)"
        continue
      }
      $validationLog = Join-Path $logDir "$($job.Row.cik).validate.txt"
      $validationExit = Invoke-ValidateProposal -Row $job.Row -LogPath $validationLog
      if ($validationExit -ne 0) {
        $failures += "$($job.Row.cik): validate_proposal failed; log=$validationLog"
      } else {
        Write-Host "validated $($job.Row.cik)"
      }
    }
    $running = $nextRunning
  }

  if ($failures.Count -gt 0) {
    $failurePath = Join-Path $batchDir "dispatch_failures.txt"
    Set-Content -LiteralPath $failurePath -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
    throw "Agent A dispatch completed with $($failures.Count) failure(s); see $failurePath"
  }

  & python -m scripts.agent_a.run_quarter finalize $Quarter --staged --manifest $manifestPath
  & python -m scripts.agent_a.run_quarter gate $Quarter --staged --manifest $manifestPath
  Write-Host "Agent A dispatch complete. Manifest: $manifestPath"
} finally {
  foreach ($job in $running) {
    if (-not $job.Process.HasExited) {
      Stop-TrackedProcessTree -ProcessId $job.Process.Id
    }
  }
  if ($manifestPath) {
    Invoke-ReleaseManifest -ManifestPath $manifestPath
  }
}
