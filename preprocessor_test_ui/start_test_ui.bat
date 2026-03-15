@echo off
title Preprocessor Test UI
echo Starting Preprocessor Test UI...
echo You can access the UI at http://localhost:8001
python -m uvicorn main:app --host 0.0.0.0 --port 8001
