"""CLI bootstrap for sibling workspace packages; no models or backend connections."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
for _directory in (_root, _root / "data-persistence", _root / "toolset"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))
