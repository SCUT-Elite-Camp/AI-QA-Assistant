import os
import sys
import time
import signal
import subprocess
import glob
import threading
from pathlib import Path


# Resolve project root
project_root = Path(__file__).resolve().parent
os.chdir(str(project_root))

# Standard paths for PYTHONPATH
python_paths = [
    str(project_root),
    str(project_root / "data-pipeline"),
    str(project_root / "data-persistence"),
    str(project_root / "toolset")
]
env_pythonpath = os.path.pathsep.join(python_paths)

def run_command(cmd, cwd=None, env=None, check=True, stdout=None, stderr=None):
    """Utility to run shell command and check exit code"""
    print(f"Executing: {' '.join(cmd) if isinstance(cmd, list) else cmd} (Cwd: {cwd or '.'})")
    res = subprocess.run(cmd, cwd=cwd, env=env, shell=False, check=check, stdout=stdout, stderr=stderr)
    return res

def cleanup_port(port: int):
    """Kill any process listening on the given port."""
    try:
        import urllib.request
        # Try a soft ping first — if nothing responds, skip
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
        except Exception:
            return  # Nothing on this port, good to go

        # Something is running — kill it
        if os.name == 'nt':
            # Windows
            result = subprocess.run(
                f'netstat -ano | findstr ":{port}"',
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid], shell=False,
                                   capture_output=True, timeout=5)
                    print(f"  Killed existing process on port {port} (PID {pid})")
        else:
            # macOS / Linux
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            for pid in result.stdout.strip().splitlines():
                if pid:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"  Killed existing process on port {port} (PID {pid})")
    except Exception as e:
        print(f"  Warning: could not clean port {port}: {e}")


# 1. Check and install dependencies
print("\n=== [1/5] Checking and Installing Dependencies ===")
pip_path = str(project_root / ".venv" / "Scripts" / "pip.exe")
if not os.path.exists(pip_path):
    pip_path = "pip"

try:
    run_command([pip_path, "install", "-r", "requirements.txt", "-i", "https://mirrors.aliyun.com/pypi/simple/"])
    print("Dependencies are up to date.")
except Exception as e:
    print(f"Warning: Failed to verify dependencies: {e}")

# 2. Start Milvus Container
print("\n=== [2/5] Checking Milvus Container ===")
try:
    # Check if docker is running
    res = subprocess.run(["docker", "ps"], shell=False, capture_output=True, text=True, errors="ignore")
    if res.returncode != 0:
        print("Warning: Docker daemon is not running! Milvus will be unavailable.")
        print("  (Search functionality will fall back to BM25 if configured.)")
    else:
        # Check if Milvus container is running
        if "milvus-standalone" not in res.stdout:
            print("Milvus standalone is not running. Starting Docker Compose...")
            compose_dir = project_root / "data-persistence"
            run_command(["docker", "compose", "up", "-d"], cwd=str(compose_dir))

            # Wait for Milvus to be ready
            print("Waiting for Milvus container to initialize (approx 10s)...")
            time.sleep(10)
        else:
            print("Milvus container is already running.")
except Exception as e:
    print(f"Warning: Error checking Docker containers: {e}")
    print("  (Continuing without Milvus. BM25 fallback will be used.)")

# 3. Check and process raws via data-pipeline
print("\n=== [3/5] Checking Document Pipeline ===")
documents_dir = project_root / "data-persistence" / "data" / "documents"
json_docs = glob.glob(str(documents_dir / "*.json"))
json_docs = [f for f in json_docs if not f.endswith(".gitkeep")]

if not json_docs:
    print("No unified JSON documents detected in data-persistence/data/documents/.")
    raws_dir = str(project_root / "data-persistence" / "data" / "raws" / "测试数据")
    print(f"Starting data-pipeline to process raw files in {raws_dir}...")
    python_path = str(project_root / ".venv" / "Scripts" / "python.exe")
    if not os.path.exists(python_path):
        python_path = "python"

    env = os.environ.copy()
    env["PYTHONPATH"] = env_pythonpath

    # Run the pipeline processing script
    run_command(
        [python_path, "-m", "pipeline.process", raws_dir],
        env=env
    )
    print("Data-pipeline finished processing raw files. Documents are stored and indexed!")
else:
    print(f"Detected {len(json_docs)} unified documents. Skipping pipeline processing.")

# 4. Configure Agent .env (preserve existing API key if env var not set)
print("\n=== [4/5] Configuring Agent Layer ===")
agent_env_path = project_root / "agent" / ".env"

# Read existing agent .env to preserve values not set in environment
existing_agent_env = {}
if agent_env_path.exists():
    for line in agent_env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            existing_agent_env[k.strip()] = v.strip()

# Also load root .env as fallback for API key
root_env_path = project_root / ".env"
root_env_vars = {}
if root_env_path.exists():
    for line in root_env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            root_env_vars[k.strip()] = v.strip()

def get_env(key: str, default: str = "") -> str:
    """Get env var with fallback: process env > existing agent .env > root .env > default."""
    return os.getenv(key) or existing_agent_env.get(key) or root_env_vars.get(key) or default

api_key = get_env("LLM_API_KEY", "")
if not api_key:
    print("WARNING: LLM_API_KEY is not set! LLM calls will fail.")
    print("  Set it in .env file or export LLM_API_KEY in your shell.")

env_content = (
    "DEFAULT_TOP_K=5\n"
    "MIN_RETRIEVAL_SCORE=0.0\n"
    "DEFAULT_RETRIEVAL_MODE=hybrid\n"
    "TOOL_LAYER_IMPORT=toolset.tool_layer\n"
    "TOOL_LAYER_CLASS=SearchTool\n"
    "RETRIEVAL_BACKEND=milvus\n"
    "LOG_LEVEL=INFO\n"
    "\n"
    "# LongCat API 配置\n"
    "LLM_API_BASE=https://api.longcat.chat/openai/v1\n"
    "LLM_MODEL=LongCat-2.0\n"
    f"LLM_API_KEY={api_key}\n"
    "LLM_TEMPERATURE=0.1\n"
    "LLM_MAX_TOKENS=2000\n"
    "LLM_TIMEOUT=60\n"
)
with open(agent_env_path, "w", encoding="utf-8") as f:
    f.write(env_content)
print(f"Configured agent/.env: LLM=LongCat-2.0 via LongCat API (key={'set' if api_key else 'EMPTY!'}).")


# 5. Start Servers (Agent Backend & Web Frontend)
print("\n=== [5/5] Launching Servers ===")
python_path = str(project_root / ".venv" / "Scripts" / "python.exe")
if not os.path.exists(python_path):
    python_path = "python"


# --- 5a. Clean up any leftover process on port 8000 ---
cleanup_port(8000)

# --- 5b. Start Agent Backend ---
print("Starting Agent Backend service on port 8000...")
agent_env = os.environ.copy()
agent_env["PYTHONPATH"] = env_pythonpath
agent_log = open(project_root / "agent" / "agent_stdout.log", "w", encoding="utf-8")
agent_err = open(project_root / "agent" / "agent_stderr.log", "w", encoding="utf-8")

agent_proc = subprocess.Popen(
    [python_path, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000",
     "--log-level", "info"],
    cwd=str(project_root / "agent"),
    env=agent_env,
    stdout=agent_log,
    stderr=agent_err,
    shell=False
)

# --- 5c. Wait for backend to be healthy (up to 60 seconds) ---
print("Waiting for Agent Backend to become healthy...")
import urllib.request
backend_ready = False
start_time = time.time()
while time.time() - start_time < 60:
    if agent_proc.poll() is not None:
        # Process died
        agent_err.flush()
        with open(project_root / "agent" / "agent_stderr.log", "r", encoding="utf-8") as f:
            err_text = f.read().strip()
        print(f"ERROR: Agent Backend process exited prematurely (code={agent_proc.returncode})!")
        if err_text:
            print(f"  stderr: {err_text[:1000]}")
        break
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as resp:
            if resp.status == 200:
                backend_ready = True
                print(f"  Agent Backend is healthy (took {time.time() - start_time:.1f}s)")
                break
    except Exception:
        pass
    time.sleep(1.0)

if not backend_ready and agent_proc.poll() is None:
    print("  Agent Backend process is running but not responding to health checks yet.")
    print("  (Will continue startup — the backend may need more time.)")


# --- 5d. Start Web Frontend ---
print("Starting Web Frontend service...")
web_dir = project_root / "web"
web_env = os.environ.copy()
web_env["SESSION_SECRET"] = "a_very_secret_key_123456_for_qa_assistant"
web_proc = subprocess.Popen(
    ["node", str(web_dir / "node_modules" / "vite" / "bin" / "vite.js"), "--host", "0.0.0.0", "--port", "3000"],
    cwd=str(web_dir),
    env=web_env,
    shell=False
)


# --- 5e. Background preload (RAG warmup) ---
def preload_in_background():
    backend_url = "http://127.0.0.1:8000/health"
    start_time = time.time()
    while time.time() - start_time < 30:
        try:
            with urllib.request.urlopen(backend_url, timeout=2) as response:
                if response.status == 200:
                    chat_url = "http://127.0.0.1:8000/api/chat"
                    data = json.dumps({"query": "预热", "top_k": 1, "retrieval_mode": "hybrid"}).encode("utf-8")
                    req = urllib.request.Request(chat_url, data=data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=30) as chat_response:
                        if chat_response.status == 200:
                            print("RAG models preloaded successfully in background.")
                            break
        except Exception:
            time.sleep(1.0)
    else:
        print("(Background RAG preload skipped — backend not ready in time)")

import json
threading.Thread(target=preload_in_background, daemon=True).start()



print("\n" + "="*60)
print("ALL COMPONENTS LAUNCHED SUCCESSFULLY!")
print("- Agent API: http://127.0.0.1:8000")
print("- Web UI:    http://localhost:3000")
print("Press Ctrl+C in this terminal to shutdown all services.")
print("="*60 + "\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down services...")
    agent_proc.terminate()
    web_proc.terminate()
    agent_log.close()
    agent_err.close()
    print("All servers stopped. Goodbye!")