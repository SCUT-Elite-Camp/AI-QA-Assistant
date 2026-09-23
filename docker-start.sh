#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "====================================================================="
echo "               AI-QA-Assistant Docker Full-Stack Deploy"
echo "====================================================================="
echo ""

# Step 1: Check Docker status
echo "[1/3] Checking Docker status..."
if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker is not running or not installed! Please start Docker service."
    exit 1
fi
echo "[OK] Docker is running."

# Step 2: Check .env configuration file
echo "[2/3] Checking environment configuration..."
if [ ! -f ".env" ]; then
    if [ -f ".env.docker.example" ]; then
        echo "[INFO] .env not found. Creating .env from .env.docker.example..."
        cp ".env.docker.example" ".env"
        echo "[IMPORTANT] Created .env. Please edit .env and set your LLM_API_KEY."
    else
        echo "[WARNING] .env file not found."
    fi
else
    echo "[OK] .env configuration file exists."
fi

# Step 3: Launch Docker containers
echo ""
echo "[3/3] Launching Docker containers (Milvus + Agent + Web UI)..."
echo "Building images on first run, please wait..."
echo ""

docker compose up --build -d

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
