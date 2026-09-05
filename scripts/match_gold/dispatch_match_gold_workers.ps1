param(
  [Parameter(Mandatory = $true)]
  [string] $BatchId,

  # Override the batch dir (default: <repo>\data\output\match_quality\gold\<BatchId>).
  [string] $BatchDir = "",

  # Do not raise without measuring. The Windows sandbox does NOT create a user per run:
  # the machine has exactly two fixed accounts (CodexSandboxOffline / CodexSandboxOnline)
  # and every worker of this shape uses the Offline one, so concurrent workers contend
  # for one credential. The loser gets "CreateProcessWithLogonW failed: 1326" -- not only
  # at launch, but on EVERY process spawn inside its turn, so it burns a full turn and
  # writes nothing. Measured 2026-09-05 on mg3: MaxParallel 1 = 1/1 OK, 3 = 2/3 OK,
  # 6 = 2/8 OK with 16 retries. Every other dispatcher in this repo defaults to 2 for
  # the same reason.
  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 15,

  # Seconds to wait between launching workers, to keep sandbox-user logons from
  # colliding at launch. Does not help with mid-turn contention (see MaxParallel).
  [int] $LaunchStaggerSeconds = 5,

  # Re-dispatch a packet whose verdict failed the deterministic gate, up to this many
  # total attempts. Adjudication is a single model turn; a second attempt costs one
  # worker and recovers the transient truncation/timeout failures.
  [int] $MaxAttempts = 2,

  # Dispatch only these packet ids (canary / targeted re-run).
  [string[]] $PacketId = @(),
  # Cap the number of packets dispatched this run (0 = no cap).
  [int] $Limit = 0,

  # Dispatch packets with NO roamable filing at all (no accessions, or none cached).
  # Off by default: those workers have nothing to read and can only return
  # INSUFFICIENT_EVIDENCE, so they cost a worker and yield no precision signal.
  [switch] $IncludeUncached,
  # Dispatch only packets whose accessions are ALL cached. Default also takes
  # partially-cached packets: a worker can still adjudicate from the filings that are
  # present, and returns INSUFFICIENT_EVIDENCE honestly when it cannot.
  [switch] $RequireFullCache,
  # Re-dispatch packets that already hold a VALID verdict (default: skip them, which
  # is what makes an aborted fleet resumable).
  [switch] $Redispatch,

  # Short worker root. Windows MAX_PATH is trap #3: worker homes must not live under
  # the deep batch dir, and slot ids must be short (w1, not the 16-char MGP id).
  [string] $WorkerRoot = "C:\cxw\mg",

  [string] $CodexBin = "codex.cmd",

  # Circuit breaker: abort the whole fleet after this many workers fail with a Codex
  # usage-limit error (account-level cap, so every remaining worker fails the same
  # way in seconds). 0 disables.
  [int] $UsageLimitAbortThreshold = 1,

  # Keep packets_meta/ + worklist.csv in the batch dir during dispatch (they carry the
  # tier labels the packets are blinded of). Default is to hold them outside the repo.
  [switch] $NoBlindHold,
  # Recover held meta from a crashed run and exit.
  [switch] $RestoreHoldOnly,

  # Print the dispatch plan and exit.
  [switch] $DryRun
)

# Match-gold adjudication fleet dispatcher.
#
# One sandboxed Codex worker per blinded packet; each worker roams the cached filing
# with evidence_cli.py and writes verdicts/<packet_id>.json. Modeled on
# dispatch_agent_b_workers.ps1 (queue + MaxParallel + wrapper + deterministic gate),
# with three differences the 2026-09-04 mg1 canary forced:
#
#  1. Worker homes are a REUSED POOL of MaxParallel short-path slots under $WorkerRoot,
#     not one home per packet. Codex copies its ~308 MB binary into every fresh
#     CODEX_HOME; 300+ fresh homes is hundreds of GB of churn (see the disk-bloat
#     incident in scripts/cleanup_worker_scratch.ps1). Slot state that could leak one
#     packet into the next (history.jsonl, sessions\) is purged before each launch.
#  2. Blinding is enforced by MOVING packets_meta\ and worklist.csv outside the repo
#     for the duration. setup_codex_worker_harness.ps1 hardcodes a repo-root read
#     grant and evidence_cli.py resolves cached HTML relative to the repo, so the
#     grant cannot be narrowed; relocating the tier labels is the cheap structural fix.
#     The canary showed workers do not go looking, but that was compliance by behavior.
#  3. The ACE sweep runs periodically, not just at startup. Every worker run leaks one
#     sandbox-SID ACE onto the verdicts dir and the DACL ceiling is ~1,820 (2026-07-24
#     incident); a 300-packet fleet with retries is a meaningful fraction of that.
#
# Prerequisite: python scripts/match_gold/build_packets.py --batch-id <BatchId>
# Must run from an ELEVATED shell: the worker config sets [windows] sandbox = "elevated"
# and non-admin dispatch fails with logon errors 1223/1326.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

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

function Assert-Elevated {
  $principal = New-Object System.Security.Principal.WindowsPrincipal(
    [System.Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw @"
Refusing to dispatch: this shell is not elevated.

The worker config sets [windows] sandbox = "elevated". Creating the per-run sandbox
user requires admin; without it every worker dies with logon error 1223/1326 and
writes no verdict. Re-launch PowerShell as Administrator (conda-activated, codex
login already done) and re-run.
"@
  }
}

function Quote-ForWrapper {
  param([Parameter(Mandatory = $true)][string] $Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

function Get-SourceCodexHome {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { return $env:CODEX_HOME }
  return Join-Path $HOME ".codex"
}

function Stop-TrackedProcessTree {
  param([Parameter(Mandatory = $true)][int] $ProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) { Stop-TrackedProcessTree -ProcessId ([int]$child.ProcessId) }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Test-UsageLimitHit {
  # Account-level Codex quota error in the worker's stdout event stream. Not an
  # adjudication failure: once hit, every remaining worker fails identically.
  param([Parameter(Mandatory = $true)][string] $StdoutPath)
  if (-not (Test-Path -LiteralPath $StdoutPath -PathType Leaf)) { return $false }
  $text = Get-Content -LiteralPath $StdoutPath -Raw -ErrorAction SilentlyContinue
  if ([string]::IsNullOrEmpty($text)) { return $false }
  return ($text -match "usage limit")
}

function Test-SandboxLogonFailure {
  # Codex's per-run sandbox user could not be logged on: 1326 (bad user/password) or
  # 1223. Seen when several workers launch simultaneously, and when the operator shell
  # is not elevated. Transient in the first case, so it earns extra retries.
  param([Parameter(Mandatory = $true)][string] $StderrPath)
  if (-not (Test-Path -LiteralPath $StderrPath -PathType Leaf)) { return $false }
  $text = Get-Content -LiteralPath $StderrPath -Raw -ErrorAction SilentlyContinue
  if ([string]::IsNullOrEmpty($text)) { return $false }
  return ($text -match "CreateProcessWithLogonW failed")
}

function Invoke-AceSweep {
  param([Parameter(Mandatory = $true)][string] $VerdictsDir)
  & (Join-Path $RepoRoot "scripts\clean_sandbox_acl_orphans.ps1") -Path @($VerdictsDir) | Out-Null
  return $LASTEXITCODE
}

# ---------------------------------------------------------------- batch layout --
if ([string]::IsNullOrWhiteSpace($BatchDir)) {
  $BatchDir = Join-Path $RepoRoot "data\output\match_quality\gold\$BatchId"
}
if (-not (Test-Path -LiteralPath $BatchDir -PathType Container)) {
  throw "Batch dir does not exist: $BatchDir  (run build_packets.py --batch-id $BatchId first)"
}
$BatchDir = (Resolve-Path -LiteralPath $BatchDir).Path
$verdictsDir = Join-Path $BatchDir "verdicts"
$packetsDir  = Join-Path $BatchDir "packets"
$metaDir     = Join-Path $BatchDir "packets_meta"
$worklistPath = Join-Path $BatchDir "worklist.csv"
$logDir      = Join-Path $BatchDir "logs"
$wrapperDir  = Join-Path $BatchDir "wrappers"

# The blind-hold lives OUTSIDE the repo on purpose: anywhere inside it is covered by
# the worker's hardcoded repo-root read grant, so an in-repo "hidden" dir would blind
# nothing. A crashed run leaves HOLD_README.txt in the batch dir pointing here.
$holdRoot = Join-Path $env:LOCALAPPDATA "match_gold_hold\$BatchId"
$holdReadme = Join-Path $BatchDir "HOLD_README.txt"

function Restore-Hold {
  if (-not (Test-Path -LiteralPath $holdRoot -PathType Container)) { return $false }
  $restored = $false
  $heldMeta = Join-Path $holdRoot "packets_meta"
  if ((Test-Path -LiteralPath $heldMeta -PathType Container) -and (-not (Test-Path -LiteralPath $metaDir))) {
    Move-Item -LiteralPath $heldMeta -Destination $metaDir -Force
    $restored = $true
  }
  $heldWorklist = Join-Path $holdRoot "worklist.csv"
  if ((Test-Path -LiteralPath $heldWorklist -PathType Leaf) -and (-not (Test-Path -LiteralPath $worklistPath))) {
    Move-Item -LiteralPath $heldWorklist -Destination $worklistPath -Force
    $restored = $true
  }
  Remove-Item -LiteralPath $holdReadme -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $holdRoot -Recurse -Force -ErrorAction SilentlyContinue
  return $restored
}

if ($RestoreHoldOnly) {
  if (Restore-Hold) { Write-Host "Restored held blinding artifacts into $BatchDir" }
  else { Write-Host "Nothing held for batch $BatchId (nothing to restore)." }
  exit 0
}

# A previous crashed run may still be holding them; recover before reading.
$null = Restore-Hold

if (-not (Test-Path -LiteralPath $worklistPath -PathType Leaf)) {
  throw "worklist.csv missing from $BatchDir. If a prior run crashed mid-dispatch, re-run with -RestoreHoldOnly."
}

Assert-OutsideCodexSession
Assert-Elevated

$sourceHome = Get-SourceCodexHome
$sourceAuth = Join-Path $sourceHome "auth.json"
$hasFileAuth = Test-Path -LiteralPath $sourceAuth -PathType Leaf
$hasApiKey = -not [string]::IsNullOrWhiteSpace($env:CODEX_API_KEY)
if (-not ($hasFileAuth -or $hasApiKey)) {
  throw "No Codex auth found. Expected $sourceAuth or CODEX_API_KEY."
}
if ($MaxParallel -lt 1) { throw "MaxParallel must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }
if ($MaxAttempts -lt 1) { throw "MaxAttempts must be >= 1." }

# ------------------------------------------------------------------ selection --
$worklist = @(Import-Csv -LiteralPath $worklistPath)
if ($worklist.Count -eq 0) { throw "worklist.csv has no rows." }

# One interpreter start classifies every existing verdict, so a fleet aborted by the
# circuit breaker (or a killed shell) resumes by simply being re-run.
$scanJson = & python (Join-Path $RepoRoot "scripts\match_gold\validate_verdict.py") --scan-batch $BatchDir
if ($LASTEXITCODE -ne 0) { throw "Verdict scan failed for $BatchDir" }
$scan = $scanJson | ConvertFrom-Json
$alreadyValid = @{}
foreach ($pid_ in @($scan.valid)) { $alreadyValid[$pid_] = $true }

# Select on MEASURED cache coverage, not on worklist.has_cached_filing. That column is
# an all-or-nothing snapshot taken at build time: it reads False both for a packet with
# no accessions at all and for one with 5 of 6 filings cached, which are different
# problems -- and the second is still adjudicable. Measuring here also means selection
# reflects the cache as it is now, not as it was when the batch was built.
$covJson = & python (Join-Path $RepoRoot "scripts\match_gold\cache_coverage.py") --batch-dir $BatchDir --json
if ($LASTEXITCODE -ne 0) { throw "cache_coverage.py failed for $BatchDir" }
$coverage = $covJson | ConvertFrom-Json

$wanted = @("full", "partial")
if ($RequireFullCache) { $wanted = @("full") }
if ($IncludeUncached) { $wanted = @("full", "partial", "none", "no_acc") }

$selected = @()
$skipCoverage = 0
$skipDone = 0
$catCount = @{}
foreach ($row in $worklist) {
  $cat = "unknown"
  if ($coverage.PSObject.Properties.Name -contains $row.packet_id) {
    $cat = $coverage.($row.packet_id).category
  }
  if ($catCount.ContainsKey($cat)) { $catCount[$cat]++ } else { $catCount[$cat] = 1 }
  if ($PacketId.Count -gt 0 -and ($PacketId -notcontains $row.packet_id)) { continue }
  if ($wanted -notcontains $cat) { $skipCoverage++; continue }
  if ($alreadyValid.ContainsKey($row.packet_id) -and -not $Redispatch) { $skipDone++; continue }
  $selected += $row
}
Write-Host ("cache coverage: " + (($catCount.Keys | Sort-Object | ForEach-Object { "$_=$($catCount[$_])" }) -join "  ") +
  "   [dispatching: $($wanted -join ',')]")
if ($Limit -gt 0 -and $selected.Count -gt $Limit) {
  $selected = $selected[0..($Limit - 1)]
}

Write-Host ("match-gold dispatch: batch={0} worklist={1} selected={2} (skipped: {3} no roamable filing, {4} already valid)" -f `
  $BatchId, $worklist.Count, $selected.Count, $skipCoverage, $skipDone)

if ($DryRun) {
  $selected | Select-Object packet_id, packet_type, stratum, cik, n_rows, n_edges | Format-Table -AutoSize
  exit 0
}
if ($selected.Count -eq 0) {
  Write-Host "Nothing to dispatch."
  exit 0
}

# -------------------------------------------------------------- worker grants --
$envJson = & python (Join-Path $RepoRoot "scripts\match_gold\worker_env.py")
if ($LASTEXITCODE -ne 0) { throw "worker_env.py failed." }
$workerEnv = $envJson | ConvertFrom-Json
$readGrants = @(@($workerEnv.read_dirs) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
Write-Host ("worker python: {0}" -f $workerEnv.python)
Write-Host ("read grants:   {0}" -f ($readGrants -join "; "))

New-Item -ItemType Directory -Force -Path $logDir, $wrapperDir, $verdictsDir | Out-Null

if ((Invoke-AceSweep -VerdictsDir $verdictsDir) -ne 0) {
  throw "Verdicts-dir DACL near the 64KB ceiling even after the orphan sweep; aborting before stranding workers."
}

# Slot pool: MaxParallel reused worker homes on a short path (MAX_PATH trap).
$slotRoot = Join-Path $WorkerRoot $BatchId
$slots = @()
for ($i = 1; $i -le $MaxParallel; $i++) {
  $slots += [pscustomobject]@{
    Id      = "w$i"
    Home    = (Join-Path $slotRoot "w$i")
    Runroot = (Join-Path $slotRoot "w${i}r")
    Busy    = $false
  }
}
New-Item -ItemType Directory -Force -Path (@($slotRoot) + ($slots | ForEach-Object { $_.Home }) + ($slots | ForEach-Object { $_.Runroot })) | Out-Null

# ------------------------------------------------------------------- blinding --
if (-not $NoBlindHold) {
  New-Item -ItemType Directory -Force -Path $holdRoot | Out-Null
  if (Test-Path -LiteralPath $metaDir -PathType Container) {
    Move-Item -LiteralPath $metaDir -Destination (Join-Path $holdRoot "packets_meta") -Force
  }
  Move-Item -LiteralPath $worklistPath -Destination (Join-Path $holdRoot "worklist.csv") -Force
  Set-Content -LiteralPath $holdReadme -Encoding ASCII -Value @"
Blinding hold in progress for match-gold batch $BatchId.

packets_meta\ and worklist.csv (which carry the stratum / match_method tier labels the
packets are blinded of) were moved to:
    $holdRoot
for the duration of the worker dispatch, because the Codex sandbox grants read on the
whole repo root and cannot be narrowed (evidence_cli.py resolves cached filing HTML
relative to the repo).

They are moved back automatically when the dispatcher exits. If this file still exists,
the dispatcher died; recover with:
    powershell -File scripts\match_gold\dispatch_match_gold_workers.ps1 -BatchId $BatchId -RestoreHoldOnly
"@
  Write-Host "blinding: packets_meta + worklist held at $holdRoot"
}

# ------------------------------------------------------------------ dispatch ---
$queue = New-Object System.Collections.Queue
foreach ($row in $selected) {
  $queue.Enqueue([pscustomobject]@{ Row = $row; Attempt = 1 })
}

$running = @()
$results = @()
$failures = @()
$usageLimitCount = 0
$usageLimitHit = $false
$completed = 0
$sinceSweep = 0
$total = $selected.Count
$startedAt = Get-Date

try {
  while (($queue.Count -gt 0) -or ($running.Count -gt 0)) {
    while (($queue.Count -gt 0) -and ($running.Count -lt $MaxParallel) -and (-not $usageLimitHit)) {
      $slot = $slots | Where-Object { -not $_.Busy } | Select-Object -First 1
      if ($null -eq $slot) { break }
      $item = $queue.Dequeue()
      $row = $item.Row
      $pkt = $row.packet_id

      # Purge cross-packet state from the reused slot home. sessions\ is normally
      # harvested by run_codex_worker.ps1, history.jsonl is not -- and it holds the
      # previous packet's prompt, which would be a blinding leak between packets.
      foreach ($stale in @("history.jsonl", "sessions")) {
        Remove-Item -LiteralPath (Join-Path $slot.Home $stale) -Recurse -Force -ErrorAction SilentlyContinue
      }

      & (Join-Path $RepoRoot "scripts\setup_codex_worker_harness.ps1") `
        -WorkerHome $slot.Home `
        -WorkerRunroot $slot.Runroot `
        -WriteDirs @($verdictsDir) `
        -ReadDirs $readGrants `
        -EnvInherit "all" `
        -AllowUserSite | Out-Null

      if ($hasFileAuth) {
        Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $slot.Home "auth.json") -Force
      }

      $wrapperPath = Join-Path $wrapperDir "$pkt.ps1"
      $runScript = Join-Path $RepoRoot "scripts\run_codex_worker.ps1"
      $wrapper = @"
`$ErrorActionPreference = 'Stop'
& $(Quote-ForWrapper $runScript) ``
  -PromptPath $(Quote-ForWrapper $row.prompt_path) ``
  -WorkerHome $(Quote-ForWrapper $slot.Home) ``
  -WorkerRunroot $(Quote-ForWrapper $slot.Runroot) ``
  -CodexBin $(Quote-ForWrapper $CodexBin) ``
  -TraceDir $(Quote-ForWrapper $logDir) ``
  -TracePrefix $(Quote-ForWrapper "${pkt}__") ``
  -NoSetup
exit `$LASTEXITCODE
"@
      Set-Content -LiteralPath $wrapperPath -Value $wrapper -Encoding ASCII

      $stdout = Join-Path $logDir "$pkt.stdout.jsonl"
      $stderr = Join-Path $logDir "$pkt.stderr.txt"
      $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$wrapperPath`"") `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
      # Touch .Handle so the object caches the OS handle; without it .ExitCode is
      # frequently $null after the process exits (well-known PowerShell gotcha).
      $null = $proc.Handle

      $slot.Busy = $true
      $running += [pscustomobject]@{
        Row = $row; Attempt = $item.Attempt; Slot = $slot
        Process = $proc; Started = Get-Date; Stdout = $stdout; Stderr = $stderr
      }

      # Stagger the next launch so concurrent sandbox-user creation does not race.
      if (($queue.Count -gt 0) -and ($LaunchStaggerSeconds -gt 0)) {
        Start-Sleep -Seconds $LaunchStaggerSeconds
      }
    }

    Start-Sleep -Seconds 2

    $nextRunning = @()
    foreach ($job in $running) {
      $proc = $job.Process
      $pkt = $job.Row.packet_id
      $elapsed = (Get-Date) - $job.Started
      $timedOut = $false

      if (-not $proc.HasExited) {
        if ($elapsed.TotalMinutes -lt $TimeoutMinutes) { $nextRunning += $job; continue }
        Stop-TrackedProcessTree -ProcessId $proc.Id
        $timedOut = $true
      }

      $job.Slot.Busy = $false
      # Counts every worker RUN, retries included: each run leaks one ACE regardless
      # of outcome. $completed counts PACKETS and is incremented past the retry gate.
      $sinceSweep++

      $ec = $null
      if (-not $timedOut) { $ec = $proc.ExitCode }

      # A confirmed non-zero exit is a hard failure; $null means the handle lost the
      # code, so fall through to the deterministic gate, which is authoritative.
      $status = ""
      $detail = ""
      $verdict = ""
      $confidence = ""
      if ($timedOut) {
        $status = "TIMEOUT"; $detail = "killed after $TimeoutMinutes minute(s)"
      } elseif ($null -ne $ec -and $ec -ne 0) {
        if (Test-SandboxLogonFailure -StderrPath $job.Stderr) {
          $status = "SANDBOX_LOGON"; $detail = "sandbox user logon failed; stderr=$($job.Stderr)"
        } else {
          $status = "WORKER_EXIT"; $detail = "exit $ec; stderr=$($job.Stderr)"
        }
      } else {
        $gateLog = Join-Path $logDir "$pkt.validate.txt"
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
          # Merged streams + explicit UTF-8: a bare `*>` writes UTF-16 in PS 5.1.
          & python (Join-Path $RepoRoot "scripts\match_gold\validate_verdict.py") `
            --packet $job.Row.packet_path --verdict $job.Row.verdict_path *>&1 |
            Out-File -LiteralPath $gateLog -Encoding utf8
          $gateExit = $LASTEXITCODE
        } finally { $ErrorActionPreference = $prevEap }
        if ($gateExit -eq 0) {
          $status = "OK"
          try {
            $doc = Get-Content -LiteralPath $job.Row.verdict_path -Raw | ConvertFrom-Json
            $verdict = "$($doc.verdict)"
            $confidence = "$($doc.confidence)"
          } catch { }
        } else {
          $status = "INVALID_VERDICT"; $detail = "gate log=$gateLog"
        }
      }

      if ($status -ne "OK") {
        if (($UsageLimitAbortThreshold -gt 0) -and (Test-UsageLimitHit -StdoutPath $job.Stdout)) {
          $usageLimitCount++
          $status = "USAGE_LIMIT"
          if ($usageLimitCount -ge $UsageLimitAbortThreshold) { $usageLimitHit = $true }
        } elseif ($job.Attempt -lt (& { if ($status -eq "SANDBOX_LOGON") { $MaxAttempts + 2 } else { $MaxAttempts } })) {
          # A sandbox-logon failure is a launch race, not an adjudication failure, so it
          # gets extra attempts; by the time it is re-dequeued the contending worker is
          # long gone.
          Write-Host ("  retry {0} (attempt {1}): {2}" -f $pkt, $job.Attempt, $status)
          $queue.Enqueue([pscustomobject]@{ Row = $job.Row; Attempt = ($job.Attempt + 1) })
          continue
        }
        $failures += "${pkt}: $status ($detail)"
      }

      $completed++
      $results += [pscustomobject]@{
        packet_id = $pkt
        packet_type = $job.Row.packet_type
        status = $status
        attempt = $job.Attempt
        verdict = $verdict
        confidence = $confidence
        seconds = [math]::Round($elapsed.TotalSeconds, 1)
        detail = $detail
      }

      $pct = [math]::Round(100.0 * $completed / [math]::Max($total, 1), 1)
      $rate = ((Get-Date) - $startedAt).TotalMinutes
      Write-Host ("[{0}/{1} {2}%] {3} {4} {5} ({6}s)" -f `
        $completed, $total, $pct, $pkt, $status, $verdict, [math]::Round($elapsed.TotalSeconds, 0))
      if ($completed % 25 -eq 0) {
        Write-Host ("  ... {0} done in {1} min; {2} queued, {3} running" -f `
          $completed, [math]::Round($rate, 1), $queue.Count, $nextRunning.Count)
      }
    }
    $running = $nextRunning

    # Periodic ACE sweep: each finished worker leaves one dead sandbox-SID ACE on the
    # verdicts dir, and the DACL ceiling is ~1,820 entries.
    if ($sinceSweep -ge 100) {
      $sinceSweep = 0
      if ((Invoke-AceSweep -VerdictsDir $verdictsDir) -ne 0) {
        Write-Warning "Verdicts-dir DACL still above the sweep threshold; watch for sandbox setup failures."
      }
    }

    if ($usageLimitHit) {
      Write-Host "CIRCUIT BREAKER: Codex usage limit hit. Aborting dispatch." -ForegroundColor Yellow
      $queue.Clear()
      foreach ($job in $running) {
        if (-not $job.Process.HasExited) { Stop-TrackedProcessTree -ProcessId $job.Process.Id }
      }
      $running = @()
    }
  }
} finally {
  foreach ($job in $running) {
    if (-not $job.Process.HasExited) { Stop-TrackedProcessTree -ProcessId $job.Process.Id }
  }
  if (-not $NoBlindHold) {
    $null = Restore-Hold
    Write-Host "blinding: packets_meta + worklist restored to $BatchDir"
  }
  if ($results.Count -gt 0) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $results | Export-Csv -LiteralPath (Join-Path $logDir "dispatch_results_$stamp.csv") -NoTypeInformation -Encoding UTF8
  }
  if ($failures.Count -gt 0) {
    Set-Content -LiteralPath (Join-Path $BatchDir "dispatch_failures.txt") `
      -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
  }
}

$ok = @($results | Where-Object { $_.status -eq "OK" }).Count
Write-Host ""
Write-Host ("match-gold dispatch complete: {0}/{1} OK, {2} failed, {3} min elapsed" -f `
  $ok, $total, $failures.Count, [math]::Round(((Get-Date) - $startedAt).TotalMinutes, 1))

if ($usageLimitHit) {
  throw ("Dispatch ABORTED by circuit breaker: Codex USAGE LIMIT reached. This is an " +
    "account-level quota cap. Wait for the reset (time is in a worker stdout log under " +
    "$logDir) then re-run the same command -- packets with valid verdicts are skipped.")
}
if ($failures.Count -gt 0) {
  Write-Warning ("$($failures.Count) packet(s) failed after $MaxAttempts attempt(s); see " +
    (Join-Path $BatchDir "dispatch_failures.txt"))
}
