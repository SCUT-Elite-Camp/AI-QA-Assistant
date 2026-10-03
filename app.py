# app.py - Root Entrypoint for Local Backend Dev
import sys
from pathlib import Path
import importlib.util

root_dir = Path(__file__).resolve().parent
agent_dir = root_dir / "agent"

for folder in [
    agent_dir,
    root_dir,
    root_dir / "data-pipeline",
    root_dir / "data-persistence",
    root_dir / "toolset",
    root_dir / "shared_runtime",
]:
    folder_str = str(folder)
    if folder_str not in sys.path:
        sys.path.insert(0, folder_str)

spec = importlib.util.spec_from_file_location("agent_app_module", agent_dir / "app.py")
agent_app_module = importlib.util.module_from_spec(spec)
sys.modules["agent_app_module"] = agent_app_module
spec.loader.exec_module(agent_app_module)
app = agent_app_module.app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
