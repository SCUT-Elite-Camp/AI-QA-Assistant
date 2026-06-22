import json
import tempfile
import unittest
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

    def test_min_score_filters_normalized_results(self):
        tool = SearchTool(backend=FakeBackend())
        results = tool.search("query", min_score=0.5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doc_id"], "doc_001")

    def test_local_backend_supports_cp2_modes_and_hybrid_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks_path = Path(tmp) / "chunks.jsonl"
            chunks = [
                {
                    "doc_id": "doc_vector",
                    "chunk_index": 0,
                    "chunk_text": "milvus semantic vector retrieval search",
                },
                {
                    "doc_id": "doc_bm25",
                    "chunk_index": 0,
                    "chunk_text": "bm25 keyword keyword exact search",
                },
                {
                    "doc_id": "doc_hybrid",
                    "chunk_index": 0,
                    "chunk_text": "milvus bm25 hybrid search",
                },
            ]
            chunks_path.write_text(
                "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks),
                encoding="utf-8",
            )

            tool = SearchTool(chunks_path=str(chunks_path))

            vector_results = tool.search("milvus vector search", mode="vector", top_k=3)
            bm25_results = tool.search("keyword exact search", mode="bm25", top_k=3)
            hybrid_results = tool.search("milvus bm25 hybrid search", mode="hybrid", top_k=3)

        self.assertGreaterEqual(len(vector_results), 1)
        self.assertGreaterEqual(len(bm25_results), 1)
        self.assertGreaterEqual(len(hybrid_results), 1)

        self.assertTrue(all("vector_score" in row and "bm25_score" in row for row in hybrid_results))

        hybrid_keys = [(row["doc_id"], row["chunk_index"]) for row in hybrid_results]
        self.assertEqual(len(hybrid_keys), len(set(hybrid_keys)))


if __name__ == "__main__":
    unittest.main()
