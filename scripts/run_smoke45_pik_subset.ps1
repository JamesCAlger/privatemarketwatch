param(
  [string] $SourceBatch = "smoke45",
  [string] $RuleName = "pik_le_interest_rate",
  [string] $BatchId = "",
  [int] $MaxParallel = 2,
  [int] $TimeoutMinutes = 30,
  [string] $CodexBin = "codex.cmd",
  [switch] $PrepareOnly,
  [switch] $NoArchiveExistingVerdicts,
  [switch] $NoCompareBaseline
)

# Create and optionally run an Agent B batch that is a rule-level subset of an
# existing smoke batch. This preserves the exact sampled review_ids from the
# source batch; it does not resample the review queue.

$ErrorActionPreference = "Stop"

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock] $Command,
    [Parameter(Mandatory = $true)]
    [string] $Label
  )
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

if ([string]::IsNullOrWhiteSpace($BatchId)) {
  $BatchId = "smoke45_pik_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}

$sourceWorklist = Join-Path $Repo "data\output\agent_b\batch\$SourceBatch\worklist.csv"
if (-not (Test-Path -LiteralPath $sourceWorklist -PathType Leaf)) {
  throw "Missing source worklist: $sourceWorklist"
}

$rows = @(Import-Csv -LiteralPath $sourceWorklist | Where-Object { $_.rule_name -eq $RuleName })
if ($rows.Count -eq 0) {
  throw "No rows with rule_name=$RuleName in $sourceWorklist"
}

$batchDir = Join-Path $Repo "data\output\agent_b\batch\$BatchId"
$idsCsv = Join-Path $batchDir "selected_review_ids.csv"
$previewCsv = Join-Path $batchDir "selected_worklist_preview.csv"
$archiveDir = Join-Path $batchDir "prior_verdicts"
$verdictsDir = Join-Path $Repo "data\output\review_queue\verdicts"

New-Item -ItemType Directory -Force -Path $batchDir, $archiveDir | Out-Null

$reviewIds = @($rows | ForEach-Object { $_.review_id })
$rows | Select-Object review_id, engine, lane, cik, report_date, rule_name, class_hint, bundle_path |
  Export-Csv -LiteralPath $previewCsv -NoTypeInformation -Encoding UTF8
$rows | Select-Object review_id |
  Export-Csv -LiteralPath $idsCsv -NoTypeInformation -Encoding UTF8

Write-Host "Creating Agent B subset batch: $BatchId"
Write-Host "Source batch: $SourceBatch"
Write-Host "Rule: $RuleName"
Write-Host "Selected rows: $($reviewIds.Count)"

Invoke-Checked -Label "discover" -Command {
  & python -m scripts.agent_b.run_review discover $BatchId --review-ids-from $idsCsv
}

$newWorklist = Join-Path $batchDir "worklist.csv"
$newRows = @(Import-Csv -LiteralPath $newWorklist)
$badRows = @($newRows | Where-Object { $_.rule_name -ne $RuleName })
if ($newRows.Count -ne $reviewIds.Count) {
  throw "Subset worklist count mismatch: expected $($reviewIds.Count), got $($newRows.Count)"
}
if ($badRows.Count -gt 0) {
  throw "Subset worklist contains non-$RuleName rows"
}

if ($PrepareOnly) {
  Write-Host "PrepareOnly complete."
  Write-Host "Batch worklist: $newWorklist"
  Write-Host "Selected IDs: $idsCsv"
  Write-Host "No verdicts were archived and no workers were launched."
  exit 0
}

$archived = 0
if (-not $NoArchiveExistingVerdicts) {
  foreach ($id in $reviewIds) {
    $src = Join-Path $verdictsDir "$id.json"
    if (Test-Path -LiteralPath $src -PathType Leaf) {
      Move-Item -LiteralPath $src -Destination (Join-Path $archiveDir "$id.json") -Force
      $archived += 1
    }
  }
  Write-Host "Archived existing selected verdicts: $archived"
} else {
  Write-Host "Existing verdict archive disabled; dispatch preflight will fail if selected verdicts already exist."
}

$dispatchArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", (Join-Path $Repo "scripts\dispatch_agent_b_workers.ps1"),
  "-BatchId", $BatchId,
  "-MaxParallel", "$MaxParallel",
  "-TimeoutMinutes", "$TimeoutMinutes",
  "-CodexBin", $CodexBin
)

Invoke-Checked -Label "Agent B PIK subset dispatch" -Command {
  & powershell @dispatchArgs
}

$baselineCount = @(Get-ChildItem -LiteralPath $archiveDir -Filter *.json -ErrorAction SilentlyContinue).Count
if (-not $NoCompareBaseline -and $baselineCount -gt 0) {
  Invoke-Checked -Label "finalize baseline comparison" -Command {
    & python -m scripts.agent_b.run_review finalize $BatchId --compare-baseline $archiveDir
  }
}

$summaryPath = Join-Path $batchDir "finalize_summary.json"
if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
  Get-Content -LiteralPath $summaryPath -Raw
}
