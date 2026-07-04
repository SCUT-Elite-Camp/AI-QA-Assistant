import sys
from pathlib import Path

# Add agent and project root folders to sys.path
agent_dir = Path(__file__).resolve().parent.parent
project_root = agent_dir.parent

if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
