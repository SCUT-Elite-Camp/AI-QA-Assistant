#!/usr/bin/env bash
set -e

echo "=== [Agent Container] Starting Initialization ==="

# 1. 确保嵌入模型权重存在（不存在时自动从 ModelScope / HF 镜像下载）
echo "[Agent Container] 检查本地嵌入模型权重..."
python /app/scripts/ensure_models.py "${LOCAL_EMBEDDING_MODEL_PATH:-/app/data-persistence/models/bge-small-en-v1.5}"

# 2. 检查并初始化文档库与索引（若 documents 目录为空且存在 raws 测试数据，则自动执行初始流水线）
DOCS_COUNT=$(find /app/data-persistence/data/documents -name "*.json" 2>/dev/null | wc -l)
if [ "$DOCS_COUNT" -eq 0 ] && [ -d "/app/data-persistence/data/raws" ]; then
    echo "[Agent Container] 检测到 documents 目录无文档，开始自动处理 raws 目录文件..."
    python -m pipeline.auto_process || echo "[Agent Container] 文档预处理完成或跳过。"
fi

echo "=== [Agent Container] 启动 FastAPI 服务 (Port 8000) ==="
exec python -m uvicorn app:app --host 0.0.0.0 --port 8000
