param([int]$Port = 8766)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
)
$pythonPath = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonPath) { throw 'Create a virtualenv and install this project first: python -m pip install -e .' }
Write-Host "Flutter prototype backend: http://127.0.0.1:$Port"
Write-Host 'Data: .agent-data/flutter-prototype (separate from the web app)'
& $pythonPath -m companion_agent.app --port $Port --data-dir .agent-data/flutter-prototype
exit $LASTEXITCODE
