"""The request schema must match the configured vector collection dimension."""
import os
import base64
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dimension", [384, 1024])
def test_search_schemas_follow_configured_dimension(tmp_path, dimension):
    repo_root = Path(__file__).resolve().parents[3]
    environment = {**os.environ, "LOCAL_EMBEDDING_MODEL_DIM": str(dimension),
        "PYTHONPATH": os.pathsep.join(str(path) for path in (repo_root / 'agent', repo_root / 'toolset', repo_root / 'data-pipeline', repo_root / 'data-persistence', repo_root)),
        "ATTACHMENT_INTERNAL_SECRET": "test-only-secret",
        "ATTACHMENT_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"d" * 32).decode(),
        "ATTACHMENT_DATA_DIR": str(tmp_path), "ATTACHMENT_VECTOR_INDEX_ENABLED": "false"}
    code = """
from pydantic import ValidationError
from agent.api.private_files import SearchRequest, LibrarySearchRequest
import os
dim = int(os.environ['LOCAL_EMBEDDING_MODEL_DIM'])
for cls, data in [(SearchRequest, {'attachment_ids': []}), (LibrarySearchRequest, {'owner_id':'a','knowledge_base_id':'kb'})]:
    cls(**data, query_vector=[0.1] * dim)
    try:
        cls(**data, query_vector=[0.1] * (dim + 1))
    except ValidationError:
        pass
    else:
        raise AssertionError('mismatched_dimension_accepted')
"""
    result = subprocess.run([sys.executable, "-c", code], env=environment, text=True, capture_output=True,
        cwd=Path(__file__).resolve().parents[1], timeout=30)
    assert result.returncode == 0, result.stderr
