# Starts the report client-app (Vite dev server, default port 5174).
# Proxies /api to http://127.0.0.1:8000 — you need Analyzer FastAPI listening there.
# Typical dev: run preprocessor\preprocessor_test_ui\start_test_ui.bat (starts Analyzer :8000 then Test UI :8001),
# then this script; or run analyzer\start_fastapi.ps1 in another terminal before npm run dev.

Write-Host "Starting Vite (report UI). Ensure Analyzer API is on http://127.0.0.1:8000 ..."

# Navigate to the client-app directory within the current project
cd .\client-app

npm run dev
