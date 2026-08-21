param(
  [Parameter(Mandatory = $true)]
  [string] $BatchId,

  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string[]] $ReviewId = @(),
  [string] $CodexBin = "codex.cmd",

  # Circuit breaker: stop the whole dispatch after this many workers fail with a
  # Codex "usage limit" error. The cap is account-level, so once it is hit every
  # remaining worker fails the same way in seconds; 1 is definitive. Set to 0 to
  # disable the breaker (old behaviour: try every worker, then throw at the end).
  [int] $UsageLimitAbortThreshold = 1,

  # Optional verdict-dir override (scratch dir for stability re-runs that must
  # not touch the production verdict store). Passed through to the preflight.
  [string] $VerdictsDirOverride = ""
)

# Agent B1 adjudication dispatcher. The B analog of dispatch_agent_a_workers.ps1:
# run the deterministic preflight (which builds the manifest + per-bundle blinded
# prompts), launch one sandboxed Codex worker per dispatched item (write-grant scoped
# to the verdicts dir), validate each verdict leaf, then finalize (collect + route).
#
# Prerequisite: the batch worklist must already exist --
#   python -m scripts.agent_b.run_review discover <BatchId> [--lane ... --engine ... --limit N]
#
# NOTE: shares run_codex_worker.ps1 + setup_codex_worker_harness.ps1 with Agent A.
# The dispatch LOOP is duplicated from A on purpose for now (M1): refactoring A's only
# working external dispatcher into a shared core is deferred until an operator can
# smoke-test both. See docs/adjudication_architecture/B_build_plan_codex_fleet.md (3.2).

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
  $args = @("-m", "scripts.agent_b.dispatch_preflight", "--batch-id", $BatchId, "--reserve")
  foreach ($OneId in $ReviewId) {
    $args += @("--review-id", $OneId)
  }
  if (-not [string]::IsNullOrWhiteSpace($VerdictsDirOverride)) {
    $args += @("--verdicts-dir", $VerdictsDirOverride)
  }
  $json = & python @args
  if ($LASTEXITCODE -ne 0) {
    throw "Agent B dispatch preflight failed."
  }
  return $json | ConvertFrom-Json
}

function Invoke-ReleaseManifest {
  param([Parameter(Mandatory = $true)][string] $ManifestPath)
  & python -m scripts.agent_b.dispatch_preflight --release-manifest $ManifestPath | Out-Null
}

function New-WorkerWrapper {
  param(
    [Parameter(Mandatory = $true)] $Row,
    [Parameter(Mandatory = $true)][string] $WorkerHome,
    [Parameter(Mandatory = $true)][string] $WorkerRunroot,
    [Parameter(Mandatory = $true)][string] $WrapperPath,
    [Parameter(Mandatory = $true)][string] $TraceDir,
    [Parameter(Mandatory = $true)][string] $TracePrefix
  )

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

function Test-UsageLimitHit {
  # True when the worker's Codex stdout contains a usage-limit / quota error. This
  # is an account-level cap (e.g. {"type":"error","message":"You've hit your usage
  # limit ..."} followed by turn.failed), not an adjudication failure -- it drives
  # the circuit breaker so we stop dispatching instead of burning every worker.
  param([Parameter(Mandatory = $true)][string] $StdoutPath)
  if (-not (Test-Path -LiteralPath $StdoutPath -PathType Leaf)) {
    return $false
  }
  $text = Get-Content -LiteralPath $StdoutPath -Raw -ErrorAction SilentlyContinue
  if ([string]::IsNullOrEmpty($text)) {
    return $false
  }
  return ($text -match "hit your usage limit") -or ($text -match "usage limit")
}

function Invoke-ValidateVerdict {
  param(
    [Parameter(Mandatory = $true)] $Row,
    [Parameter(Mandatory = $true)][string] $LogPath
  )
  # A FAILING validator prints "INVALID: ..." to stderr; under the script-wide
  # ErrorActionPreference=Stop, PS 5.1 wraps that stderr line in a terminating
  # NativeCommandError and kills the whole dispatch (2026-07-24 q4t0 crash at
  # 35/47) instead of counting one failure. Relax EAP around the native call;
  # the exit code is the only signal we use.
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    # Merge streams + explicit UTF-8: the bare `*> $LogPath` wrote UTF-16 LE
    # (PS 5.1 default), which naive UTF-8 readers misparse.
    & python -m scripts.review_agent.validate_leaf_verdicts --verdict $Row.verdict_path *>&1 |
      Out-File -LiteralPath $LogPath -Encoding utf8
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prevEap
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
$verdictsDir = $manifest.verdicts_dir

# ACE-leak guard (2026-07-24): every worker run leaks one sandbox-SID ACE onto the
# verdicts dir; at ~1,820 the DACL is full and ALL sandbox setups fail
# (SetEntriesInAclW 87). Sweep dead SIDs and fail closed if still near the ceiling.
& (Join-Path $PSScriptRoot "clean_sandbox_acl_orphans.ps1") -Path @($verdictsDir)
if ($LASTEXITCODE -ne 0) {
  Invoke-ReleaseManifest -ManifestPath $manifestPath
  throw "Verdicts-dir DACL near the 64KB ceiling even after orphan sweep; aborting before stranding workers."
}

# The worker prompt names an absolute Python interpreter (the one preflight ran under,
# which has the project deps). Grant the sandbox READ on that interpreter's import roots
# (its dir + env/user site-packages, reported by preflight as worker_read_dirs) so the
# worker can execute it AND import pandas et al.; inherit the full operator env so DLLs
# resolve; allow the user site (the deps live there, not in the conda env).
$workerPython = $manifest.worker_python
$readGrants = @()
if (-not [string]::IsNullOrWhiteSpace($workerPython)) {
  $readGrants += (Split-Path -Parent $workerPython)
}
if ($manifest.worker_read_dirs) {
  $readGrants += @($manifest.worker_read_dirs)
}
$readGrants = @($readGrants | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
$logDir = Join-Path $batchDir "logs"
$wrapperDir = Join-Path $batchDir "wrappers"
$homeDir = Join-Path $batchDir "worker_home"
$runrootDir = Join-Path $batchDir "worker_runroot"
New-Item -ItemType Directory -Force -Path $logDir, $wrapperDir, $homeDir, $runrootDir | Out-Null

if (($manifest.rows | Measure-Object).Count -eq 0) {
  Write-Host "Agent B dispatch: nothing to dispatch ($($manifest.n_auto_resolved) auto-resolved). Finalizing."
  & python -m scripts.agent_b.run_review finalize $BatchId
  Invoke-ReleaseManifest -ManifestPath $manifestPath
  exit 0
}

$queue = New-Object System.Collections.Queue
foreach ($row in $manifest.rows) {
  $queue.Enqueue($row)
}

$running = @()
$failures = @()
$usageLimitCount = 0
$usageLimitHit = $false

try {
  while (($queue.Count -gt 0) -or ($running.Count -gt 0)) {
    while (($queue.Count -gt 0) -and ($running.Count -lt $MaxParallel) -and (-not $usageLimitHit)) {
      $row = $queue.Dequeue()
      $idSafe = $row.review_id
      $workerHome = Join-Path $homeDir $idSafe
      $workerRunroot = Join-Path $runrootDir $idSafe
      New-Item -ItemType Directory -Force -Path $workerHome, $workerRunroot | Out-Null

      & (Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1") `
        -WorkerHome $workerHome `
        -WorkerRunroot $workerRunroot `
        -WriteDirs @($verdictsDir) `
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
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

      # Touch .Handle so the Process object caches the OS handle; without this, a
      # Start-Process -PassThru object frequently returns $null for .ExitCode after the
      # process exits (a well-known PowerShell gotcha).
      $null = $proc.Handle

      $running += [pscustomobject]@{
        Row = $row
        Process = $proc
        Started = Get-Date
        Stdout = $stdout
        Stderr = $stderr
      }
      Write-Host "launched $($row.review_id) pid=$($proc.Id)"
    }

    Start-Sleep -Seconds 2

    $nextRunning = @()
    foreach ($job in $running) {
      $proc = $job.Process
      $elapsed = (Get-Date) - $job.Started
      if (-not $proc.HasExited -and $elapsed.TotalMinutes -ge $TimeoutMinutes) {
        Stop-TrackedProcessTree -ProcessId $proc.Id
        $failures += "$($job.Row.review_id): TIMEOUT after $TimeoutMinutes minute(s)"
        continue
      }
      if (-not $proc.HasExited) {
        $nextRunning += $job
        continue
      }
      # Only a CONFIRMED non-zero exit is a hard failure. A $null exit code means the
      # handle didn't capture it; fall through to validate_leaf_verdicts, the
      # authoritative deterministic check (it re-parses the written verdict).
      $ec = $proc.ExitCode
      if ($null -ne $ec -and $ec -ne 0) {
        if (($UsageLimitAbortThreshold -gt 0) -and (Test-UsageLimitHit -StdoutPath $job.Stdout)) {
          $usageLimitCount += 1
          $failures += "$($job.Row.review_id): Codex usage limit hit (worker exit $ec); see $($job.Stdout)"
          if ($usageLimitCount -ge $UsageLimitAbortThreshold) { $usageLimitHit = $true }
        } else {
          $failures += "$($job.Row.review_id): worker exit $ec; stderr=$($job.Stderr)"
        }
        continue
      }
      $validationLog = Join-Path $logDir "$($job.Row.review_id).validate.txt"
      $validationExit = Invoke-ValidateVerdict -Row $job.Row -LogPath $validationLog
      if ($validationExit -ne 0) {
        if (($UsageLimitAbortThreshold -gt 0) -and (Test-UsageLimitHit -StdoutPath $job.Stdout)) {
          $usageLimitCount += 1
          $failures += "$($job.Row.review_id): Codex usage limit hit (no verdict written); see $($job.Stdout)"
          if ($usageLimitCount -ge $UsageLimitAbortThreshold) { $usageLimitHit = $true }
        } else {
          $failures += "$($job.Row.review_id): verdict validation failed; log=$validationLog"
        }
      } else {
        Write-Host "validated $($job.Row.review_id)"
      }
    }
    $running = $nextRunning

    if ($usageLimitHit) {
      # Circuit breaker tripped. The account quota is exhausted, so every queued or
      # in-flight worker would fail the same way. Stop launching, drain the queue,
      # and kill in-flight workers (they hold no verdict yet -- prep_retry re-splits
      # the undecided rids on the next run, so nothing is lost).
      Write-Host "CIRCUIT BREAKER: Codex usage limit hit ($usageLimitCount). Aborting dispatch." -ForegroundColor Yellow
      $queue.Clear()
      foreach ($job in $running) {
        if (-not $job.Process.HasExited) {
          Stop-TrackedProcessTree -ProcessId $job.Process.Id
        }
      }
      $running = @()
    }
  }

  if ($usageLimitHit) {
    $failurePath = Join-Path $batchDir "dispatch_failures.txt"
    Set-Content -LiteralPath $failurePath -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
    throw ("Agent B dispatch ABORTED by circuit breaker: Codex USAGE LIMIT reached after " +
      "$($failures.Count) failure(s). This is an account-level quota cap -- NOT a PRECHECK_FAIL " +
      "and NOT stale worker-home markers. Re-running now will not help. Wait for the Codex quota " +
      "to reset (the reset time is in a worker stdout log under the batch logs dir) or add credits, " +
      "then re-run; prep_retry will re-split the still-undecided rids. See $failurePath")
  }

  if ($failures.Count -gt 0) {
    $failurePath = Join-Path $batchDir "dispatch_failures.txt"
    Set-Content -LiteralPath $failurePath -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
    throw "Agent B dispatch completed with $($failures.Count) failure(s); see $failurePath"
  }

  if ([string]::IsNullOrWhiteSpace($VerdictsDirOverride)) {
    & python -m scripts.agent_b.run_review finalize $BatchId
  } else {
    Write-Host "Scratch verdicts-dir run: skipping finalize (it reads the production store)."
  }
  Write-Host "Agent B dispatch complete. Manifest: $manifestPath"
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
