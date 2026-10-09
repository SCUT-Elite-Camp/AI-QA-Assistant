"""The request schema must match the configured vector collection dimension."""
import os
import base64
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dimension", [384, 1024])
def test_search_schemas_follow_configured_dimension(tmp_path, dimension):
    environment = {**os.environ, "LOCAL_EMBEDDING_MODEL_DIM": str(dimension),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "ATTACHMENT_INTERNAL_SECRET": "test-only-secret",
        "ATTACHMENT_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"d" * 32).decode(),
        "ATTACHMENT_DATA_DIR": str(tmp_path), "ATTACHMENT_VECTOR_INDEX_ENABLED": "false",
        "ALLOW_FAKE_ATTACHMENT_SCANNER": "true", "ATTACHMENT_SCANNER": "disabled"}
    code = """
from pydantic import ValidationError
from attachment_service.app import SearchRequest, LibrarySearchRequest, LibraryScopedSearchRequest, LibraryOutlineRequest
import os
dim = int(os.environ['LOCAL_EMBEDDING_MODEL_DIM'])
for cls, data in [(SearchRequest, {'attachment_ids': []}), (LibrarySearchRequest, {'owner_id':'a','knowledge_base_id':'kb'}),
                  (LibraryScopedSearchRequest, {'owner_id':'a','knowledge_base_id':'kb','query':'q','section_ids':['section']}),
                  (LibraryOutlineRequest, {'owner_id':'a','knowledge_base_id':'kb','query':'q'})]:
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
