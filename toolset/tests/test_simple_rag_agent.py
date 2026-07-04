import re
import unittest

from agent_layer import ExtractiveAnswerGenerator, SimpleRagAgent, build_prompt
from tool_layer import RetrievalError


class FakeSearchTool:
    def __init__(self, results=None, error=None):
        self.results = [] if results is None else results
        self.error = error
        self.calls = []

    def search(self, query, top_k=5, mode="hybrid", filters=None, min_score=0.0, trace_id=None):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "mode": mode,
                "filters": filters,
                "min_score": min_score,
                "trace_id": trace_id,
            }
        )
        if self.error:
            raise self.error
        return self.results


class FakeGenerator:
    def __init__(self, answer="Based on the retrieved context. [1]"):
        self.answer = answer
        self.calls = []

    def generate(self, prompt, query, contexts, trace_id):
        self.calls.append(
            {
                "prompt": prompt,
                "query": query,
                "contexts": contexts,
                "trace_id": trace_id,
            }
        )
        return self.answer


def sample_results(count=5):
    rows = []
    for index in range(count):
        rows.append(
            {
                "doc_id": f"doc_{index}",
                "chunk_id": f"doc_{index}::chunk_0",
                "chunk_index": 0,
                "chunk_text": f"Chunk {index} explains Agent integration and citations.",
                "title": f"Doc {index}",
                "score": 1.0 - index * 0.1,
                "vector_score": 0.5,
                "bm25_score": 0.5,
                "source_url": f"https://example.test/doc-{index}",
            }
        )
    return rows


class SimpleRagAgentTest(unittest.TestCase):
    def test_success_calls_search_once_and_returns_citations(self):
        search_tool = FakeSearchTool(results=sample_results(5))
        generator = FakeGenerator("Answer grounded in retrieved context. [1]")
        agent = SimpleRagAgent(search_tool=search_tool, answer_generator=generator)

        response = agent.answer("How are citations shown?", trace_id="trace-test")

        self.assertEqual(response["status"], "success")
        self.assertEqual(len(search_tool.calls), 1)
        self.assertEqual(search_tool.calls[0]["mode"], "hybrid")
        self.assertEqual(search_tool.calls[0]["top_k"], 5)
        self.assertEqual(len(generator.calls), 1)
        self.assertEqual(len(response["citations"]), 5)
        self.assertIn("[1]", response["answer"])
        self.assertTrue(_answer_refs_are_valid(response))
        self.assertLess(response["retrieval"]["latency_ms"], 1000)

    def test_invalid_query_does_not_call_search_or_generator(self):
        search_tool = FakeSearchTool(results=sample_results())
        generator = FakeGenerator()
        agent = SimpleRagAgent(search_tool=search_tool, answer_generator=generator)

        response = agent.answer("   ")

        self.assertEqual(response["status"], "invalid_query")
        self.assertEqual(search_tool.calls, [])
        self.assertEqual(generator.calls, [])

    def test_empty_retrieval_returns_no_relevant_context_without_generation(self):
        search_tool = FakeSearchTool(results=[])
        generator = FakeGenerator()
        agent = SimpleRagAgent(search_tool=search_tool, answer_generator=generator)

        response = agent.answer("What is outside the knowledge base?")

        self.assertEqual(response["status"], "no_relevant_context")
        self.assertEqual(response["citations"], [])
        self.assertEqual(generator.calls, [])
        self.assertIn("当前知识库没有足够信息", response["answer"])

    def test_retrieval_error_returns_clear_status(self):
        agent = SimpleRagAgent(search_tool=FakeSearchTool(error=RetrievalError("backend down")))

        response = agent.answer("trigger failure", trace_id="trace-error")

        self.assertEqual(response["status"], "retrieval_error")
        self.assertEqual(response["trace_id"], "trace-error")
        self.assertIn("backend down", response["message"])

    def test_generator_error_returns_clear_status_with_citations(self):
        class BrokenGenerator:
            def generate(self, *args, **kwargs):
                raise RuntimeError("model timeout")

        agent = SimpleRagAgent(search_tool=FakeSearchTool(results=sample_results(3)), answer_generator=BrokenGenerator())

        response = agent.answer("trigger generation failure")

        self.assertEqual(response["status"], "llm_error")
        self.assertEqual(len(response["citations"]), 3)
        self.assertIn("model timeout", response["message"])

    def test_invalid_generated_citation_is_rejected(self):
        agent = SimpleRagAgent(
            search_tool=FakeSearchTool(results=sample_results(2)),
            answer_generator=FakeGenerator("Invalid citation [3]"),
        )

        response = agent.answer("question")

        self.assertEqual(response["status"], "llm_error")
        self.assertIn("invalid citations", response["message"])

    def test_build_prompt_contains_guardrails_and_source_fields(self):
        prompt = build_prompt("What is CP4?", sample_results(1))

        self.assertIn("What is CP4?", prompt)
        self.assertIn("Do not invent facts", prompt)
        self.assertIn("doc_id: doc_0", prompt)
        self.assertIn("chunk_id: doc_0::chunk_0", prompt)
        self.assertIn("https://example.test/doc-0", prompt)
        self.assertIn("Chunk 0 explains Agent integration", prompt)

    def test_extractive_generator_adds_citation_markers(self):
        answer = ExtractiveAnswerGenerator().generate(
            prompt="prompt",
            query="query",
            contexts=sample_results(2),
            trace_id="trace",
        )

        self.assertIn("[1]", answer)
        self.assertIn("[2]", answer)


def _answer_refs_are_valid(response):
    allowed = {str(item["citation_id"]) for item in response["citations"]}
    refs = set(re.findall(r"\[(\d+)\]", response["answer"]))
    return bool(refs) and refs <= allowed


if __name__ == "__main__":
    unittest.main()
