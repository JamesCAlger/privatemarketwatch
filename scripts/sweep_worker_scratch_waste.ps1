# Sweep known-waste files out of Codex worker_home scratch trees, deterministically.
#
# Deletes ONLY files/dirs matching an explicit allowlist of Codex-runtime waste
# (binaries, plugin caches, model caches, copied credentials), and ONLY inside
# paths that contain a \worker_home\ segment. It never touches batch audit
# artifacts (manifests, prompts, wrappers, logs, gate logs) and never deletes a
# whole worker home. Thinking-bearing files (sqlite logs, sandbox logs,
# config.toml, any sessions\rollout-*.jsonl traces) are explicitly kept.
#
# Default is DRY RUN: writes a manifest CSV of what WOULD be deleted and a
# summary, deletes nothing. Pass -Apply to delete (the same manifest is written
# first, as the audit record of the sweep).
#
# Usage:
#   powershell -File scripts\sweep_worker_scratch_waste.ps1                # dry run, default roots
#   powershell -File scripts\sweep_worker_scratch_waste.ps1 -Roots data\output\agent_b2
#   powershell -File scripts\sweep_worker_scratch_waste.ps1 -Apply        # actually delete
#
# Safety rails:
#   - allowlist patterns only; anything unmatched is untouched
#   - structural guard: path must contain \worker_home\
#   - worker homes modified in the last -MinAgeHours (default 48) are skipped
#     (a batch may be mid-run)
#   - manifest CSV written before any deletion

param(
  [string[]] $Roots = @(
    'data\output\agent_a',
    'data\output\agent_anchor',
    'data\output\agent_b',
    'data\output\agent_b2',
    'data\output\agent_convention',
    'data\output\agent_investigate'
  ),
  [switch] $Apply,
  [int] $MinAgeHours = 48,
  [string] $ManifestOut = ''
)

$ErrorActionPreference = 'Stop'

# Allowlist is shared with run_codex_worker.ps1's post-run scrub -- single
# source of truth in codex_worker_waste_allowlist.ps1 (also documents KEEPs).
. (Join-Path $PSScriptRoot 'codex_worker_waste_allowlist.ps1')
$WasteFilePatterns = $CodexWorkerWasteFilePatterns
$WasteDirNames = $CodexWorkerWasteDirNames

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if ([string]::IsNullOrWhiteSpace($ManifestOut)) {
  $ManifestOut = "data\output\scratch_sweep_manifest_$stamp.csv"
}
$cutoff = (Get-Date).AddHours(-$MinAgeHours)
$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN' }
Write-Output "[sweep] mode=$mode min_age_hours=$MinAgeHours manifest=$ManifestOut"

$rows = New-Object System.Collections.Generic.List[object]

foreach ($root in $Roots) {
  if (-not (Test-Path $root)) { Write-Output "[sweep] skip (missing): $root"; continue }
  Write-Output "[sweep] scanning $root"

  $homes = Get-ChildItem $root -Recurse -Force -Directory -Filter 'worker_home' -ErrorAction SilentlyContinue
  foreach ($wh in $homes) {
    # Flat-layout coverage: some ad-hoc runs use worker_home ITSELF as the
    # CODEX_HOME (no per-worker subdir). Scan the root for waste files
    # (non-recursive; children are handled below) and root-relative waste dirs,
    # under the same age guard as everything else.
    $recentRoot = Get-ChildItem $wh.FullName -Recurse -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTime -gt $cutoff } | Select-Object -First 1
    if ($null -ne $recentRoot) {
      Write-Output "[sweep] SKIP active (<${MinAgeHours}h): $($wh.FullName) (root scan)"
    } else {
      foreach ($pat in $WasteFilePatterns) {
        foreach ($f in (Get-ChildItem $wh.FullName -Force -Filter $pat -File -ErrorAction SilentlyContinue)) {
          $rows.Add([pscustomobject]@{
            kind = 'file'; pattern = $pat; path = $f.FullName; bytes = $f.Length })
        }
      }
      foreach ($rel in $WasteDirNames) {
        $d = Join-Path $wh.FullName $rel
        if (Test-Path $d) {
          $sz = (Get-ChildItem $d -Recurse -Force -File -ErrorAction SilentlyContinue |
                 Measure-Object Length -Sum).Sum
          if ($null -eq $sz) { $sz = 0 }
          $rows.Add([pscustomobject]@{
            kind = 'dir'; pattern = $rel; path = $d; bytes = $sz })
        }
      }
    }
    foreach ($workerDir in (Get-ChildItem $wh.FullName -Directory -Force -ErrorAction SilentlyContinue)) {
      $recent = Get-ChildItem $workerDir.FullName -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt $cutoff } | Select-Object -First 1
      if ($null -ne $recent) {
        Write-Output "[sweep] SKIP active (<${MinAgeHours}h): $($workerDir.FullName)"
        continue
      }

      foreach ($pat in $WasteFilePatterns) {
        foreach ($f in (Get-ChildItem $workerDir.FullName -Recurse -Force -Filter $pat -File -ErrorAction SilentlyContinue)) {
          if ($f.FullName -notmatch '\\worker_home\\') { continue }
          # already covered (and counted) by a waste-dir entry; avoid double count
          if ($f.FullName -match '\\\.sandbox-bin\\|\\\.tmp\\plugins\\|\\plugins\\cache\\|\\cache\\codex_apps') { continue }
          $rows.Add([pscustomobject]@{
            kind = 'file'; pattern = $pat; path = $f.FullName; bytes = $f.Length })
        }
      }
      foreach ($rel in $WasteDirNames) {
        $d = Join-Path $workerDir.FullName $rel
        if (Test-Path $d) {
          if ((Resolve-Path $d).Path -notmatch '\\worker_home\\') { continue }
          $sz = (Get-ChildItem $d -Recurse -Force -File -ErrorAction SilentlyContinue |
                 Measure-Object Length -Sum).Sum
          if ($null -eq $sz) { $sz = 0 }
          $rows.Add([pscustomobject]@{
            kind = 'dir'; pattern = $rel; path = $d; bytes = $sz })
        }
      }
    }
  }
}

$rows | Export-Csv -Path $ManifestOut -NoTypeInformation -Encoding UTF8
$totalMB = [math]::Round((($rows | Measure-Object bytes -Sum).Sum) / 1MB, 1)
Write-Output "[sweep] matched $($rows.Count) items, $totalMB MB reclaimable; manifest -> $ManifestOut"

$byPat = $rows | Group-Object pattern | Sort-Object { ($_.Group | Measure-Object bytes -Sum).Sum } -Descending
foreach ($g in $byPat) {
  $mb = [math]::Round((($g.Group | Measure-Object bytes -Sum).Sum) / 1MB, 1)
  Write-Output ("[sweep]   {0,-42} {1,6} items {2,12:N1} MB" -f $g.Name, $g.Count, $mb)
}

if (-not $Apply) {
  Write-Output '[sweep] DRY RUN complete. Nothing deleted. Re-run with -Apply to delete.'
  exit 0
}

$deleted = 0
$failed = 0
foreach ($r in $rows) {
  try {
    if ($r.kind -eq 'dir') {
      Remove-Item -LiteralPath $r.path -Recurse -Force -Confirm:$false -ErrorAction Stop
    } else {
      Remove-Item -LiteralPath $r.path -Force -Confirm:$false -ErrorAction Stop
    }
    $deleted++
  } catch {
    $failed++
    Write-Output "[sweep] FAILED to delete: $($r.path) ($($_.Exception.Message))"
  }
}
Write-Output "[sweep] APPLY complete: $deleted deleted, $failed failed, manifest kept at $ManifestOut"
