@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo                AI-QA-Assistant Docker Full-Stack Deploy
echo =====================================================================
echo.

cd /d "%~dp0"

REM Step 1: Check Docker status
echo [1/3] Checking Docker status...
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker daemon is not running or not installed!
    echo         Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)
echo [OK] Docker is running.

REM Step 2: Check .env configuration file
echo [2/3] Checking environment configuration...
if not exist ".env" (
    if exist ".env.docker.example" (
        echo [INFO] .env not found. Creating .env from .env.docker.example...
        copy /y ".env.docker.example" ".env" >nul
        echo [IMPORTANT] Created .env. Please open .env and set your LLM_API_KEY.
    ) else (
        echo [WARNING] .env file not found.
    )
) else (
    echo [OK] .env configuration file exists.
)

REM Step 3: Launch Docker containers
echo.
echo [3/3] Launching Docker containers (Milvus + Agent + Web UI)...
echo Building images on first run, please wait...
echo.

docker compose up --build -d

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to start containers. Please check error output above.
    echo.
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo                All Services Started Successfully!
echo =====================================================================
echo  - Web UI:       http://localhost:3000
echo  - Agent API:    http://localhost:8000
echo  - Milvus Store: localhost:19530
echo.
echo  Useful commands:
echo   * View live logs:  docker compose logs -f
echo   * Stop services:   docker compose down
echo =====================================================================
echo.
pause
