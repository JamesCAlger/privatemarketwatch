param(
  [Parameter(Mandatory = $true)]
  [string] $B1BatchId,

  [string] $B2BatchId = "",
  [int] $TimeoutMinutes = 45,
  [int] $MaxTargets = 0,            # 0 = all discovered targets
  [string[]] $OnlyCik = @(),        # restrict to these CIKs (optional)
  [switch] $Fresh,                  # clear each target's prior rules/escalations before dispatch
  [switch] $SkipDispatch
)

# Agentic B2 canary: the COUNTERPART to run_b2_fixclass_canary.ps1, but it routes authoring through
# the INVESTIGATION LOOP (run_investigation) instead of the deterministic template-author. For each
# B1 real_error target it dispatches a Codex worker that QUERIES the extracted data, finds the real
# mechanism, authors auditable rule(s) (row_exclusion / dedup / value_rescale / value_expression /
# row_add) or ESCALATES, iterates to <=1% + gate PASS, then this script B3-gates each target.
# Run from an operator shell OUTSIDE a Codex session (conda-activated).

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $sig = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($sig.Count -gt 0) { throw "Refusing to dispatch Codex workers from inside a Codex session: $($sig -join ', ')" }
}
Assert-OutsideCodexSession

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($B2BatchId)) { $B2BatchId = "investigate_$B1BatchId" }

$b1Worklist = Join-Path $root "data/output/agent_b/batch/$B1BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $b1Worklist -PathType Leaf)) {
  throw "B1 worklist missing: $b1Worklist"
}

Write-Host "[investigate-canary] b1_batch=$B1BatchId"
Write-Host "[investigate-canary] b2_batch=$B2BatchId"

# 1) Discover investigation targets from the B1 batch (every real_error -> (cik, target_quarter)).
$discoverOut = & python -m scripts.agent_investigate.run_investigation discover $B2BatchId --source-worklist $b1Worklist
if ($LASTEXITCODE -ne 0) { throw "discover failed: $($discoverOut -join [Environment]::NewLine)" }
$discoverText = ($discoverOut | Out-String).Trim()
Write-Host $discoverText
$discover = $discoverText | ConvertFrom-Json
$worklistPath = [string]$discover.worklist
if (-not (Test-Path -LiteralPath $worklistPath -PathType Leaf)) {
  Write-Host "[investigate-canary] no investigation worklist produced"; exit 0
}

$targets = @(Import-Csv -LiteralPath $worklistPath)
if ($OnlyCik.Count -gt 0) {
  # `powershell -File -OnlyCik a,b` arrives as a SINGLE "a,b" string (not a 2-element array, unlike
  # an in-process call), so split each element on commas, then strip leading zeros for comparison.
  $want = @($OnlyCik | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().TrimStart('0') } |
            Where-Object { $_ })
  $targets = @($targets | Where-Object { $want -contains ([string]$_.cik).TrimStart('0') })
}
if ($MaxTargets -gt 0 -and $targets.Count -gt $MaxTargets) {
  $targets = @($targets[0..($MaxTargets - 1)])
}
if ($targets.Count -eq 0) { Write-Host "[investigate-canary] no targets selected"; exit 0 }
Write-Host "[investigate-canary] $($targets.Count) target(s)"

$dispatch = Join-Path $PSScriptRoot "dispatch_investigation.ps1"
$batchDir = Join-Path $root "data/output/agent_investigate/batch/$B2BatchId"
New-Item -ItemType Directory -Force $batchDir | Out-Null
$summary = @()

foreach ($t in $targets) {
  $cik = [string]$t.cik
  $q = [string]$t.target_quarter
  Write-Host "==== investigate cik=$cik quarter=$q ===="

  if ($Fresh) {
    $cikDir = Join-Path $root "data/output/agent_investigate/$($cik.TrimStart('0'))"
    foreach ($sub in @("rules", "escalations")) {
      $d = Join-Path $cikDir $sub
      if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Filter *.json | Remove-Item -Force }
    }
    # Also drop derived artifacts so a fresh run never gates stale corrected holdings.
    Get-ChildItem -LiteralPath $cikDir -Filter "corrected_holdings.*.csv" -ErrorAction SilentlyContinue | Remove-Item -Force
    Remove-Item -LiteralPath (Join-Path $cikDir "apply_audit.json") -Force -ErrorAction SilentlyContinue
    Write-Host "[fresh] cleared prior rules/escalations/derived artifacts for $cik"
  }

  if (-not $SkipDispatch) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dispatch `
      -Cik $cik -TargetQuarter $q -B1Reviewed -TimeoutMinutes $TimeoutMinutes
    if ($LASTEXITCODE -ne 0) { Write-Host "[warn] dispatch returned $LASTEXITCODE for $cik" }
  }

  # B3 gate the authored rules (the un-gameable verdict).
  $gateOut = & python -m scripts.agent_investigate.run_investigation gate --cik $cik --target-quarter $q
  $gateText = ($gateOut | Out-String).Trim()
  Set-Content -LiteralPath (Join-Path $batchDir "b3_gate.$cik.$q.json") -Value $gateText -Encoding UTF8
  $verdict = "UNKNOWN"; $tier = ""; $noop = ""; $nEsc = ""
  try {
    $gj = $gateText | ConvertFrom-Json
    $verdict = [string]$gj.verdict; $tier = [string]$gj.anchor_tier
  } catch { $verdict = "PARSE_ERROR" }

  # Apply-audit (no-op rules / escalations) for the summary.
  $applyAudit = Join-Path $root "data/output/agent_investigate/$($cik.TrimStart('0'))/apply_audit.json"
  if (Test-Path -LiteralPath $applyAudit) {
    try {
      $aj = Get-Content -Raw -LiteralPath $applyAudit | ConvertFrom-Json
      $noop = ($aj.noop_rules -join ";"); $nEsc = [string]$aj.n_escalations
    } catch {}
  }

  Write-Host "[gate] cik=$cik quarter=$q verdict=$verdict anchor_tier=$tier noop=[$noop] escalations=$nEsc"
  $summary += [pscustomobject]@{ cik = $cik; quarter = $q; verdict = $verdict;
    anchor_tier = $tier; noop_rules = $noop; n_escalations = $nEsc }
}

$summaryPath = Join-Path $batchDir "b3_gate_summary.csv"
$summary | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding UTF8
Write-Host "[investigate-canary] complete"
Write-Host "[investigate-canary] worklist: $worklistPath"
Write-Host "[investigate-canary] gate summary: $summaryPath"
