param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$frontendEntry = Join-Path $projectRoot 'frontend\dist\index.html'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Host 'Missing project Python: .venv\Scripts\python.exe'
    Write-Host 'Create the project virtual environment and install requirements.txt first.'
    exit 1
}
if (-not (Test-Path -LiteralPath $frontendEntry -PathType Leaf)) {
    Write-Host 'Missing frontend build: frontend\dist\index.html'
    Write-Host 'Run npm run build from the frontend directory first.'
    exit 1
}

Write-Host 'Local startup files are ready. This check does not contact model services.'
if ($CheckOnly) { exit 0 }

Write-Host 'After the server starts, open http://127.0.0.1:8000. Press Ctrl+C to stop.'
$serverExitCode = 1
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath (Join-Path $projectRoot 'server.py')
    $serverExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $serverExitCode
