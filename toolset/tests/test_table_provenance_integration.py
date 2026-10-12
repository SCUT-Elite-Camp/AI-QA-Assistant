import json
import math

import pytest

from tool_layer.search_tool import SearchTool, _page_regions_from_provenance


def document():
    return {
        "doc_id": "doc", "last_updated": "2", "content": "Current table",
        "chunks": [{
            "index": 0, "text": "Current table", "chunk_id": "c1", "chunk_type": "table",
            "table_id": "t1", "source_pages": [2, 3],
            "page_regions": [
                {"page_number": 2, "bbox": {"x0": 1, "y0": 2, "x1": 30, "y1": 40},
                 "table_ids": ["t1"], "sources": ["table"], "confidence": 0.9},
                {"page_number": 3, "bbox": [3, 4, 50, 60],
                 "table_ids": ["t1"], "sources": ["table"], "confidence": 0.9},
            ],
        }],
    }


def test_search_public_results_use_current_projection_geometry(tmp_path):
    current = document()
    (tmp_path / "doc.json").write_text(json.dumps(current), encoding="utf-8")
    tool = SearchTool(documents_dir=str(tmp_path))
    result = tool._normalize_results([{
        "doc_id": "doc", "chunk_index": 0, "text": "Current table",
        "score": 1, "table_id": "stale", "page_regions": [{"page_number": 99}],
    }], {"doc_ids": ["doc"]}, 0)[0]
    assert result["table_id"] == "t1"
    assert result["source_pages"] == [2, 3]
    assert result["page_regions"][0]["bbox"] == [1, 2, 30, 40]
    assert result["read_status"] == "original_excerpt_loaded"


def test_stale_text_cannot_acquire_current_table_provenance():
    result = SearchTool._read_provenance(document(), 0, "Previous table")
    assert result["read_status"] == "retrieval_hit"
    assert result["evidence_ref"] is None
    assert "page_regions" not in result


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_invalid_geometry_is_not_exposed(bad_value):
    assert _page_regions_from_provenance(0, "", json.dumps({
        "page_regions": [{"page_number": 1, "bbox": [bad_value, 0, 1, 1]}],
    })) == []
