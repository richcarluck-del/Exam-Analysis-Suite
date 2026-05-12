$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$node = "node"
$script = Join-Path $root "scripts\deepseek_local_mcp_bridge.js"
$logDir = Join-Path $root "scripts\_out"
$stdoutLogFile = Join-Path $logDir "deepseek_local_mcp_bridge.stdout.log"
$stderrLogFile = Join-Path $logDir "deepseek_local_mcp_bridge.stderr.log"
$port = 8765

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$userApiKey = [Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")
$userLegacyToken = [Environment]::GetEnvironmentVariable("DEEPSEEK_MCP_AUTH_TOKEN", "User")

if (-not $userApiKey -and -not $userLegacyToken) {
    throw "Missing user env DEEPSEEK_API_KEY (or legacy DEEPSEEK_MCP_AUTH_TOKEN)"
}

if ($userApiKey) {
    $env:DEEPSEEK_API_KEY = $userApiKey
}

if ($userLegacyToken) {
    $env:DEEPSEEK_MCP_AUTH_TOKEN = $userLegacyToken
}

$env:DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $existingPids = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($existingPid in $existingPids) {
        try {
            Stop-Process -Id $existingPid -Force -ErrorAction Stop
            Write-Output "Stopped existing process on port $port (PID: $existingPid)"
        } catch {
            Write-Warning "Failed to stop existing process on port $port (PID: $existingPid): $($_.Exception.Message)"
        }
    }
    Start-Sleep -Milliseconds 500
}

Start-Process `
    -FilePath $node `
    -ArgumentList @($script) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLogFile `
    -RedirectStandardError $stderrLogFile

Write-Output "DeepSeek local MCP bridge started. Logs: $stdoutLogFile , $stderrLogFile"
