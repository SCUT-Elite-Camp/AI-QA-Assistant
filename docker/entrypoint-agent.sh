#!/usr/bin/env bash
set -e

echo "=== [Agent Container] Starting Initialization ==="

# 1. Ensure local embedding model weights exist (auto-download if missing)
echo "[Agent Container] Checking embedding model weights..."
python /app/scripts/ensure_models.py "${LOCAL_EMBEDDING_MODEL_PATH:-/app/data-persistence/models/bge-small-en-v1.5}"

# 2. Check and initialize document database if empty
DOCS_COUNT=$(find /app/data-persistence/data/documents -name "*.json" 2>/dev/null | wc -l)
if [ "$DOCS_COUNT" -eq 0 ] && [ -d "/app/data-persistence/data/raws" ]; then
    echo "[Agent Container] No processed documents found. Running initial document processing pipeline..."
    python -m pipeline.auto_process || echo "[Agent Container] Pipeline completed or skipped."
fi

echo "=== [Agent Container] Launching FastAPI Backend (Port 8000) ==="
exec python -m uvicorn app:app --host 0.0.0.0 --port 8000
