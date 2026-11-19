# Runs dbt for this project. Usage: .\warehouse\dbt.ps1 build
# Telemetry is off and the working directory is the project folder, because the
# project's paths to data/output are relative to it.
$env:DBT_SEND_ANONYMOUS_USAGE_STATS = 'false'
$dbt = Join-Path $PSScriptRoot '.venv\Scripts\dbt.exe'
if (-not (Test-Path $dbt)) {
    Write-Host "dbt is not installed at $dbt. See warehouse\README.md, Environment."
    exit 1
}
$code = 1
Push-Location $PSScriptRoot
try {
    $global:LASTEXITCODE = $null
    & $dbt @args --profiles-dir . --no-version-check
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($null -eq $code) { $code = 1 }
exit $code
