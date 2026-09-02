# Sync the raw EDGAR cache (and optionally baseline snapshots) to Cloudflare R2.
#
# Prereqs: rclone installed and an "r2" remote configured -- see
# docs/reference/cloud_backup_setup.md for one-time setup steps.
#
# Usage:
#   .\scripts\backup_raw_to_r2.ps1                 # sync data/raw only
#   .\scripts\backup_raw_to_r2.ps1 -IncludeSnapshots
#   .\scripts\backup_raw_to_r2.ps1 -DryRun        # show what would transfer
#
# Uses `rclone sync` (mirror: deletions locally propagate to the bucket).
# The raw cache is append-mostly, so this is safe; if you ever prune locally
# and want the bucket to keep history, switch to `rclone copy`.

param(
    [switch]$IncludeSnapshots,
    [switch]$DryRun,
    [string]$Remote = "r2",
    [string]$Bucket = "pmw-backup"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    Write-Error "rclone not found. Install: winget install Rclone.Rclone (then see docs/reference/cloud_backup_setup.md)"
}

$logDir = Join-Path $repoRoot "data\output"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$common = @(
    "--transfers", "8",
    "--checkers", "16",
    "--fast-list",
    "--stats", "60s",
    "--stats-one-line",
    "--log-level", "INFO",
    "--log-file", (Join-Path $logDir "r2_backup_$stamp.log")
)
if ($DryRun) { $common += "--dry-run" }

$jobs = @(
    @{ Src = (Join-Path $repoRoot "data\raw"); Dst = "${Remote}:${Bucket}/data/raw" }
)
if ($IncludeSnapshots) {
    $jobs += @{ Src = (Join-Path $repoRoot "data\snapshots\baseline"); Dst = "${Remote}:${Bucket}/data/snapshots/baseline" }
}

foreach ($job in $jobs) {
    Write-Host "Syncing $($job.Src) -> $($job.Dst)"
    & rclone sync $job.Src $job.Dst @common
    if ($LASTEXITCODE -ne 0) {
        Write-Error "rclone sync failed (exit $LASTEXITCODE) for $($job.Src). See log in data\output\r2_backup_$stamp.log"
    }
}

Write-Host "Backup complete. Log: data\output\r2_backup_$stamp.log"
