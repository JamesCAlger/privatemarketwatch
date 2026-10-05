<#
.SYNOPSIS
  Run scripts/rebuild_outputs.py as its own process, with a memory trace.

.DESCRIPTION
  The unified rebuild peaks at an estimated 13-17 GB (financial preparation step,
  see docs/agent_changelog.md 2026-10-05). An agent session that starts it as a
  background task has it stopped when the machine runs low on memory. This
  launcher starts the build outside the session, so Windows pages through the
  peak instead. The machine can be sluggish for a few minutes at each peak.

  Everything is written to one run directory (default
  scratch\<date>_rebuild\<time>): start.txt, rebuild.log (the build's log),
  stdout.log, mem.csv (time, working set, private bytes, free memory), pid.txt
  and, when the build ends, exit.txt.

.EXAMPLE
  .\scripts\run_rebuild_detached.ps1                          # --unified
  .\scripts\run_rebuild_detached.ps1 -RebuildArgs "--returns"
  .\scripts\run_rebuild_detached.ps1 -Status                  # latest run
#>
param(
    [string]$RebuildArgs = "--unified",
    [string]$RunDir = "",
    [double]$MinFreeGB = 12,
    [int]$SampleSeconds = 15,
    [switch]$Force,
    [switch]$Status,
    [switch]$Worker,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Get-FreeGB {
    $os = Get-CimInstance Win32_OperatingSystem
    return [math]::Round($os.FreePhysicalMemory / 1MB, 2)
}

function Get-HeavyJobs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pytest.exe'" |
        Where-Object { $_.CommandLine -match 'rebuild_outputs|pytest|pipeline\.main|run_quarter_pass' }
}

# ---------------------------------------------------------------- worker
if ($Worker) {
    $env:PATH = Get-Content -Raw (Join-Path $RunDir "path.txt")
    $log = Join-Path $RunDir "rebuild.log"
    $out = Join-Path $RunDir "stdout.log"
    $mem = Join-Path $RunDir "mem.csv"
    "time,ws_gb,private_gb,free_gb" | Out-File -FilePath $mem -Encoding ascii
    $p = Start-Process -FilePath $PythonExe -ArgumentList "scripts/rebuild_outputs.py $RebuildArgs" `
        -WorkingDirectory $repo -RedirectStandardOutput $out -RedirectStandardError $log `
        -PassThru -WindowStyle Hidden
    $null = $p.Handle   # keep the handle so ExitCode is readable after exit
    "$($p.Id)" | Out-File -FilePath (Join-Path $RunDir "pid.txt") -Encoding ascii
    while (-not $p.HasExited) {
        try {
            $p.Refresh()
            $line = "{0},{1:N2},{2:N2},{3:N2}" -f (Get-Date -Format "HH:mm:ss"),
                ($p.WorkingSet64 / 1GB), ($p.PrivateMemorySize64 / 1GB), (Get-FreeGB)
            $line | Out-File -FilePath $mem -Append -Encoding ascii
        } catch { }
        Start-Sleep -Seconds $SampleSeconds
    }
    $p.WaitForExit()
    "exit=$($p.ExitCode) $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" |
        Out-File -FilePath (Join-Path $RunDir "exit.txt") -Encoding ascii
    exit 0
}

# ---------------------------------------------------------------- status
if ($Status) {
    if (-not $RunDir) {
        $latest = Get-ChildItem (Join-Path $repo "scratch") -Directory -Filter "*_rebuild" |
            ForEach-Object { Get-ChildItem $_.FullName -Directory } |
            Where-Object { Test-Path (Join-Path $_.FullName "start.txt") } |
            Sort-Object LastWriteTime | Select-Object -Last 1
        if (-not $latest) { Write-Output "no detached rebuild run found"; exit 1 }
        $RunDir = $latest.FullName
    }
    Write-Output "run dir : $RunDir"
    Get-Content (Join-Path $RunDir "start.txt")
    $exitFile = Join-Path $RunDir "exit.txt"
    if (Test-Path $exitFile) {
        Write-Output ("state   : finished, " + (Get-Content $exitFile))
    } else {
        $alive = $false
        $pidFile = Join-Path $RunDir "pid.txt"
        if (Test-Path $pidFile) {
            $alive = [bool](Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue)
        }
        if ($alive) { Write-Output "state   : running" }
        else { Write-Output "state   : NOT running and no exit.txt (stopped from outside, or still starting)" }
    }
    $mem = Join-Path $RunDir "mem.csv"
    if (Test-Path $mem) {
        $rows = Import-Csv $mem
        if ($rows) {
            $peak = ($rows | ForEach-Object { [double]$_.private_gb } | Measure-Object -Maximum).Maximum
            $low = ($rows | ForEach-Object { [double]$_.free_gb } | Measure-Object -Minimum).Minimum
            $last = $rows[-1]
            Write-Output ("memory  : last {0} ws {1} private {2} free {3} | peak private {4} | lowest free {5}" -f
                $last.time, $last.ws_gb, $last.private_gb, $last.free_gb, $peak, $low)
        }
    }
    $log = Join-Path $RunDir "rebuild.log"
    if (Test-Path $log) {
        $tail = Get-Content $log -Tail 1
        if ($tail) { Write-Output ("log     : " + $tail.Substring(0, [Math]::Min(150, $tail.Length))) }
    }
    exit 0
}

# ---------------------------------------------------------------- launcher
$jobs = @(Get-HeavyJobs)
if ($jobs.Count -gt 0 -and -not $Force) {
    Write-Output "REFUSED: a rebuild, pipeline or pytest process is already running:"
    $jobs | ForEach-Object { Write-Output ("  pid {0}: {1}" -f $_.ProcessId,
        $_.CommandLine.Substring(0, [Math]::Min(110, $_.CommandLine.Length))) }
    exit 2
}
$free = Get-FreeGB
if ($free -lt $MinFreeGB -and -not $Force) {
    Write-Output ("REFUSED: {0} GB free, below the {1} GB floor. Close applications or pass -Force." -f $free, $MinFreeGB)
    exit 3
}
if (-not $PythonExe) { $PythonExe = (Get-Command python).Source }
if (-not $RunDir) {
    $RunDir = Join-Path $repo ("scratch\{0}_rebuild\{1}" -f (Get-Date -Format "yyyy-MM-dd"), (Get-Date -Format "HHmmss"))
}
New-Item -ItemType Directory -Force $RunDir | Out-Null
$head = (& git -C $repo rev-parse --short HEAD)
@("started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", "args    : $RebuildArgs", "git head: $head",
  "free GB : $free", "python  : $PythonExe") | Out-File -FilePath (Join-Path $RunDir "start.txt") -Encoding ascii
$env:PATH | Out-File -FilePath (Join-Path $RunDir "path.txt") -Encoding ascii -NoNewline

# Win32_Process.Create starts the worker outside this shell's process tree.
$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Worker -RunDir "{1}" -RebuildArgs "{2}" -PythonExe "{3}" -SampleSeconds {4}' -f
    $PSCommandPath, $RunDir, $RebuildArgs, $PythonExe, $SampleSeconds
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $command; CurrentDirectory = $repo }
if ($result.ReturnValue -ne 0) {
    Write-Output "FAILED to start the worker (Win32_Process.Create returned $($result.ReturnValue))"
    exit 4
}
Write-Output "started : rebuild_outputs.py $RebuildArgs"
Write-Output "run dir : $RunDir"
Write-Output "status  : .\scripts\run_rebuild_detached.ps1 -Status"
exit 0
