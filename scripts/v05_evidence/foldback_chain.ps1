# Fold the fund sandboxes' committed fixes into production: re-extract the cohort and rebuild the chain.
# Generalised from scratch\2026-11-10_q2\chain.ps1 (owner run 2026-11-10, git 5dbcec98).
#
#   powershell -File scripts\v05_evidence\foldback_chain.ps1 -Tag n1111 -Quarters 2026-06-30,2026-03-31
#
# Launch DETACHED (Start-Process powershell ... -WindowStyle Hidden); Claude Code background shells are
# stopped under memory pressure. About 6 hours; needs ~14 GB free for the unified step. Ask the owner first;
# never close their applications. No fund build, pytest or code edit in this checkout while it runs.
# Stops at the first failing step. Log: scratch\<date>_foldback_<Tag>\chain.log, per-step logs alongside.
# The first quarter's pass runs from nonaccrual; later quarters reuse those stages and run from queue.
# Re-attestation failing is expected while the signed-off quarters regress (AGENTS.md); it is logged, not fatal.
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string[]]$Quarters
)
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$dir = Join-Path $repo ("scratch\{0}_foldback_{1}" -f (Get-Date -Format 'yyyy-MM-dd'), $Tag)
New-Item -ItemType Directory -Force $dir | Out-Null
$log = Join-Path $dir "chain.log"
Set-Location $repo
function Say($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $log -Append -Encoding ascii }
function FreeGB { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1) }
function Step($name, $argList, $minFree, [switch]$NonFatal) {
    $f = FreeGB
    if ($f -lt $minFree) { Say "STOP ${name}: free $f GB < $minFree GB"; exit 2 }
    Say "START $name (free $f GB): python $argList"
    $p = Start-Process -FilePath python -ArgumentList $argList -WorkingDirectory $repo `
        -RedirectStandardOutput (Join-Path $dir "$name.out.log") -RedirectStandardError (Join-Path $dir "$name.err.log") `
        -PassThru -WindowStyle Hidden -Wait
    if ($p.ExitCode -ne 0) {
        if ($NonFatal) { Say "NONFATAL $name exit $($p.ExitCode)"; return }
        Say "FAIL $name exit $($p.ExitCode)"; exit 1
    }
    Say "DONE $name"
}
if (Get-Process python -ErrorAction SilentlyContinue) { Say "STOP: a Python process is running"; exit 3 }
$ciks = (& python scripts/v05_evidence/cohort_by_size.py | Select-String -Pattern '^\s*\d+\s+(\d{10})\s' |
    ForEach-Object { $_.Matches[0].Groups[1].Value }) -join " "
Say "chain begin, git $(git rev-parse --short HEAD), tag $Tag, quarters $($Quarters -join ',')"
Step "01_extract"     "scripts/rebuild_outputs.py --bdc-holdings --cohort" 8
Step "02_fieldstatus" "scripts/refresh_ixbrl_field_status.py --published --ciks $ciks" 8
Step "03_highlights"  "scripts/rebuild_outputs.py --highlights" 8
Step "04_financials"  "scripts/rebuild_outputs.py --financials" 8
Step "05_unified"     "scripts/rebuild_outputs.py --unified" 14
Step "06_returns"     "scripts/rebuild_outputs.py --returns" 12
Step "07_refresh"     "scripts/rebuild_outputs.py --derivatives --sector-breakdown --income --pik-status --pik-proxy" 8
Step "08_frontend"    "scripts/rebuild_outputs.py --frontend" 8
$i = 0
foreach ($q in $Quarters) {
    $from = if ($i -eq 0) { "nonaccrual" } else { "queue" }
    $pid_ = "{0}_{1}" -f $Tag, ($q -replace '-', '')
    Step ("09_qpass_" + ($q -replace '-', '')) "scripts/run_quarter_pass.py --pass-id $pid_ --quarter $q --from $from --until acceptance" 8
    $i++
}
Step "10_reattest" "scripts/reattest_quarters.py check" 6 -NonFatal
$firstLedger = "data/output/quarter_pass/{0}_{1}/findings_ledger_pre.csv" -f $Tag, ($Quarters[-1] -replace '-', '')  # last pass: its ledger covers all quarters
Step "11_parity"   "scripts/v05_evidence/sandbox_parity.py --quarters $($Quarters -join ' ') --out $($dir.Substring($repo.Path.Length + 1)) --prod-ledger $firstLedger" 4 -NonFatal
Step "12_status"   "scripts/v05_evidence/outstanding_status.py" 4
Say "chain end OK (check NONFATAL lines: re-attestation and parity need reading, not ignoring)"
