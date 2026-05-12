# Launches Analyzer API :8000, Preprocessor Test UI :8001, Report client-app Vite :5174
# Repo layout: Analyzer shares DB with Test UI; Vite proxies /api to :8000.
# SKIP_ANALYZER_API=1 avoids start_test_ui.bat starting a duplicate Analyzer window.

param(
    [switch]$SkipTestUiFrontendBuild,
    [switch]$SkipFreeReportPort,
    [switch]$SkipFreeAnalyzerPort,
    [switch]$SkipFreeTestUiPort,
    [switch]$SkipWaitForAnalyzerReady,
    [ValidateRange(30, 900)]
    [int]$AnalyzerReadyTimeoutSec = 240
)

$ErrorActionPreference = 'Stop'

function Stop-ListenersOnPort {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($listenPid in $conns) {
        try {
            Stop-Process -Id $listenPid -Force -ErrorAction Stop
            Write-Host ("  Stopped PID {0} that was listening on :{1}" -f $listenPid, $Port)
        }
        catch {
            Write-Warning ("Could not stop PID {0} on port {1}: {2}" -f $listenPid, $Port, $_)
        }
    }
}

function Wait-AnalyzerHttpReady {
    param(
        [int]$TimeoutSec,
        [int]$PollSec = 2
    )
    $url = 'http://127.0.0.1:8000/docs'
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $n = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200) {
                Write-Host ("  Analyzer responded OK at {0} (after ~{1}s)." -f $url, ($n * $PollSec))
                return $true
            }
        }
        catch {
            # Typical: connection refused until uvicorn finishes heavy imports.
        }
        $n++
        if (($n % 5) -eq 1 -or $n -eq 1) {
            Write-Host ('  Waiting for Analyzer on :8000 (first import can take 30–120s)...' )
        }
        Start-Sleep -Seconds $PollSec
    }
    return $false
}

$RepoRoot = if ($PSScriptRoot) { $PSScriptRoot.TrimEnd('\') } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

$pythonExe = 'python'
foreach ($candidate in @(
        (Join-Path $RepoRoot '.venv_commercial\Scripts\python.exe'),
        (Join-Path $RepoRoot '.venv\Scripts\python.exe'))) {
    if (Test-Path -LiteralPath $candidate) {
        $pythonExe = $candidate
        break
    }
}

$analyzerCmd = Join-Path $RepoRoot 'preprocessor\preprocessor_test_ui\start_analyzer_api_8000.cmd'
$testUiBat = Join-Path $RepoRoot 'preprocessor\preprocessor_test_ui\start_test_ui.bat'
$clientDir = Join-Path $RepoRoot 'analyzer\client-app'

if (-not (Test-Path -LiteralPath $analyzerCmd)) { throw "Missing: $analyzerCmd" }
if (-not (Test-Path -LiteralPath $testUiBat)) { throw "Missing: $testUiBat" }
if (-not (Test-Path -LiteralPath $clientDir)) { throw "Missing: $clientDir" }

Write-Host "Repo:           $RepoRoot"
Write-Host "Python:        $pythonExe"
Write-Host ""

if (-not $SkipFreeAnalyzerPort) {
    Write-Host '[1/3] Analyzer API — freeing :8000 if a previous uvicorn is still listening (avoids WinError 10013)...'
    Stop-ListenersOnPort -Port 8000
    Start-Sleep -Seconds 1
}

Write-Host '[1/3] Starting Analyzer FastAPI http://127.0.0.1:8000 ...'
Start-Process -FilePath 'cmd.exe' -ArgumentList @(
    '/k', ('call "{0}" "{1}"' -f $analyzerCmd, $pythonExe)
)

Start-Sleep -Seconds 3

if (-not $SkipWaitForAnalyzerReady) {
    Write-Host '[1/3] Waiting until Analyzer listens (avoids Vite proxy ECONNREFUSED to :8000)...'
    $ready = Wait-AnalyzerHttpReady -TimeoutSec $AnalyzerReadyTimeoutSec -PollSec 2
    if (-not $ready) {
        throw "Analyzer API did not become ready within ${AnalyzerReadyTimeoutSec}s. Check the Analyzer window for tracebacks."
    }
}
else {
    Write-Host '[1/3] SkipWaitForAnalyzerReady: proceeding without HTTP check — Vite may show ECONNREFUSED until Analyzer finishes loading.' -ForegroundColor Yellow
}

if (-not $SkipFreeTestUiPort) {
    Write-Host '[2/3] Unified Test UI — freeing :8001 if an old uvicorn is still running...'
    Stop-ListenersOnPort -Port 8001
    Start-Sleep -Seconds 1
}

$buildSkip = ''
if ($SkipTestUiFrontendBuild) {
    $buildSkip = 'set SKIP_FRONTEND_BUILD=1& '
}
$testUiLine = '{0}set SKIP_ANALYZER_API=1& call "{1}"' -f $buildSkip, $testUiBat

Write-Host '[2/3] Starting Preprocessor Test UI http://localhost:8001 (SKIP_ANALYZER_API=1)...'
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', $testUiLine) -WorkingDirectory $RepoRoot

Start-Sleep -Seconds 5

if (-not $SkipFreeReportPort) {
    Write-Host '[3/3] Report Vite — freeing :5174 if a previous dev server is still running...'
    Stop-ListenersOnPort -Port 5174
    Start-Sleep -Seconds 1
}
Write-Host '[3/3] Starting Report Vite http://127.0.0.1:5174 ...'
Start-Process -FilePath 'cmd.exe' -ArgumentList @(
    '/k', ('cd /d "{0}" && npm run dev' -f $clientDir))

Write-Host ""
Write-Host "Done. Open:"
Write-Host "  - Analyzer API:     http://127.0.0.1:8000/"
Write-Host "  - Unified Test UI:  http://localhost:8001/"
Write-Host "  - Report /matches: http://127.0.0.1:5174/report  (requires API on :8000)"
Write-Host ""
Write-Host "Optional: .\start_suite.ps1 -SkipTestUiFrontendBuild  (skip Test UI npm run build)"
Write-Host "Optional: .\start_suite.ps1 -SkipFreeReportPort     (do not kill process on :5174; use if another app needs the port)"
Write-Host "Optional: .\start_suite.ps1 -SkipFreeAnalyzerPort    (do not kill process on :8000 before starting Analyzer)"
Write-Host "Optional: .\start_suite.ps1 -SkipFreeTestUiPort       (do not kill process on :8001 before Test UI)"
Write-Host "Optional: .\start_suite.ps1 -AnalyzerReadyTimeoutSec 300"
Write-Host "Optional: .\start_suite.ps1 -SkipWaitForAnalyzerReady  (dangerous; Vite may start before :8000 is up)"
