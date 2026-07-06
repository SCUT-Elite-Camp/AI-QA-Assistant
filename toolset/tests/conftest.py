import sys
from pathlib import Path

# Add toolset folder to sys.path to allow importing tool_layer and agent_layer packages
toolset_dir = Path(__file__).resolve().parent.parent
if str(toolset_dir) not in sys.path:
    sys.path.insert(0, str(toolset_dir))
