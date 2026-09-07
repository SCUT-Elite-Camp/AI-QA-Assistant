import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tool_layer import RetrievalError, RetrievalParameterError, SearchTool


class FakeBackend:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k, mode, filters=None):
        self.calls.append({"query": query, "top_k": top_k, "mode": mode, "filters": filters})
        return [
            {
                "doc_id": "doc_001",
                "chunk_index": 0,
                "text": "first chunk",
                "score": 3.0,
                "vector_score": 0.9,
                "bm25_score": 0.4,
            },
            {
                "doc_id": "doc_002",
                "chunk_index": 2,
                "chunk_text": "second chunk",
                "chunk_id": "custom_chunk",
                "title": "Inline title",
                "score": 1.0,
                "vector_score": 0.3,
                "bm25_score": 0.8,
                "source_url": "https://example.test/doc",
            },
        ]


class SearchToolTest(unittest.TestCase):
    def test_navigation_boosts_section_evidence_without_dropping_direct_reserve(self):
        class NavigationBackend:
            def search(self, query, top_k, mode, filters=None):
                return [
                    {"doc_id": "doc_1", "chunk_id": "c_direct", "chunk_index": 0,
                     "text": "general risk", "score": 1.0},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "doc_1.json").write_text(json.dumps({
                "doc_id": "doc_1", "active_version": True,
                "title": "Policy", "version_id": "ver-1",
                "chunks": [
                    {"chunk_id": "c_direct", "index": 0, "text": "general risk"},
                    {"chunk_id": "c_scoped", "index": 1, "text": "special control"},
                ],
                "sections": [{
                    "id": "s1", "title": "Special controls",
                    "section_path": ["Policy", "Special controls"],
                    "summary": "special control", "evidence_ids": ["c_scoped"],
                    "quality": "high", "level": 1,
                }],
            }), encoding="utf-8")
            tool = SearchTool(backend=NavigationBackend(), documents_dir=str(docs))
            with patch.dict("os.environ", {"HIERARCHICAL_NAVIGATION_ENABLED": "true"}):
                rows = tool.search(
                    "special control", top_k=2, navigation_mode="hybrid",
                )
        self.assertEqual(rows[0]["chunk_id"], "c_scoped")
        self.assertEqual({row["chunk_id"] for row in rows}, {"c_direct", "c_scoped"})

    def test_navigation_is_direct_when_feature_flag_is_disabled(self):
        tool = SearchTool(backend=FakeBackend())
        with patch.dict("os.environ", {"HIERARCHICAL_NAVIGATION_ENABLED": "false"}):
            rows = tool.search("query", top_k=2, navigation_mode="hierarchical")
        self.assertEqual(rows[0]["doc_id"], "doc_001")

    def test_accepts_all_cp1_modes(self):
        backend = FakeBackend()
        tool = SearchTool(backend=backend)

        tool.search("query", mode="vector")
        tool.search("query", mode="bm25")
        tool.search("query", mode="hybrid")

        self.assertEqual([call["mode"] for call in backend.calls], ["vector", "bm25", "hybrid"])

    def test_returns_agent_contract_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs_dir = Path(tmp)
            (docs_dir / "doc_001.json").write_text(
                json.dumps({"title": "Title doc_001", "source_url": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            tool = SearchTool(backend=FakeBackend(), documents_dir=str(docs_dir))
            results = tool.search("query", top_k=2, trace_id="trace-test")

        self.assertEqual(results[0]["doc_id"], "doc_001")
        self.assertEqual(results[0]["chunk_id"], "doc_001::chunk_0")
        self.assertEqual(results[0]["chunk_text"], "first chunk")
        self.assertEqual(results[0]["title"], "Title doc_001")
        self.assertEqual(results[0]["source_url"], "")
        self.assertTrue(0.0 <= results[0]["score"] <= 1.0)
        self.assertEqual(results[0]["vector_score"], 0.9)
        self.assertEqual(results[0]["bm25_score"], 0.4)

        self.assertEqual(results[1]["chunk_id"], "custom_chunk")
        self.assertEqual(results[1]["title"], "Inline title")
        self.assertEqual(results[1]["source_url"], "https://example.test/doc")

    def test_empty_retrieval_returns_empty_list(self):
        class EmptyBackend:
            def search(self, *args, **kwargs):
                return []

        self.assertEqual(SearchTool(backend=EmptyBackend()).search("unknown"), [])

    def test_validates_parameters(self):
        tool = SearchTool(backend=FakeBackend())

        with self.assertRaises(RetrievalParameterError):
            tool.search("")
        with self.assertRaises(RetrievalParameterError):
            tool.search("query", top_k=0)
        with self.assertRaises(RetrievalParameterError):
            tool.search("query", mode="dense")

    def test_wraps_backend_failures(self):
        class BrokenBackend:
            def search(self, *args, **kwargs):
                raise RuntimeError("backend down")

        with self.assertRaises(RetrievalError):
            SearchTool(backend=BrokenBackend()).search("query")

    def test_logs_trace_mode_latency_result_count_and_top_scores(self):
        tool = SearchTool(backend=FakeBackend())

        with self.assertLogs("tool_layer.search_tool", level="INFO") as logs:
            tool.search("query", top_k=2, mode="hybrid", trace_id="trace-log")

        line = "\n".join(logs.output)
        self.assertIn("trace_id=trace-log", line)
        self.assertIn("mode=hybrid", line)
        self.assertIn("results=2", line)
        self.assertIn("latency=", line)
        self.assertIn("top_scores=1.0000,0.0000", line)

    def test_min_score_filters_normalized_results(self):
        tool = SearchTool(backend=FakeBackend())
        results = tool.search("query", min_score=0.5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doc_id"], "doc_001")

if __name__ == "__main__":
    unittest.main()
