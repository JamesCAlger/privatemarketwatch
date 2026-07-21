param(
  [Parameter(Mandatory = $true)]
  [string] $BatchId,

  [int] $TimeoutMinutes = 30,
  [switch] $SkipPrep
)

# Convention Adjudicator dispatcher. Serial by design (v1): the batch is small
# (<= ~21 workers) and the Codex elevated sandbox races its shared account
# password above 2-wide anyway; serial avoids cloning B1's parallel job control
# untested. Run from an operator shell OUTSIDE a Codex session (codex login done).
#
# Prerequisite: python -m scripts.agent_convention.run_convention discover <BatchId> ...
# After: strip_verdict_bom is NOT needed (leaves are read utf-8-sig), then per cik:
#   run_convention verify --cik <cik> --target-quarter <q>
#   run_convention promote --cik <cik> --target-quarter <q>

$ErrorActionPreference = "Stop"

$signals = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
  Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
if ($signals.Count -gt 0) {
  throw "Refusing to dispatch Codex workers from inside a Codex session: $($signals -join ', ')"
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$wl = Join-Path $root "data/output/agent_convention/batch/$BatchId/convention_worklist.csv"
if (-not (Test-Path -LiteralPath $wl -PathType Leaf)) {
  throw "worklist missing: $wl (run: python -m scripts.agent_convention.run_convention discover $BatchId ...)"
}

$rows = Import-Csv -LiteralPath $wl
$done = 0; $failed = @(); $skipped = @()
foreach ($row in $rows) {
  $cik = $row.cik; $q = $row.target_quarter
  if ($row.bundle_path -eq "NEEDS_BUNDLE") {
    Write-Host "[skip] $cik $q -- no review bundle (generate one first)"
    $skipped += $cik
    continue
  }

  if (-not $SkipPrep) {
    Write-Host "==== prep $cik $q ===="
    & python -m scripts.agent_convention.run_convention prep --cik $cik --target-quarter $q --bundle $row.bundle_path
    if ($LASTEXITCODE -ne 0) { Write-Host "[warn] prep failed for $cik"; $failed += $cik; continue }
  }

  $cikNorm = $cik.TrimStart('0')
  $prompt = Join-Path $root "data/output/agent_convention/$cikNorm/prompt.$q.md"
  $leaf = Join-Path $root "data/output/agent_convention/$cikNorm/leaf/convention.$q.json"
  if (-not (Test-Path -LiteralPath $prompt -PathType Leaf)) {
    Write-Host "[warn] prompt missing for $cik"; $failed += $cik; continue
  }

  # Fresh per-cik worker home under TEMP: avoids the stale setup-marker trap
  # (error 80) on re-runs and keeps the 308MB per-home Codex exe out of the repo;
  # run_codex_worker.ps1 cleans scratch post-run.
  $stamp = Get-Date -Format "yyyyMMddHHmmss"
  $whome = Join-Path $env:TEMP "conv-worker\$BatchId\$cikNorm-$stamp\home"
  $wrun  = Join-Path $env:TEMP "conv-worker\$BatchId\$cikNorm-$stamp\run"

  Write-Host "==== worker $cik $q ===="
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_codex_worker.ps1") `
    -PromptPath $prompt -WorkerHome $whome -WorkerRunroot $wrun
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] worker exit $LASTEXITCODE for $cik" }

  if (Test-Path -LiteralPath $leaf -PathType Leaf) {
    Write-Host "[ok] leaf written: $leaf"
    $done += 1
  } else {
    Write-Host "[fail] no leaf for $cik $q"
    $failed += $cik
  }
}

Write-Host "================ DONE ($BatchId): $done leaves, $($failed.Count) failed, $($skipped.Count) skipped ================"
if ($failed.Count -gt 0) { Write-Host "failed: $($failed -join ', ')" }
if ($skipped.Count -gt 0) { Write-Host "needs bundle: $($skipped -join ', ')" }
Write-Host "Next: run_convention verify/promote per cik, then python -m pipeline.rate_convention"
