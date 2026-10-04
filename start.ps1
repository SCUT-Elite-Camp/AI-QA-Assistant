# AI-QA-Assistant Local Startup Script for PowerShell
$ErrorActionPreference = "Stop"

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "               AI-QA-Assistant 一键本地启动脚本 (PowerShell)           " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

# 1. Check Docker & Milvus / Redis Stack
Write-Host "[1/5] 检查 Milvus 向量数据库与 Docker 环境..." -ForegroundColor Yellow
$DockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($DockerCmd) {
    $dockerRunning = $false
    try {
        $res = & docker info 2>&1
        if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
    } catch {
        $dockerRunning = $false
    }

    if ($dockerRunning) {
        Write-Host "[INFO] Docker 守护进程运行中，正在唤醒 Milvus 向量库及依赖容器..." -ForegroundColor Cyan
        & docker compose up -d etcd minio milvus-standalone redis *>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Milvus 向量数据库与 Redis 服务已在后台就绪 (Port: 19530, 6379)." -ForegroundColor Green
        } else {
            Write-Host "[WARN] 启动 Milvus 容器失败，系统将自动降级为 BM25 文本检索模式." -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "[INFO] Docker 守护进程未启动，尝试唤醒 Docker Desktop..." -ForegroundColor Cyan
        $dockerExePaths = @(
            "C:\Program Files\Docker\Docker\Docker Desktop.exe",
            "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe"
        )
        $foundExe = $dockerExePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($foundExe) {
            Start-Process $foundExe
            Write-Host "[INFO] 已触发 Docker Desktop 启动 (后台加载中)..." -ForegroundColor Cyan
        }
        Write-Host "[WARN] Docker 尚未完全就绪，系统将自动使用 BM25 检索兜底保障正常运行." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[INFO] 本地未检测到 Docker 命令，系统将以内置 BM25 模式运行." -ForegroundColor DarkYellow
}

# 2. Check Python & Virtual Environment
Write-Host ""
Write-Host "[2/5] 检查 Python 后端环境..." -ForegroundColor Yellow
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

# 3. Check Node.js & Package Manager
Write-Host ""
Write-Host "[3/5] 检查前端运行环境..." -ForegroundColor Yellow
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

# 4. Start Backend and Frontend in separate windows
Write-Host ""
Write-Host "[4/5] 正在启动服务..." -ForegroundColor Yellow
Write-Host "[INFO] 启动后端 API 服务 (端口 8000)..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k title AI-QA-Assistant Backend (:8000) && cd /d `"$RootDir`" && `"$PythonExe`" -m app"

Start-Sleep -Seconds 2

Write-Host "[INFO] 启动前端 Web 服务 (端口 3000)..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k title AI-QA-Assistant Frontend (:3000) && cd /d `"$RootDir\frontend`" && $PkgMgr run dev"

# 5. Open Browser
Write-Host ""
Write-Host "[5/5] 准备就绪，正在打开浏览器..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "               所有服务已成功启动！" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " - 前端界面 (Web UI):   http://localhost:3000" -ForegroundColor White
Write-Host " - 后端接口 (API Docs): http://localhost:8000/docs" -ForegroundColor White
Write-Host " - 向量服务 (Milvus):   localhost:19530" -ForegroundColor White
Write-Host ""
Write-Host " 提示: 后端与前端在独立窗口运行，关闭窗口即可停止服务。" -ForegroundColor Gray
Write-Host "=====================================================================" -ForegroundColor Green
