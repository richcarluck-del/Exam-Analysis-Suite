@echo off
setlocal

REM 切換到題庫前端所在的 client-app 目錄
cd /d "%~dp0analyzer\client-app"

title Exam Analyzer - Frontend (Vite + React)
echo ==========================================
echo  啟動題庫前端（Vite + React）
echo  啟動後訪問：http://localhost:5173/paper-preview
echo ==========================================

echo 使用 Node：
node -v
echo.

REM 啟動 Vite 開發服務
npm run dev

endlocal
pause
