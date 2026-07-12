param(
  [int] $TimeoutMinutes = 45,
  [switch] $SkipDispatch   # gate-only, e.g. to re-read verdicts without re-dispatching workers
)

# Re-run the three look-through / anchor CIKs through the investigation loop AFTER the filing-parser
# change (bundle/filing now wired into B2 + 0.5% rounding tolerance). -Fresh clears each target's
# prior rules/escalations/derived artifacts so they re-author against the filing-aware loop instead
# of gating stale corrected holdings. Then each is B3-gated (the un-gameable verdict).
#
# Run from an operator shell OUTSIDE a Codex session (conda-activated). The canary asserts this.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$ciks = "1975736,1803498,1930087"   # KKR FS / 1803498 / 1930087 -- the filing look-through cases

$canary = Join-Path $PSScriptRoot "run_investigation_canary.ps1"
$args = @(
  "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $canary,
  "-B1BatchId", "restall",
  "-OnlyCik", $ciks,
  "-Fresh",
  "-TimeoutMinutes", $TimeoutMinutes
)
if ($SkipDispatch) { $args += "-SkipDispatch" }

Write-Host "[rerun-three] dispatching restall/{$ciks} through the filing-aware investigation loop"
& powershell.exe @args
$code = $LASTEXITCODE

# Surface the B3 verdicts for the three (gate summary written by the canary).
$summary = Join-Path $root "data/output/agent_investigate/batch/investigate_restall/b3_gate_summary.csv"
if (Test-Path -LiteralPath $summary) {
  Write-Host "`n[rerun-three] B3 gate verdicts:"
  Import-Csv -LiteralPath $summary |
    Where-Object { '1975736','1803498','1930087' -contains ([string]$_.cik).TrimStart('0') } |
    Format-Table cik, quarter, verdict, anchor_tier, noop_rules, n_escalations -AutoSize
}
exit $code
