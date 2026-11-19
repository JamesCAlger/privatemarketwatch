# Parses cached SEC filings into the filed layer. Usage: .\warehouse\parse.ps1 [--cik N] [--accession A] [--verify] [--reparse]
# Runs from the repository root, because the default --raw and --out paths are relative to it.
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "Python is not installed at $py. See warehouse\README.md, Environment."
    exit 1
}
$root = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = $PSScriptRoot
$code = 1
Push-Location $root
try {
    $global:LASTEXITCODE = $null
    & $py -m filed_parser @args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($null -eq $code) { $code = 1 }
exit $code
