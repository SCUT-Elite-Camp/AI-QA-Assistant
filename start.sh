#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "====================================================================="
echo "               AI-QA-Assistant Local Startup Script"
echo "====================================================================="
echo ""

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    trap - EXIT INT TERM
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [ -n "$pid" ]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

probe_url() {
    "$PYTHON_BIN" -c '
import json
import sys
from urllib.request import urlopen

url, readiness = sys.argv[1], sys.argv[2] == "ready"
try:
    with urlopen(url, timeout=1) as response:
        body = response.read() if readiness else b""
except Exception:
    print("unavailable")
else:
    if readiness:
        try:
            print(json.loads(body).get("status", "unknown"))
        except (ValueError, AttributeError):
            print("unknown")
    else:
        print("ready")
' "$1" "$2" 2>/dev/null || printf 'unavailable'
}

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

# 4. Wait for truthful service readiness, then open the browser
echo ""
echo "[4/4] Waiting for frontend and Agent readiness (up to 60 seconds)..."
FRONTEND_STATE="unavailable"
AGENT_STATE="unavailable"
STARTUP_STARTED_AT=$SECONDS
while (( SECONDS - STARTUP_STARTED_AT < 60 )); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[ERROR] Agent process exited before becoming ready."
        exit 1
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "[ERROR] Frontend process exited before becoming ready."
        exit 1
    fi

    FRONTEND_STATE="$(probe_url http://127.0.0.1:3000/ live)"
    AGENT_STATE="$(probe_url http://127.0.0.1:8000/ready ready)"
    if [ "$FRONTEND_STATE" = "ready" ] && [ "$AGENT_STATE" = "ready" ]; then
        break
    fi
    if [ "$FRONTEND_STATE" = "ready" ] && [ "$AGENT_STATE" = "degraded" ]; then
        break
    fi
    sleep 2
done

echo "[INFO] Frontend: $FRONTEND_STATE; Agent /ready: $AGENT_STATE"
if [ "$FRONTEND_STATE" = "ready" ]; then
    echo "[4/4] Opening browser..."
    if command -v xdg-open &> /dev/null; then
        if ! xdg-open http://localhost:3000; then
            echo "[WARN] Could not open a browser automatically. Visit http://localhost:3000."
        fi
    elif command -v open &> /dev/null; then
        if ! open http://localhost:3000; then
            echo "[WARN] Could not open a browser automatically. Visit http://localhost:3000."
        fi
    else
        echo "[INFO] No browser opener found. Visit http://localhost:3000."
    fi
else
    echo "[WARN] Frontend did not respond within 60 seconds; check its terminal output."
fi

echo ""
echo "====================================================================="
if [ "$FRONTEND_STATE" = "ready" ] && [ "$AGENT_STATE" = "ready" ]; then
    echo "               All Services Ready!"
elif [ "$FRONTEND_STATE" = "ready" ] && [ "$AGENT_STATE" = "degraded" ]; then
    echo "               Frontend Ready; Agent Degraded"
else
    echo "               Startup Timed Out; Check Service Logs"
fi
echo "====================================================================="
echo " - Frontend: http://localhost:3000"
echo " - Backend:  http://localhost:8000/docs"
echo " Press Ctrl+C to terminate all services."
echo "====================================================================="

while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[ERROR] Agent process exited; stopping the frontend."
        exit 1
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "[ERROR] Frontend process exited; stopping the Agent."
        exit 1
    fi
    sleep 2
done
