@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo =====================================================================
echo                AI-QA-Assistant Docker 一键全栈部署
echo =====================================================================
echo.

cd /d "%~dp0"

:: 1. 检查 Docker 是否安装且正在运行
echo [1/3] 检查 Docker 运行状态...
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Docker 未运行或未安装！请确保 Docker Desktop 已启动。
    pause
    exit /b 1
)
echo [成功] Docker 运行正常。

:: 2. 检查 .env 配置文件
echo [2/3] 检查环境变量配置...
if not exist ".env" (
    if exist ".env.docker.example" (
        echo [提示] 检测到未创建 .env 文件，正在从 .env.docker.example 自动创建...
        copy /y ".env.docker.example" ".env" >nul
        echo [重要] 已生成 .env 文件，请使用记事本打开 .env 并填入您的 LLM_API_KEY。
    ) else (
        echo [警告] 未找到 .env 配置文件。
    )
) else (
    echo [成功] .env 配置文件已就绪。
)

:: 3. 启动全套 Docker 容器服务
echo.
echo [3/3] 正在启动全栈 Docker 容器 (Milvus + Agent + Web UI)...
echo 首次启动会自动构建镜像，请稍候...
echo.

docker compose up --build -d

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 容器启动失败，请检查上方日志。
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo                🎉 服务全部拉起成功！
echo =====================================================================
echo  - Web 前端界面 : http://localhost:3000
echo  - Agent 后端 API: http://localhost:8000
echo  - Milvus 向量库 : localhost:19530
echo.
echo  常用命令提示：
echo   * 查看实时日志: docker compose logs -f
echo   * 停止所有服务: docker compose down
echo =====================================================================
echo.
pause
