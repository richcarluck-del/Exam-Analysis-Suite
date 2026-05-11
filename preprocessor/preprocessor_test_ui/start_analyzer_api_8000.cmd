@echo off
setlocal EnableExtensions

REM Launcher for Analyzer FastAPI (:8000) used by analyzer/client-app Vite dev proxy.
REM Passed arg: full path to python.exe

set "PYTHON_EXE=%~1"
if "%PYTHON_EXE%"=="" (
  echo ERROR: pass PYTHON_EXE as arg 1.
  exit /b 2
)

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.."
set "REPO_ROOT=%CD%"
popd

cd /d "%REPO_ROOT%\analyzer"
if errorlevel 1 (
  echo ERROR: could not cd to analyzer folder.
  exit /b 3
)

echo [Analyzer API] Repo: "%REPO_ROOT%\analyzer"
echo [Analyzer API] Python: "%PYTHON_EXE%"
echo [Analyzer API] http://127.0.0.1:8000  ^(exam-sessions, reports proxy target^)

REM Kill previous listener on :8000 to avoid WinError 10013 when restarting ^(often old uvicorn^).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0free_port_listen.ps1" -Port 8000

timeout /t 1 /nobreak >nul

REM shared/ lives at repo root; uvicorn cwd is analyzer\ so PYTHONPATH must include REPO_ROOT
set "PYTHONPATH=%REPO_ROOT%;%PYTHONPATH%"

"%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir "%REPO_ROOT%\analyzer\app" --log-config "%REPO_ROOT%\analyzer\log_config.yaml"
