param(
  [Parameter(Mandatory = $true)]
  [string] $B1BatchId,                 # an EXISTING B1 batch (run B1 first; see runbook)

  [string[]] $OnlyCik = @(),
  [int] $TimeoutMinutes = 45,
  [switch] $SkipB2First,               # skip the first B2 pass (e.g. resume from anchor stage)
  [switch] $SkipAnchor,
  [switch] $SkipB2Second
)

# Full remediation chain over a B1 batch:  B2 (fix vs companyfacts) -> Anchor Adjudicator (find the
# GRAND total, verify, promote override) -> B2 (re-fix vs the corrected anchor). B1 is the prereq
# (its worklist + verdicts must already exist). Each stage delegates to the existing canaries, so the
# investigation loop + sandbox harness are reused unchanged. Run OUTSIDE a Codex session.

$ErrorActionPreference = "Stop"

function Assert-OutsideCodexSession {
  $sig = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($sig.Count -gt 0) { throw "Refusing to dispatch Codex workers from inside a Codex session: $($sig -join ', ')" }
}
Assert-OutsideCodexSession

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$b1Worklist = Join-Path $root "data/output/agent_b/batch/$B1BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $b1Worklist -PathType Leaf)) { throw "B1 worklist missing: $b1Worklist (run B1 first)" }

$wantCiks = @($OnlyCik | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().TrimStart('0') } | Where-Object { $_ })
$cikArg = $wantCiks -join ','
$invCanary = Join-Path $PSScriptRoot "run_investigation_canary.ps1"
$anchorDispatch = Join-Path $PSScriptRoot "dispatch_anchor_workers.ps1"
$overridesRoot = Join-Path $root "data/overrides/agent_anchor"

function Invoke-B2 {
  param([string] $Label)
  Write-Host "================ $Label (B2 investigation loop) ================"
  $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $invCanary,
         "-B1BatchId", $B1BatchId, "-Fresh", "-TimeoutMinutes", [string]$TimeoutMinutes)
  if ($cikArg) { $a += @("-OnlyCik", $cikArg) }
  & powershell.exe @a
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] $Label returned $LASTEXITCODE" }
}

# --- Stage 1: B2 pass 1 (fix vs the companyfacts anchor; surfaces anchor escalations) ---
if (-not $SkipB2First) { Invoke-B2 -Label "STAGE 1" } else { Write-Host "[skip] stage 1 (B2 first pass)" }

# --- Stage 2: Anchor Adjudicator (discover triggered targets -> find grand total -> promote) ---
$promoted = @()                       # (cik, quarter) pairs that got a verified override THIS run
if (-not $SkipAnchor) {
  Write-Host "================ STAGE 2 (Anchor Adjudicator) ================"
  $anchorBatch = "anchor_$B1BatchId"
  $disc = & python -m scripts.agent_anchor.run_anchor discover $anchorBatch --source-worklist $b1Worklist
  if ($LASTEXITCODE -ne 0) { throw "anchor discover failed: $($disc -join [Environment]::NewLine)" }
  Write-Host ($disc | Out-String).Trim()
  $awl = Join-Path $root "data/output/agent_anchor/batch/$anchorBatch/anchor_worklist.csv"
  $rows = @(Import-Csv -LiteralPath $awl)
  if ($wantCiks.Count -gt 0) {
    $rows = @($rows | Where-Object { $wantCiks -contains ([string]$_.cik).TrimStart('0') })
  }
  Write-Host "[anchor] $($rows.Count) target(s) to adjudicate"
  foreach ($r in $rows) {
    $cik = ([string]$r.cik).TrimStart('0'); $q = [string]$r.target_quarter
    Write-Host "---- anchor adjudicate cik=$cik quarter=$q (triggers: $($r.triggers)) ----"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $anchorDispatch `
      -Cik $cik -TargetQuarter $q -TimeoutMinutes $TimeoutMinutes
    if ($LASTEXITCODE -ne 0) { Write-Host "[warn] anchor dispatch returned $LASTEXITCODE for $cik" }
    if (Test-Path -LiteralPath (Join-Path $root "data/overrides/agent_anchor/$cik/$q.json")) {
      $promoted += [pscustomobject]@{ cik = $cik; quarter = $q }
    }
  }
  Write-Host "[anchor] promoted overrides: $(($promoted | ForEach-Object { "$($_.cik)/$($_.quarter)" }) -join ', ')"
} else { Write-Host "[skip] stage 2 (anchor)" }

# --- Stage 3: B2 re-fix EVERY override target in scope (real_error or not) ---
# A promoted override is itself proof of a real discrepancy, so we do NOT gate on B1's real_error
# verdict (1743415 has a correct override but is not a real_error; the canary's real_error filter
# would drop it). We enumerate override FILES (not just this run's promotions) so a pre-existing
# override-without-fix is still picked up, and we gate-first (cheap, no worker) to SKIP any target
# whose existing rules already reconcile to the corrected anchor.
$stage3Dispatch = Join-Path $PSScriptRoot "dispatch_investigation.ps1"
$stage3Rows = @()
if (-not $SkipB2Second) {
  $targets = @()
  if (Test-Path -LiteralPath $overridesRoot) {
    foreach ($cdir in (Get-ChildItem -LiteralPath $overridesRoot -Directory)) {
      $cik = $cdir.Name
      if ($wantCiks.Count -gt 0 -and -not ($wantCiks -contains $cik)) { continue }
      foreach ($jf in (Get-ChildItem -LiteralPath $cdir.FullName -Filter *.json)) {
        $targets += [pscustomobject]@{ cik = $cik; quarter = [System.IO.Path]::GetFileNameWithoutExtension($jf.Name) }
      }
    }
  }
  if ($targets.Count -eq 0) {
    Write-Host "[stage 3] no anchor overrides in scope; nothing to re-fix"
  } else {
    Write-Host "================ STAGE 3 (B2 re-fix vs corrected anchor) ================"
    foreach ($p in $targets) {
      $cik = $p.cik; $q = $p.quarter
      # gate-first (deterministic, no worker): skip if existing rules already reconcile.
      $gj = & python -m scripts.agent_investigate.run_investigation gate --cik $cik --target-quarter $q
      $pre = "UNKNOWN"; try { $pre = (($gj | Out-String).Trim() | ConvertFrom-Json).verdict } catch {}
      if ($pre -eq "PASS") {
        Write-Host "[stage 3] cik=$cik quarter=$q already PASS vs corrected anchor; skip"
        $stage3Rows += [pscustomobject]@{ cik = $cik; quarter = $q; verdict = "PASS"; refixed = $false }
        continue
      }
      Write-Host "---- re-fix cik=$cik quarter=$q (pre-gate=$pre) ----"
      $cikDir = Join-Path $root "data/output/agent_investigate/$cik"
      foreach ($sub in @("rules", "escalations")) {
        $d = Join-Path $cikDir $sub
        if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Filter *.json | Remove-Item -Force }
      }
      Get-ChildItem -LiteralPath $cikDir -Filter "corrected_holdings.*.csv" -ErrorAction SilentlyContinue | Remove-Item -Force
      Remove-Item -LiteralPath (Join-Path $cikDir "apply_audit.json") -Force -ErrorAction SilentlyContinue
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stage3Dispatch `
        -Cik $cik -TargetQuarter $q -B1Reviewed -TimeoutMinutes $TimeoutMinutes
      if ($LASTEXITCODE -ne 0) { Write-Host "[warn] re-fix dispatch returned $LASTEXITCODE for $cik" }
      $gj2 = & python -m scripts.agent_investigate.run_investigation gate --cik $cik --target-quarter $q
      $verdict = "UNKNOWN"; try { $verdict = (($gj2 | Out-String).Trim() | ConvertFrom-Json).verdict } catch { $verdict = "PARSE_ERROR" }
      Write-Host "[gate] cik=$cik quarter=$q verdict=$verdict"
      $stage3Rows += [pscustomobject]@{ cik = $cik; quarter = $q; verdict = $verdict; refixed = $true }
    }
    $sumDir = Join-Path $root "data/output/agent_investigate/batch/investigate_$B1BatchId"
    New-Item -ItemType Directory -Force $sumDir | Out-Null
    $sumPath = Join-Path $sumDir "b3_gate_summary_stage3.csv"
    $stage3Rows | Export-Csv -LiteralPath $sumPath -NoTypeInformation -Encoding UTF8
    Write-Host "[stage 3] gate summary: $sumPath"
  }
} else { Write-Host "[skip] stage 3 (B2 second pass)" }

Write-Host "================ DONE ================"
foreach ($r in $stage3Rows) { Write-Host ("  [{0}] {1} {2}" -f $r.verdict, $r.cik, $r.quarter) }
Write-Host "Stage-3 gate summary: data/output/agent_investigate/batch/investigate_$B1BatchId/b3_gate_summary_stage3.csv"
Write-Host "Anchor overrides:     data/overrides/agent_anchor/<cik>/<quarter>.json"
