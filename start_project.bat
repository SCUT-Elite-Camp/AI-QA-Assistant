@echo off
chcp 65001 >nul
title AI QA Assistant - One-Click Launcher

echo ===================================================
echo   AI QA Assistant - Starting One-Click Environment
echo ===================================================
echo.

set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set HF_DATASETS_OFFLINE=1
set DISABLE_SYMLINKS_WARNING=1

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" start_project.py
) else (
    python start_project.py
)

pause
