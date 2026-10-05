# AI-QA-Assistant Local Startup Script for PowerShell
$ErrorActionPreference = "Stop"

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "               AI-QA-Assistant 一键本地启动脚本 (PowerShell)           " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

# 1. Check Python & Virtual Environment
Write-Host "[1/4] 检查 Python 后端环境..." -ForegroundColor Yellow
$PythonExe = ""
if (Test-Path "$RootDir\.venv\Scripts\python.exe") {
    $PythonExe = "$RootDir\.venv\Scripts\python.exe"
    Write-Host "[OK] 发现虚拟环境: .venv" -ForegroundColor Green
} elseif (Test-Path "$RootDir\venv\Scripts\python.exe") {
    $PythonExe = "$RootDir\venv\Scripts\python.exe"
    Write-Host "[OK] 发现虚拟环境: venv" -ForegroundColor Green
} else {
    $SysPython = Get-Command python -ErrorAction SilentlyContinue
    if ($SysPython) {
        Write-Host "[INFO] 未检测到 .venv，正在使用系统 Python 创建虚拟环境..." -ForegroundColor Cyan
        & python -m venv "$RootDir\.venv"
        if (Test-Path "$RootDir\.venv\Scripts\python.exe") {
            $PythonExe = "$RootDir\.venv\Scripts\python.exe"
            Write-Host "[INFO] 正在安装后端依赖 requirements.txt ..." -ForegroundColor Cyan
            & "$RootDir\.venv\Scripts\pip.exe" install -r "$RootDir\requirements.txt"
            Write-Host "[OK] 依赖安装完成." -ForegroundColor Green
        } else {
            $PythonExe = "python"
        }
    } else {
        Write-Host "[ERROR] 未找到 Python 环境，请先安装 Python 3.10+。" -ForegroundColor Red
        Exit 1
    }
}

# 2. Check Node.js & Package Manager
Write-Host ""
Write-Host "[2/4] 检查前端运行环境..." -ForegroundColor Yellow
$PkgMgr = "pnpm"
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        $PkgMgr = "npm"
    } else {
        Write-Host "[ERROR] 未找到 Node.js / pnpm / npm 环境，请先安装 Node.js 18+。" -ForegroundColor Red
        Exit 1
    }
}
Write-Host "[OK] 使用包管理器: $PkgMgr" -ForegroundColor Green

if (-not (Test-Path "$RootDir\frontend\node_modules")) {
    Write-Host "[INFO] 正在安装前端依赖 (首次启动可能需要 1-2 分钟)..." -ForegroundColor Cyan
    Push-Location "$RootDir\frontend"
    & $PkgMgr install
    Pop-Location
    Write-Host "[OK] 前端依赖安装完成." -ForegroundColor Green
} else {
    Write-Host "[OK] 前端依赖 node_modules 已就绪." -ForegroundColor Green
}

# 3. Start Backend and Frontend in separate windows
Write-Host ""
Write-Host "[3/4] 正在启动服务..." -ForegroundColor Yellow
Write-Host "[INFO] 启动后端 API 服务 (端口 8000)..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k title AI-QA-Assistant Backend (:8000) && cd /d `"$RootDir`" && `"$PythonExe`" -m app"

Start-Sleep -Seconds 2

Write-Host "[INFO] 启动前端 Web 服务 (端口 3000)..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k title AI-QA-Assistant Frontend (:3000) && cd /d `"$RootDir\frontend`" && $PkgMgr run dev"

# 4. Open Browser
Write-Host ""
Write-Host "[4/4] 准备就绪，正在打开浏览器..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "               所有服务已成功启动！" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " - 前端界面 (Web UI):   http://localhost:3000" -ForegroundColor White
Write-Host " - 后端接口 (API Docs): http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host " 提示: 后端与前端在独立窗口运行，关闭窗口即可停止服务。" -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Green
