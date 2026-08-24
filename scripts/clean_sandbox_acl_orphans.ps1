param(
  # Directories whose DACLs accumulate per-worker sandbox ACEs (fleet write roots).
  [Parameter(Mandatory = $true)]
  [string[]] $Path,

  # Fail (exit 2) if a directory still exceeds this many ACEs AFTER the sweep --
  # the 64KB DACL ceiling lands around ~1,820 entries (measured 2026-07-24).
  [int] $FailThreshold = 1500,

  # Report only; remove nothing.
  [switch] $WhatIfOnly
)

# Codex sandbox ACE-leak prevention (2026-07-24 q4t0 incident). Every Codex
# worker run grants a write ACE for a per-run sandbox user SID on each write
# root and never removes it; at the DACL ceiling every subsequent worker fails
# setup with "SetEntriesInAclW failed: 87" (stderr shows a decoy marker error
# 80). This script removes ACEs whose S-1-5-21-* identity no longer resolves
# to an account (the per-run sandbox users are deleted after each run, so
# their ACEs are provably dead). Inherited ACEs and resolvable accounts are
# never touched. Run it in dispatcher preflight; ASCII-only output.

$ErrorActionPreference = "Stop"
$exitCode = 0

foreach ($dir in $Path) {
  if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
    Write-Host "SKIP (missing): $dir"
    continue
  }
  $acl = Get-Acl -LiteralPath $dir
  $before = $acl.Access.Count
  $dead = @()
  foreach ($ace in @($acl.Access)) {
    if ($ace.IsInherited) { continue }
    $id = $ace.IdentityReference.Value
    if ($id -notmatch '^S-1-5-21-') { continue }
    $resolves = $true
    try {
      $null = (New-Object System.Security.Principal.SecurityIdentifier($id)).Translate([System.Security.Principal.NTAccount])
    } catch {
      $resolves = $false
    }
    if (-not $resolves) { $dead += $ace }
  }

  if ($dead.Count -gt 0 -and -not $WhatIfOnly) {
    foreach ($ace in $dead) { $null = $acl.RemoveAccessRule($ace) }
    Set-Acl -LiteralPath $dir -AclObject $acl
    $after = (Get-Acl -LiteralPath $dir).Access.Count
  } else {
    $after = $before - $(if ($WhatIfOnly) { 0 } else { $dead.Count })
  }

  Write-Host ("{0}: {1} ACEs -> {2} (removed {3} orphaned sandbox SIDs{4})" -f `
    $dir, $before, $after, $dead.Count, $(if ($WhatIfOnly) { ", WHATIF" } else { "" }))

  if ($after -gt $FailThreshold) {
    Write-Host ("FAIL: {0} still has {1} ACEs (> {2}). Live accounts or inherited entries " -f $dir, $after, $FailThreshold) -ForegroundColor Red
    Write-Host "dominate the DACL; investigate before dispatching (see agent_changelog 2026-07-24 DACL entry)." -ForegroundColor Red
    $exitCode = 2
  }
}

exit $exitCode
