# Shared allowlist of Codex worker_home waste + the post-run scrub function.
#
# Single source of truth consumed by BOTH:
#   - scripts/run_codex_worker.ps1  (in-line post-run scrub, every worker)
#   - scripts/sweep_worker_scratch_waste.ps1  (retroactive/backstop sweeper for
#     killed-dispatcher orphans and pre-fix batches)
# so the two can never drift apart.
#
# KEEP (never list here): config.toml, *.sqlite / -shm / -wal (Codex event
# logs), .sandbox\*.log, sessions\**\rollout-*.jsonl (agent traces -- harvested,
# not deleted), installation_id, cap_sid.

# Pure-waste FILES anywhere inside a worker home.
$CodexWorkerWasteFilePatterns = @(
  'codex.exe',
  'codex-command-runner*.exe',
  'auth.json',            # copied operator credentials -- must never persist in scratch
  'auth.json.bak*',
  'auth.json.stranded*',
  'models_cache.json'
)

# Pure-waste DIRECTORIES relative to a worker home root.
$CodexWorkerWasteDirNames = @(
  '.sandbox-bin',                          # binary copies only (~300 MB pre-0.142 cleanup era)
  '.tmp\plugins',                          # synced plugin cache
  'plugins\cache',                         # plugin cache, newer layout (~26 MB / ~5,000 files)
  'plugins\.remote-plugin-install-staging',
  'cache\codex_apps_tools',
  'cache\codex_apps_server_info',
  'skills'                                 # codex-synced skills cache, re-synced on demand
)

function Remove-CodexWorkerWaste {
  # Scrub one worker home. Best-effort: cleanup must never fail the worker run,
  # so every deletion swallows errors. Returns nothing.
  param([Parameter(Mandatory = $true)][string] $WorkerHome)

  if ([string]::IsNullOrWhiteSpace($WorkerHome) -or -not (Test-Path -LiteralPath $WorkerHome)) { return }

  foreach ($rel in $CodexWorkerWasteDirNames) {
    Remove-Item (Join-Path $WorkerHome $rel) -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
  }
  foreach ($pat in $CodexWorkerWasteFilePatterns) {
    Get-ChildItem -LiteralPath $WorkerHome -Recurse -Force -Filter $pat -File -ErrorAction SilentlyContinue |
      Remove-Item -Force -Confirm:$false -ErrorAction SilentlyContinue
  }
}
