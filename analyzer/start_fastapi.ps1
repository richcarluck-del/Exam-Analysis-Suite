$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

$venvCandidates = @(
    (Join-Path $repoRoot ".venv_commercial\Scripts\python.exe"),
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $scriptDir ".venv\Scripts\python.exe")
)
$pythonExe = $venvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExe) {
    throw "No project virtualenv python found. Checked: $($venvCandidates -join ', ')"
}

Write-Host "Starting FastAPI server..."
Write-Host "Repo root: $repoRoot"
Write-Host "Python: $pythonExe"

Push-Location $repoRoot
try {
    & $pythonExe -m uvicorn analyzer.app.main:app --host 0.0.0.0 --port 8000 --reload --log-config analyzer\log_config.yaml
}
finally {
    Pop-Location
}
