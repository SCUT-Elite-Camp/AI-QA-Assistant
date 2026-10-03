@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo                AI-QA-Assistant One-Click Deployment
echo =====================================================================
echo.

cd /d "%~dp0"

REM ----------------------------------------------------------------------
REM Step 1: Check and auto-launch Docker if not running
REM ----------------------------------------------------------------------
echo [1/4] Checking Docker daemon status...
docker info >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Docker daemon is running and ready.
    goto :docker_ready
)

echo [INFO] Docker daemon is not active yet.
set "DOCKER_EXE="
if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    set "DOCKER_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
) else if exist "%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe" (
    set "DOCKER_EXE=%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe"
)

if not "%DOCKER_EXE%"=="" (
    echo [INFO] Found Docker Desktop at "%DOCKER_EXE%".
    echo [INFO] Launching Docker Desktop in background, please wait...
    start "" "%DOCKER_EXE%"
) else (
    echo [INFO] Attempting to launch Docker Desktop via system command...
    start "" "Docker Desktop" 2>nul
)

echo [INFO] Waiting for Docker daemon to initialize...
set /a DOCKER_WAIT=0
:wait_docker_loop
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Docker daemon is now running and ready!
    goto :docker_ready
)
set /a DOCKER_WAIT+=3
if %DOCKER_WAIT% lss 90 (
    echo        ... still initializing Docker (%DOCKER_WAIT%s / 90s)
    goto :wait_docker_loop
)

echo [ERROR] Docker daemon did not start in time. Please check Docker Desktop and retry.
pause
exit /b 1

:docker_ready

REM ----------------------------------------------------------------------
REM Step 2: Auto-prepare .env file
REM ----------------------------------------------------------------------
echo.
echo [2/4] Checking environment configuration (.env)...
if not exist ".env" (
    if exist ".env.docker.example" (
        echo [INFO] Generating .env from template .env.docker.example...
        copy /y ".env.docker.example" ".env" >nul
        echo [OK] .env configuration file created.
    ) else (
        echo [WARNING] .env.docker.example not found.
    )
) else (
    echo [OK] .env configuration file exists.
)

REM ----------------------------------------------------------------------
REM Step 3: Build and start containers
REM ----------------------------------------------------------------------
echo.
echo [3/4] Launching Docker containers (Milvus + Agent + Web UI)...
echo Building images on first run, please wait...
echo.

docker compose up --build -d

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to start Docker containers. Please check error output above.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------
REM Step 4: Ready and auto-open browser
REM ----------------------------------------------------------------------
echo.
echo [4/4] Opening Web Interface in your default browser...
timeout /t 2 /nobreak >nul
start http://localhost:3000

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
