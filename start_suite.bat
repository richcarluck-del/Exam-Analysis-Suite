@echo off
setlocal
REM One-click dev stack: Analyzer :8000 + Test UI :8001 + Report Vite :5174

cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0start_suite.ps1" %*

endlocal
