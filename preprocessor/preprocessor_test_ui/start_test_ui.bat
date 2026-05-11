@echo off
setlocal EnableExtensions
REM Must stay ASCII-only: UTF-8 bytes in REM break cmd.exe on CP936 (garbled lines run as commands).

cd /d "%~dp0..\.."
if errorlevel 1 (
    echo ERROR: could not cd to repo root from "%~dp0"
    exit /b 1
)
set "REPO_ROOT=%CD%"

cd /d "%REPO_ROOT%"
if errorlevel 1 (
    echo ERROR: could not cd to REPO_ROOT=%REPO_ROOT%
    exit /b 1
)

title Preprocessor Test UI
echo Starting Preprocessor Test UI...
echo Open: http://localhost:8001

if "%KNOWLEDGE_POINT_DEV_UI_ENABLED%"=="" (
    set "KNOWLEDGE_POINT_DEV_UI_ENABLED=true"
)

REM PDF / Pix2Text OCR defaults for topic ingest
set "QUESTION_BANK_PDF_OCR_MODE=auto"
set "QUESTION_BANK_PDF_OCR_THRESHOLD=0.12"
set "QUESTION_BANK_PDF_OCR_RENDER_SCALE=2.5"
set "QUESTION_BANK_PDF_OCR_ENABLE_FORMULA=true"
set "QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER=true"
set "QUESTION_BANK_OCR_WORKER_TIMEOUT_SECONDS=900"
set "PIX2TEXT_DEVICE=cpu"

REM PDF: math-symbol spans to small PNG clips
set "QUESTION_BANK_PDF_MATH_CLIP_IMAGES=true"
set "QUESTION_BANK_PDF_MATH_CLIP_DPI=144"

REM DOCX: rasterize Word OMML to PNG via local Word COM (set false if no Word)
set "QUESTION_BANK_DOCX_OMML_AS_IMAGES=true"

set "PYTHON_EXE="
if exist "%REPO_ROOT%\.venv_commercial\Scripts\python.exe" (
    set "PYTHON_EXE=%REPO_ROOT%\.venv_commercial\Scripts\python.exe"
) else if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

set "TEST_UI_DIR=%REPO_ROOT%\preprocessor\preprocessor_test_ui"

echo REPO_ROOT=%REPO_ROOT%
echo TEST_UI_DIR=%TEST_UI_DIR%
echo Using Python: %PYTHON_EXE%
echo KNOWLEDGE_POINT_DEV_UI_ENABLED=%KNOWLEDGE_POINT_DEV_UI_ENABLED%
echo QUESTION_BANK_PDF_OCR_MODE=%QUESTION_BANK_PDF_OCR_MODE% THRESHOLD=%QUESTION_BANK_PDF_OCR_THRESHOLD% SCALE=%QUESTION_BANK_PDF_OCR_RENDER_SCALE%
echo QUESTION_BANK_PDF_OCR_ENABLE_FORMULA=%QUESTION_BANK_PDF_OCR_ENABLE_FORMULA% APPEND_PAGE_RASTER=%QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER%
echo QUESTION_BANK_PDF_MATH_CLIP_IMAGES=%QUESTION_BANK_PDF_MATH_CLIP_IMAGES% DPI=%QUESTION_BANK_PDF_MATH_CLIP_DPI%
echo QUESTION_BANK_DOCX_OMML_AS_IMAGES=%QUESTION_BANK_DOCX_OMML_AS_IMAGES%
echo QUESTION_BANK_OCR_WORKER_TIMEOUT_SECONDS=%QUESTION_BANK_OCR_WORKER_TIMEOUT_SECONDS% PIX2TEXT_DEVICE=%PIX2TEXT_DEVICE%

REM Paper preview and other SPA routes are served from frontend\dist (see main.py). Edits under frontend\src require a build.
if "%SKIP_FRONTEND_BUILD%"=="" (
  echo Building preprocessor_test_ui frontend ^(npm run build^) ...
  pushd "%REPO_ROOT%\preprocessor\preprocessor_test_ui\frontend"
  call npm run build
  if errorlevel 1 (
    echo ERROR: npm run build failed
    popd
    exit /b 1
  )
  popd
) else (
  echo SKIP_FRONTEND_BUILD is set; using existing frontend\dist
)

REM Report UI (analyzer\client-app npm run dev on 5174) proxies /api to http://127.0.0.1:8000 (Analyzer FastAPI).
REM This Test UI on 8001 does not implement /api/exam-sessions; that API lives in analyzer\app\main.py.
REM Start Analyzer in a second window unless skipped (Preprocessor-only dev: set SKIP_ANALYZER_API=1).
if "%SKIP_ANALYZER_API%"=="" (
  echo.
  echo Starting Analyzer FastAPI on http://127.0.0.1:8000 in another window ^(for report / matches / exam-sessions^).
  echo Set SKIP_ANALYZER_API=1 to skip if you only need this Test UI on 8001.
  echo.
  start "Analyzer FastAPI :8000" cmd /k call "%TEST_UI_DIR%\start_analyzer_api_8000.cmd" "%PYTHON_EXE%"
  timeout /t 2 /nobreak >nul
) else (
  echo SKIP_ANALYZER_API=1 - not starting Analyzer on 8000. Run analyzer\start_fastapi.ps1 manually if you use report client-app.
)

"%PYTHON_EXE%" -m uvicorn main:app --app-dir "%TEST_UI_DIR%" --host 0.0.0.0 --port 8001 --reload --reload-dir "%TEST_UI_DIR%" --reload-dir "%REPO_ROOT%\analyzer\app"

endlocal
