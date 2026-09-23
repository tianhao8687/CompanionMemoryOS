param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'First run: python -m venv .venv'
    Write-Host 'Then run: .\.venv\Scripts\python.exe -m pip install -e ".[dev]"'
    exit 1
}
& $pythonPath -m companion_agent.app --port $Port
exit $LASTEXITCODE
