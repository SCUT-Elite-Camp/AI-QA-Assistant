#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "====================================================================="
echo "               AI-QA-Assistant One-Click Deployment"
echo "====================================================================="
echo ""

# Step 1: Check and auto-launch Docker if not running
echo "[1/4] Checking Docker daemon status..."
if ! docker info >/dev/null 2>&1; then
    echo "[INFO] Docker daemon is not active. Attempting to start Docker service..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open -a Docker || true
    elif command -v systemctl >/dev/null 2>&1; then
        sudo systemctl start docker || true
    fi

    echo "[INFO] Waiting for Docker daemon to initialize..."
    DOCKER_WAIT=0
    while ! docker info >/dev/null 2>&1; do
        sleep 3
        DOCKER_WAIT=$((DOCKER_WAIT + 3))
        if [ $DOCKER_WAIT -ge 90 ]; then
            echo "[ERROR] Docker daemon did not start in time. Please start Docker and retry."
            exit 1
        fi
        echo "       ... still initializing Docker (${DOCKER_WAIT}s / 90s)"
    done
fi
echo "[OK] Docker daemon is running and ready."

# Step 2: Check .env configuration file
echo ""
echo "[2/4] Checking environment configuration (.env)..."
if [ ! -f ".env" ]; then
    if [ -f ".env.docker.example" ]; then
        echo "[INFO] Generating .env from template .env.docker.example..."
        cp ".env.docker.example" ".env"
        echo "[OK] .env configuration file created."
    else
        echo "[WARNING] .env.docker.example not found."
    fi
else
    echo "[OK] .env configuration file exists."
fi

# Step 3: Build and start containers
echo ""
echo "[3/4] Launching Docker containers (Milvus + Agent + Web UI)..."
echo "Building images on first run, please wait..."
echo ""

docker compose up --build -d

# Step 4: Ready and open browser
echo ""
echo "[4/4] Opening Web Interface in your default browser..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:3000 || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:3000 || true
fi

echo ""
echo "====================================================================="
echo "               All Services Started Successfully!"
echo "====================================================================="
echo " - Web UI:       http://localhost:3000"
echo " - Agent API:    http://localhost:8000"
echo " - Milvus Store: localhost:19530"
echo ""
echo " Useful commands:"
echo "  * View live logs:  docker compose logs -f"
echo "  * Stop services:   docker compose down"
echo "====================================================================="
