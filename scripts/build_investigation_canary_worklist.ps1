param(
  [string] $SourcePath = "data/output/shadow/conservation_gate_results.csv",
  [string] $OutputPath = "data/output/agent_investigate/canary_worklist.csv",
  [int] $Limit = 5,
  [string] $Status = "overshoot",
  [double] $MinAbsResidualPct = 1.0,
  [double] $MinAnchorValue = 1.0,
  [switch] $AllowRepeatedCik
)

# Build a small target worklist from the deterministic FV-conservation gate. Use this CSV
# with scripts/dispatch_b1_to_b2_workers.ps1 by default so each target receives B1 review
# before any B2 remediation worker runs. The older dispatch_investigation_canary.ps1 path is
# diagnostics-only and requires -AllowUnreviewedRawResidual.
#
# The agent needs an independent positive anchor, so this excludes no-anchor and
# non-positive-anchor rows. By default it takes one highest-absolute-residual quarter per CIK.
#
# Output CSV columns:
#   cik,target_quarter,residual_pct,status,value_sum,anchor_value

$ErrorActionPreference = "Stop"

if ($Limit -lt 1) { throw "Limit must be >= 1." }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$source = (Resolve-Path -LiteralPath $SourcePath).Path
$rows = Import-Csv -LiteralPath $source

$candidates = @(
  $rows |
    Where-Object {
      $_.rule_name -eq "fv_conservation" -and
      -not [string]::IsNullOrWhiteSpace($_.anchor_value) -and
      -not [string]::IsNullOrWhiteSpace($_.residual_pct) -and
      ([string]::IsNullOrWhiteSpace($Status) -or $_.status -eq $Status)
    } |
    ForEach-Object {
      $resid = [double]$_.residual_pct
      $anchor = [double]$_.anchor_value
      if ([math]::Abs($resid) -ge $MinAbsResidualPct -and $anchor -ge $MinAnchorValue) {
        [pscustomobject]@{
          cik = [string]$_.cik
          target_quarter = [string]$_.report_date
          residual_pct = $resid
          abs_residual_pct = [math]::Abs($resid)
          status = [string]$_.status
          value_sum = [string]$_.value_sum
          anchor_value = [string]$_.anchor_value
        }
      }
    } |
    Sort-Object abs_residual_pct -Descending
)

if ($candidates.Count -eq 0) {
  throw "No anchored fv_conservation candidates found in $source for status=$Status."
}

if ($AllowRepeatedCik) {
  $selected = @($candidates | Select-Object -First $Limit)
} else {
  $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  $selectedList = New-Object System.Collections.Generic.List[object]
  foreach ($row in $candidates) {
    if ($seen.Add($row.cik)) {
      $selectedList.Add($row)
      if ($selectedList.Count -ge $Limit) { break }
    }
  }
  $selected = @($selectedList.ToArray())
}

if ($selected.Count -eq 0) {
  throw "No rows selected."
}

$outFull = [System.IO.Path]::GetFullPath($OutputPath)
$outDir = Split-Path -Parent $outFull
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$selected |
  Select-Object cik,target_quarter,residual_pct,status,value_sum,anchor_value |
  Export-Csv -LiteralPath $outFull -NoTypeInformation -Encoding ASCII

Write-Host "[worklist] wrote $($selected.Count) rows -> $outFull"
$selected | Format-Table cik,target_quarter,residual_pct,status,value_sum,anchor_value -AutoSize
