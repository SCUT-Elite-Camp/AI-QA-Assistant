import sys
from pathlib import Path

pipeline_dir = Path(__file__).resolve().parent.parent
project_root = pipeline_dir.parent

for folder in [str(pipeline_dir), str(project_root), str(project_root / 'data-persistence'), str(project_root / 'toolset'), str(project_root / 'agent')]:
    if folder not in sys.path:
        sys.path.insert(0, folder)

# Keep repository maintenance scripts ahead of the Agent scripts package.
if str(project_root) in sys.path:
    sys.path.remove(str(project_root))
sys.path.insert(0, str(project_root))
