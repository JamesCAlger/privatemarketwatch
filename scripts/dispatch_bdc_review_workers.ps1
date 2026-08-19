param(
  [Parameter(Mandatory = $true)]
  [string] $BatchId,

  # CSV with a review_id column (BDCSRC_* ids from the bdc_cik_review worklist).
  [Parameter(Mandatory = $true)]
  [string] $WorklistCsv,

  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string] $CodexBin = "codex.cmd",
  [int] $UsageLimitAbortThreshold = 1
)

# Codex fleet dispatcher for the bdc_cik_review (source_recon) adjudication lane --
# the Q4-campaign tier-1 analog of dispatch_agent_b_workers.ps1. Differences from B1:
# no python tooling in the sandbox (each bundle under data/output/bdc_cik_review/bundles
# is self-contained; the worker reads ONE bundle and writes ONE verdict), per-item
# prompts are generated here from prompts/bdc_cik_review_prompt.md, no lock layer
# (single-dispatcher machine; a pre-existing verdict skips the item), and the final
# validation is the lane's own schema validator (scripts/bdc_cik_review/validate_verdicts.py)
# plus check_tier_coverage downstream. ACE-leak guard runs first (2026-07-24 DACL incident).
# ASCII-only output.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReviewDir = Join-Path $RepoRoot "data\output\bdc_cik_review"
$BundlesDir = Join-Path $ReviewDir "bundles"
$VerdictsDir = Join-Path $ReviewDir "verdicts"
$TemplatePath = Join-Path $RepoRoot "prompts\bdc_cik_review_prompt.md"
$BatchDir = Join-Path $ReviewDir "fleet\$BatchId"

function Assert-OutsideCodexSession {
  $signals = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($signals.Count -gt 0) {
    throw "Refusing to dispatch external Codex workers from inside an active Codex session: $($signals -join ', ')"
  }
}

function Quote-ForWrapper {
  param([Parameter(Mandatory = $true)][string] $Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

function Test-UsageLimitHit {
  param([Parameter(Mandatory = $true)][string] $StdoutPath)
  if (-not (Test-Path -LiteralPath $StdoutPath -PathType Leaf)) { return $false }
  $text = Get-Content -LiteralPath $StdoutPath -Raw -ErrorAction SilentlyContinue
  if ([string]::IsNullOrEmpty($text)) { return $false }
  return ($text -match "hit your usage limit") -or ($text -match "usage limit")
}

function Test-VerdictLeaf {
  # Per-item validation: id match + full lane schema/bundle checks via
  # validate_one_verdict.py. (validate_verdicts.py --all is NOT usable as a
  # batch gate -- it checks worklist membership across the whole store, so
  # ~1,900 historical verdicts from retired worklists fail it.)
  param(
    [Parameter(Mandatory = $true)][string] $Rid,
    [Parameter(Mandatory = $true)][string] $LogPath
  )
  $path = Join-Path $VerdictsDir "$Rid.json"
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return "missing" }
  try {
    $v = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch { return "unparseable" }
  if ($v.review_id -ne $Rid) { return "id_mismatch" }
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & python (Join-Path $PSScriptRoot "bdc_cik_review\validate_one_verdict.py") $path *> $LogPath
  $vex = $LASTEXITCODE
  $ErrorActionPreference = $prevEap
  if ($vex -ne 0) { return "schema_invalid (see $LogPath)" }
  return "ok"
}

function Stop-TrackedProcessTree {
  param([Parameter(Mandatory = $true)][int] $ProcessId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) { Stop-TrackedProcessTree -ProcessId ([int]$child.ProcessId) }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if ($MaxParallel -lt 1) { throw "MaxParallel must be >= 1." }
if ($TimeoutMinutes -lt 1) { throw "TimeoutMinutes must be >= 1." }
Assert-OutsideCodexSession

$sourceHome = if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$sourceAuth = Join-Path $sourceHome "auth.json"
$hasFileAuth = Test-Path -LiteralPath $sourceAuth -PathType Leaf
if (-not ($hasFileAuth -or -not [string]::IsNullOrWhiteSpace($env:CODEX_API_KEY))) {
  throw "No Codex auth found. Expected $sourceAuth or CODEX_API_KEY."
}
if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
  throw "Missing prompt template: $TemplatePath"
}

# ACE-leak guard (see agent_changelog 2026-07-24 DACL entry).
& (Join-Path $PSScriptRoot "clean_sandbox_acl_orphans.ps1") -Path @($VerdictsDir)
if ($LASTEXITCODE -ne 0) {
  throw "Verdicts-dir DACL near the 64KB ceiling even after orphan sweep; aborting."
}

$rows = Import-Csv -LiteralPath $WorklistCsv
if (-not $rows -or -not ($rows[0].PSObject.Properties.Name -contains "review_id")) {
  throw "Worklist $WorklistCsv has no rows or no review_id column."
}

$logDir = Join-Path $BatchDir "logs"
$wrapperDir = Join-Path $BatchDir "wrappers"
$promptDir = Join-Path $BatchDir "prompts"
$homeDir = Join-Path $BatchDir "worker_home"
$runrootDir = Join-Path $BatchDir "worker_runroot"
New-Item -ItemType Directory -Force -Path $logDir, $wrapperDir, $promptDir, $homeDir, $runrootDir | Out-Null

$template = Get-Content -LiteralPath $TemplatePath -Raw

$queue = New-Object System.Collections.Queue
$skipped = @()
foreach ($row in $rows) {
  $rid = $row.review_id.Trim()
  if (-not $rid) { continue }
  $bundle = Join-Path $BundlesDir "$rid.json"
  $verdict = Join-Path $VerdictsDir "$rid.json"
  if (-not (Test-Path -LiteralPath $bundle -PathType Leaf)) {
    $skipped += "$rid : bundle missing ($bundle)"
    continue
  }
  if (Test-Path -LiteralPath $verdict -PathType Leaf) {
    # 2026-05-28 full-pool accounting wrote 1,174 "Auto-drafted" placeholder
    # verdicts (bookkeeping, not adjudication -- check_tier_coverage counts them
    # as NOT covered). Archive those and dispatch; skip only GENUINE verdicts.
    $notes = ""
    try {
      $existing = Get-Content -LiteralPath $verdict -Raw -Encoding UTF8 | ConvertFrom-Json
      $notes = [string]$existing.reviewer_notes
    } catch { $notes = "" }
    if ($notes -and $notes.StartsWith("Auto-drafted")) {
      $archiveDir = Join-Path $BatchDir "placeholder_verdicts_archive"
      New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
      Move-Item -LiteralPath $verdict -Destination $archiveDir -Force
      Write-Host "archived placeholder verdict for $rid (re-dispatching)"
    } else {
      $skipped += "$rid : genuine verdict already exists (skipped, not re-adjudicated)"
      continue
    }
  }
  $promptPath = Join-Path $promptDir "$rid.md"
  $assignment = @(
    $template.TrimEnd(),
    "",
    "## Schema Compliance (deterministic validator -- violations reject the verdict)",
    "",
    "Measured 2026-07-24: 8 of 17 fleet verdicts were rejected on these exact rules;",
    "they are enforced by pipeline.bdc_cik_review.validate_verdict_file, not advisory.",
    "",
    "1. ``row_classification`` must be EXACTLY one of: POSITION_ROW, AGGREGATE_HEADER,",
    "   SUBTOTAL_ROW, CONTINUATION_ROW, COMPARATIVE_PERIOD_ROW, UNCLASSIFIABLE,",
    "   INSUFFICIENT_EVIDENCE. No variants (AGGREGATE_OR_HEADER and",
    "   NOT_TARGET_POSITION_ROW are rejected).",
    "2. Every HTML evidence id you list in ``evidence_refs`` (html_template_selection,",
    "   html_detected_soi_candidates, html_table_grid_excerpt, html_period_assignment,",
    "   html_row_classification_candidates, html_source_row_coordinate_candidates)",
    "   REQUIRES a full coordinate entry in ``html_citations`` (evidence_ref,",
    "   table_index, row_index, cell_indices, row_classification, reason). If you",
    "   cannot cite coordinates for it, OMIT it from evidence_refs. Only",
    "   ``html_artifact`` and ``xbrl_rows_same_accession`` are exempt.",
    "3. If ``reconciliation_diagnosis`` is XBRL_ONLY_NO_HTML_COORDINATE or",
    "   INSUFFICIENT_EVIDENCE, evidence_refs must contain NONE of the coordinate-class",
    "   HTML ids from rule 2 (with or without citations).",
    "4. Diagnoses REAL_POSITION_MISSING_FROM_UNIFIED, HTML_PRESENT_TABLE_NOT_PARSED,",
    "   AGGREGATE_OR_HEADER, COMPARATIVE_PERIOD, ZERO_OR_UNFUNDED_NON_INDEX_ROW",
    "   REQUIRE at least one coordinate-level html_citation.",
    "5. REAL_POSITION_MISSING_FROM_UNIFIED citations cannot carry row_classification",
    "   AGGREGATE_HEADER, SUBTOTAL_ROW, COMPARATIVE_PERIOD_ROW, UNCLASSIFIABLE, or",
    "   INSUFFICIENT_EVIDENCE.",
    "6. ``primary_justification`` must rest on source-reconciliation evidence; GAV",
    "   improvement as the primary justification is rejected.",
    "",
    "## Bundle Assignments",
    "",
    "All paths are ABSOLUTE; your working directory is not the repo root.",
    "",
    "- ``$bundle`` -> write ``$verdict``",
    ""
  ) -join "`n"
  Set-Content -LiteralPath $promptPath -Value $assignment -Encoding UTF8
  $queue.Enqueue([pscustomobject]@{ ReviewId = $rid; PromptPath = $promptPath; VerdictPath = $verdict })
}
foreach ($s in $skipped) { Write-Host "SKIP $s" }
if ($queue.Count -eq 0) {
  Write-Host "Nothing to dispatch (all skipped)."
  exit 0
}
Write-Host "Dispatching $($queue.Count) worker(s) for batch $BatchId (skipped $($skipped.Count))."

$running = @()
$failures = @()
$validated = 0
$usageLimitCount = 0
$usageLimitHit = $false

try {
  while (($queue.Count -gt 0) -or ($running.Count -gt 0)) {
    while (($queue.Count -gt 0) -and ($running.Count -lt $MaxParallel) -and (-not $usageLimitHit)) {
      $item = $queue.Dequeue()
      $rid = $item.ReviewId
      $workerHome = Join-Path $homeDir $rid
      $workerRunroot = Join-Path $runrootDir $rid
      New-Item -ItemType Directory -Force -Path $workerHome, $workerRunroot | Out-Null

      & (Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1") `
        -WorkerHome $workerHome `
        -WorkerRunroot $workerRunroot `
        -WriteDirs @($VerdictsDir) `
        -ReadDirs @($BundlesDir, (Split-Path -Parent $TemplatePath)) `
        -EnvInherit "all" | Out-Null

      if ($hasFileAuth) {
        Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $workerHome "auth.json") -Force
      }

      $runScript = Join-Path $PSScriptRoot "run_codex_worker.ps1"
      $wrapperPath = Join-Path $wrapperDir "$rid.ps1"
      $content = @"
`$ErrorActionPreference = 'Stop'
& $(Quote-ForWrapper $runScript) ``
  -PromptPath $(Quote-ForWrapper $item.PromptPath) ``
  -WorkerHome $(Quote-ForWrapper $workerHome) ``
  -WorkerRunroot $(Quote-ForWrapper $workerRunroot) ``
  -CodexBin $(Quote-ForWrapper $CodexBin) ``
  -NoSetup
exit `$LASTEXITCODE
"@
      Set-Content -LiteralPath $wrapperPath -Value $content -Encoding ASCII

      $stdout = Join-Path $logDir "$rid.stdout.jsonl"
      $stderr = Join-Path $logDir "$rid.stderr.txt"
      $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$wrapperPath`"") `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
      $null = $proc.Handle

      $running += [pscustomobject]@{
        Item = $item; Process = $proc; Started = Get-Date; Stdout = $stdout; Stderr = $stderr
      }
      Write-Host "launched $rid pid=$($proc.Id)"
    }

    Start-Sleep -Seconds 2

    $nextRunning = @()
    foreach ($job in $running) {
      $proc = $job.Process
      $rid = $job.Item.ReviewId
      $elapsed = (Get-Date) - $job.Started
      if (-not $proc.HasExited -and $elapsed.TotalMinutes -ge $TimeoutMinutes) {
        Stop-TrackedProcessTree -ProcessId $proc.Id
        $failures += "$rid : TIMEOUT after $TimeoutMinutes minute(s)"
        continue
      }
      if (-not $proc.HasExited) { $nextRunning += $job; continue }
      $ec = $proc.ExitCode
      if ($null -ne $ec -and $ec -ne 0 -and (Test-UsageLimitHit -StdoutPath $job.Stdout)) {
        $usageLimitCount += 1
        $failures += "$rid : Codex usage limit hit (worker exit $ec); see $($job.Stdout)"
        if (($UsageLimitAbortThreshold -gt 0) -and ($usageLimitCount -ge $UsageLimitAbortThreshold)) { $usageLimitHit = $true }
        continue
      }
      $leaf = Test-VerdictLeaf -Rid $rid -LogPath (Join-Path $logDir "$rid.validate.txt")
      if ($leaf -eq "ok") {
        $validated += 1
        Write-Host "validated $rid"
      } elseif (($UsageLimitAbortThreshold -gt 0) -and (Test-UsageLimitHit -StdoutPath $job.Stdout)) {
        $usageLimitCount += 1
        $failures += "$rid : Codex usage limit hit (no verdict); see $($job.Stdout)"
        if ($usageLimitCount -ge $UsageLimitAbortThreshold) { $usageLimitHit = $true }
      } else {
        $failures += "$rid : verdict leaf check failed ($leaf); worker exit=$ec; stderr=$($job.Stderr)"
      }
    }
    $running = $nextRunning

    if ($usageLimitHit) {
      Write-Host "CIRCUIT BREAKER: Codex usage limit hit ($usageLimitCount). Aborting dispatch." -ForegroundColor Yellow
      $queue.Clear()
      foreach ($job in $running) {
        if (-not $job.Process.HasExited) { Stop-TrackedProcessTree -ProcessId $job.Process.Id }
      }
      $running = @()
    }
  }

  if ($failures.Count -gt 0) {
    $failurePath = Join-Path $BatchDir "dispatch_failures.txt"
    Set-Content -LiteralPath $failurePath -Value ($failures -join [Environment]::NewLine) -Encoding ASCII
    throw "bdc_cik_review dispatch completed with $($failures.Count) failure(s), $validated validated; see $failurePath"
  }

  Write-Host "bdc_cik_review dispatch complete: $validated validated, 0 failures."
} finally {
  foreach ($job in $running) {
    if (-not $job.Process.HasExited) { Stop-TrackedProcessTree -ProcessId $job.Process.Id }
  }
}
