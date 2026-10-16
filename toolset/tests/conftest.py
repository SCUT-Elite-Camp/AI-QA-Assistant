import sys
import pytest
from pathlib import Path

# Add toolset folder to sys.path to allow importing tool_layer and agent_layer packages
toolset_dir = Path(__file__).resolve().parent.parent
if str(toolset_dir) not in sys.path:
    sys.path.insert(0, str(toolset_dir))
for folder in (toolset_dir.parent, toolset_dir.parent / "data-pipeline", toolset_dir.parent / "data-persistence", toolset_dir.parent / "agent"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


@pytest.fixture(autouse=True)
def isolated_reranker(monkeypatch):
    # Legacy unit tests never run installed production model weights.
    # Reranker-specific tests explicitly enable it and inject a predictor.
    monkeypatch.setenv('RERANK_ENABLED', 'false')
