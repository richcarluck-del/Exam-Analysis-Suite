@echo off
setlocal

cd /d "%~dp0"
title Exam Analyzer - Backend + Frontend
echo ==========================================
echo  一鍵啟動題庫後端和前端
echo  後端：http://localhost:8000
echo  前端：http://localhost:5173/paper-preview
echo ==========================================

REM 在新窗口中啟動後端
start "Exam Analyzer Backend" cmd /k "%~dp0start_analyzer_backend.bat"

REM 在新窗口中啟動前端
start "Exam Analyzer Frontend" cmd /k "%~dp0start_analyzer_frontend.bat"

endlocal
