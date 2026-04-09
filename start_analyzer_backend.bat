@echo off
setlocal

REM 切換到項目根目錄
cd /d "%~dp0"

title Exam Analyzer - Backend (FastAPI)
echo ==========================================
echo  啟動題庫後端(FastAPI + Uvicorn)
echo  默認地址: http://localhost:8000
echo ==========================================

REM 優先使用倉庫下的虛擬環境，如果沒有就用全局 python
set "PYTHON_EXE="
if exist ".venv_commercial\Scripts\python.exe" (
    set "PYTHON_EXE=.venv_commercial\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo 使用 Python: %PYTHON_EXE%
echo.

REM 從項目根目錄運行 uvicorn，這樣才能找到 shared 模塊
"%PYTHON_EXE%" -m uvicorn analyzer.app.main:app --host 0.0.0.0 --port 8000 --reload --log-config analyzer/log_config.yaml

endlocal
pause
