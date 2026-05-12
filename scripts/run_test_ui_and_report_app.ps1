# 同时打开两个本地前端（请在本机 8001 已启动分析/测试 API 的前提下使用）:
#   - 摄入测试平台:  http://127.0.0.1:5173
#   - 试卷/学情报告: http://127.0.0.1:5174/report
# 用法：在仓库根目录执行:  .\scripts\run_test_ui_and_report_app.ps1

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$testUi = Join-Path $Root "preprocessor\preprocessor_test_ui\frontend"
$report = Join-Path $Root "analyzer\client-app"
if (-not (Test-Path (Join-Path $testUi "package.json"))) { throw "未找到: $testUi" }
if (-not (Test-Path (Join-Path $report "package.json"))) { throw "未找到: $report" }

Start-Process powershell -ArgumentList @(
  "-NoExit", "-NoLogo",
  "-Command", "Set-Location '$testUi'; Write-Host '摄入测试平台 -> http://127.0.0.1:5173' -ForegroundColor Cyan; npm run dev"
)
Start-Process powershell -ArgumentList @(
  "-NoExit", "-NoLogo",
  "-Command", "Set-Location '$report'; Write-Host '试卷报告 /report -> http://127.0.0.1:5174/report' -ForegroundColor Cyan; npm run dev"
)
Write-Host "已在新窗口各启动一个 npm run dev。请确保 FastAPI 监听 http://127.0.0.1:8001" -ForegroundColor Green
