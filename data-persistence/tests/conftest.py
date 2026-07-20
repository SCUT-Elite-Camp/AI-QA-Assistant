import sys
from pathlib import Path

# Add data-persistence folder to sys.path to allow importing storage package
data_persistence_dir = Path(__file__).resolve().parent.parent
if str(data_persistence_dir) not in sys.path:
    sys.path.insert(0, str(data_persistence_dir))
