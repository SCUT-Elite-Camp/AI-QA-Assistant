@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =====================================================================
echo                AI-QA-Assistant 一键本地启动脚本
echo =====================================================================
echo.

cd /d "%~dp0"

REM ----------------------------------------------------------------------
REM 1. 检查 Python 及虚拟环境
REM ----------------------------------------------------------------------
echo [1/4] 检查 Python 后端环境...

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo [OK] 发现虚拟环境: .venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [OK] 发现虚拟环境: venv
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo [INFO] 未检测到 .venv，正在使用系统 Python 创建虚拟环境...
        python -m venv .venv
        if exist ".venv\Scripts\python.exe" (
            set "PYTHON_EXE=.venv\Scripts\python.exe"
            echo [INFO] 正在安装后端依赖 requirements.txt ...
            .venv\Scripts\pip.exe install -r requirements.txt
            echo [OK] 依赖安装完成.
        ) else (
            set "PYTHON_EXE=python"
        )
    ) else (
        echo [ERROR] 未找到 Python 环境，请先安装 Python 3.10+ 并配置 PATH。
        pause
        exit /b 1
    )
)

REM ----------------------------------------------------------------------
REM 2. 检查 Node.js / 前端包管理器与依赖
REM ----------------------------------------------------------------------
echo.
echo [2/4] 检查前端运行环境...

set "PKG_MGR="
where pnpm >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PKG_MGR=pnpm"
) else (
    where npm >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "PKG_MGR=npm"
    ) else (
        echo [ERROR] 未找到 Node.js / pnpm / npm 环境，请先安装 Node.js 18+。
        pause
        exit /b 1
    )
)
echo [OK] 使用包管理器: %PKG_MGR%

if not exist "frontend\node_modules" (
    echo [INFO] 正在安装前端依赖 (首次启动可能需要 1-2 分钟)...
    cd frontend
    call %PKG_MGR% install
    cd ..
    echo [OK] 前端依赖安装完成.
) else (
    echo [OK] 前端依赖 node_modules 已就绪.
)

REM ----------------------------------------------------------------------
REM 3. 启动后端与前端服务
REM ----------------------------------------------------------------------
echo.
echo [3/4] 正在启动服务...

echo [INFO] 启动后端 API 服务 (端口 8000)...
start "AI-QA-Assistant Backend (:8000)" cmd /k "cd /d "%~dp0" && %PYTHON_EXE% -m app"

timeout /t 2 /nobreak >nul

echo [INFO] 启动前端 Web 服务 (端口 3000)...
if "%PKG_MGR%"=="pnpm" (
    start "AI-QA-Assistant Frontend (:3000)" cmd /k "cd /d "%~dp0frontend" && pnpm run dev"
) else (
    start "AI-QA-Assistant Frontend (:3000)" cmd /k "cd /d "%~dp0frontend" && npm run dev"
)

REM ----------------------------------------------------------------------
REM 4. 打开浏览器
REM ----------------------------------------------------------------------
echo.
echo [4/4] 准备就绪，正在打开浏览器...
timeout /t 3 /nobreak >nul
start http://localhost:3000

echo.
echo =====================================================================
echo                所有服务已成功启动！
echo =====================================================================
echo  - 前端界面 (Web UI):   http://localhost:3000
echo  - 后端接口 (API Docs): http://localhost:8000/docs
echo.
echo  提示:
echo   * 后端与前端分别运行在独立的终端窗口中
echo   * 如需关闭服务，直接关闭弹出的两个终端窗口即可
echo =====================================================================
echo.
pause
