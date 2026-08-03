import os
import sys
import time
import subprocess
import glob
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
        print("Error: Docker daemon is not running! Please start Docker first.")
        sys.exit(1)
        
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
    print(f"Error starting Docker containers: {e}")
    sys.exit(1)

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

print("\n=== [4/5] Configuring Agent Layer ===")
agent_env_path = project_root / "agent" / ".env"
env_content = (
    "DEFAULT_TOP_K=5\n"
    "MIN_RETRIEVAL_SCORE=0.0\n"
    "DEFAULT_RETRIEVAL_MODE=hybrid\n"
    "TOOL_LAYER_IMPORT=toolset.tool_layer\n"
    "TOOL_LAYER_CLASS=SearchTool\n"
    "RETRIEVAL_BACKEND=milvus\n"
    "LOG_LEVEL=INFO\n"
    "\n"
    "# Ollama 本地 llama3.1 配置\n"
    "LLM_API_BASE=http://127.0.0.1:11434/v1\n"
    "LLM_MODEL=llama3.1\n"
    "LLM_API_KEY=ollama\n"
    "LLM_TEMPERATURE=0.1\n"
    "LLM_MAX_TOKENS=2000\n"
    "LLM_TIMEOUT=60\n"
)
with open(agent_env_path, "w", encoding="utf-8") as f:
    f.write(env_content)
print("Configured agent/.env: LLM=llama3.1 via Ollama.")

# 5. Start Servers (Agent Backend & Web Frontend)
print("\n=== [5/5] Launching Servers ===")
python_path = str(project_root / ".venv" / "Scripts" / "python.exe")
if not os.path.exists(python_path):
    python_path = "python"

print("Starting Agent Backend service on port 8000...")
agent_env = os.environ.copy()
agent_env["PYTHONPATH"] = env_pythonpath
agent_proc = subprocess.Popen(
    [python_path, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=str(project_root / "agent"),
    env=agent_env,
    shell=False
)

# Wait for backend to be online and perform cold start preloading
print("Waiting for Agent Backend to start and preloading RAG models (cold start)...")
import urllib.request
import json

backend_url = "http://127.0.0.1:8000/health"
preloaded = False
start_time = time.time()

while time.time() - start_time < 60:
    try:
        # Check health
        with urllib.request.urlopen(backend_url, timeout=2) as response:
            if response.status == 200:
                print("Agent Backend is online! Triggering model preloading...")
                
                # Send preload query to warm up BGE and jieba
                chat_url = "http://127.0.0.1:8000/api/chat"
                data = json.dumps({
                    "query": "预热",
                    "top_k": 1,
                    "retrieval_mode": "hybrid"
                }).encode("utf-8")
                
                req = urllib.request.Request(
                    chat_url,
                    data=data,
                    headers={"Content-Type": "application/json"}
                )
                
                with urllib.request.urlopen(req, timeout=45) as chat_response:
                    if chat_response.status == 200:
                        print("Cold start completed successfully! RAG models fully preloaded.")
                        preloaded = True
                        break
    except Exception as e:
        # Wait and retry
        time.sleep(1.0)

if not preloaded:
    print("Warning: Failed to complete cold start preloading within timeout. Continuing anyway.")

print("Starting Web Frontend service...")
web_dir = project_root / "web"
# Use portable Node.js with full path
node_bin = str(project_root.parent / "nodejs" / "node.exe")
if not os.path.exists(node_bin):
    node_bin = "node"  # fallback to system node
web_env = os.environ.copy()
# Ensure node dir is in PATH for child processes
node_dir = str(project_root.parent / "nodejs" / "")
if os.path.exists(node_dir):
    web_env["PATH"] = node_dir + os.pathsep + web_env.get("PATH", "")
web_proc = subprocess.Popen(
    [node_bin, str(web_dir / "node_modules" / "vite" / "bin" / "vite.js")],
    cwd=str(web_dir),
    env=web_env,
    shell=False
)

print("\n" + "="*60)
print("ALL COMPONENTS LAUNCHED SUCCESSFULLY!")
print("- Agent API: http://127.0.0.1:8000")
print("- Web UI:    http://localhost:5173")
print("Press Ctrl+C in this terminal to shutdown all services.")
print("="*60 + "\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down services...")
    agent_proc.terminate()
    web_proc.terminate()
    print("All servers stopped. Goodbye!")
