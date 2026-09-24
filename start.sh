#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "====================================================================="
echo "               AI-QA-Assistant Local Startup Script"
echo "====================================================================="
echo ""

# 1. Python Environment
echo "[1/4] Checking Python backend environment..."
PYTHON_BIN=""
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
    echo "[OK] Found virtualenv: .venv"
elif [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
    echo "[OK] Found virtualenv: venv"
elif command -v python3 &> /dev/null; then
    echo "[INFO] Creating .venv using system python3..."
    python3 -m venv .venv
    PYTHON_BIN=".venv/bin/python"
    .venv/bin/pip install -r requirements.txt
else
    echo "[ERROR] Python 3 not found. Please install Python 3.10+."
    exit 1
fi

# 2. Frontend Environment
echo ""
echo "[2/4] Checking frontend environment..."
PKG_MGR="pnpm"
if ! command -v pnpm &> /dev/null; then
    if command -v npm &> /dev/null; then
        PKG_MGR="npm"
    else
        echo "[ERROR] Node.js / pnpm / npm not found. Please install Node.js."
        exit 1
    fi
fi
echo "[OK] Using package manager: $PKG_MGR"

if [ ! -d "frontend/node_modules" ]; then
    echo "[INFO] Installing frontend dependencies..."
    cd frontend && $PKG_MGR install && cd ..
fi

# 3. Start Backend & Frontend
echo ""
echo "[3/4] Launching Backend & Frontend services..."
$PYTHON_BIN -m app &
BACKEND_PID=$!
echo "[OK] Backend started (PID: $BACKEND_PID)"

cd frontend
$PKG_MGR run dev &
FRONTEND_PID=$!
cd ..
echo "[OK] Frontend started (PID: $FRONTEND_PID)"

# 4. Open Browser
echo ""
echo "[4/4] Opening browser..."
sleep 3
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:3000
elif command -v open &> /dev/null; then
    open http://localhost:3000
fi

echo ""
echo "====================================================================="
echo "               All Services Running!"
echo "====================================================================="
echo " - Frontend: http://localhost:3000"
echo " - Backend:  http://localhost:8000/docs"
echo " Press Ctrl+C to terminate all services."
echo "====================================================================="

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM EXIT
wait
