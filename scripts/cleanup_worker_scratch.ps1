# Reclaim disk from finished Codex worker fleets.
#
# Codex copies its full ~300 MB binary into each worker home's .sandbox-bin and syncs a
# ~40 MB / ~5,000-file plugin cache into .tmp\plugins whenever it runs against a fresh
# CODEX_HOME. run_codex_worker.ps1 now removes both after each run, but dispatchers killed
# mid-batch (or batches predating that change) leave them behind -- 853 stale codex.exe
# copies totaled 257 GB by 2026-07-10. This sweep deletes ONLY those two scratch artifacts
# under worker_home trees; logs, wrappers, verdicts, prompts, and sqlite state are untouched.
#
# Usage:
#   .\scripts\cleanup_worker_scratch.ps1                  # sweep data\output
#   .\scripts\cleanup_worker_scratch.ps1 -Root <dir>      # sweep a specific batch dir
#   .\scripts\cleanup_worker_scratch.ps1 -WhatIfOnly      # report, delete nothing
param(
  [string] $Root = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'data\output'),
  [switch] $WhatIfOnly
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
  throw "Root does not exist: $Root"
}

$running = @(Get-Process -Name codex -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
  throw "Refusing to sweep while $($running.Count) codex process(es) are running (PIDs: $($running.Id -join ', '))."
}

$freed = [long]0

$exes = @(Get-ChildItem -LiteralPath $Root -Recurse -Filter codex.exe -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '\\worker_home\\[^\\]+\\\.sandbox-bin\\codex\.exe$' })
foreach ($exe in $exes) {
  $freed += $exe.Length
  if (-not $WhatIfOnly) { Remove-Item -LiteralPath $exe.FullName -Force -Confirm:$false }
}

$pluginDirs = @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter plugins -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '\\worker_home\\[^\\]+\\\.tmp\\plugins$' })
foreach ($dir in $pluginDirs) {
  $freed += (Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
    Measure-Object -Sum Length).Sum
  if (-not $WhatIfOnly) { Remove-Item -LiteralPath $dir.FullName -Recurse -Force -Confirm:$false }
}

$verb = if ($WhatIfOnly) { 'Would free' } else { 'Freed' }
"{0}: {1:N1} GB ({2} codex.exe, {3} plugin caches) under {4}" -f `
  $verb, ($freed / 1GB), $exes.Count, $pluginDirs.Count, $Root
