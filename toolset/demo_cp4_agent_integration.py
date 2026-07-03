import json
import logging
import sys
from pathlib import Path

from agent_layer import SimpleRagAgent
from tool_layer import SearchTool


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)

    base_dir = Path(__file__).resolve().parent
    tool = SearchTool(
        chunks_path=str(base_dir / "data" / "chunks.jsonl"),
        documents_dir=str(base_dir / "data" / "documents"),
    )
    agent = SimpleRagAgent(search_tool=tool)

    print("=" * 72)
    print("CP4 Demo: Agent Integration and Final Acceptance")
    print("=" * 72)

    response = agent.answer(
        query="How does the Agent use SearchTool results to show citation sources?",
        top_k=5,
        mode="hybrid",
        trace_id="demo-cp4-001",
    )

    print("\n[Agent response]")
    print(json.dumps(response, ensure_ascii=False, indent=2))

    retrieval = response.get("retrieval", {})
    result_count = retrieval.get("result_count", 0)
    latency_ms = retrieval.get("latency_ms", 0)

    print("\n[Acceptance]")
    print(f"- status success          : {response.get('status') == 'success'}")
    print(f"- returns 3-5 chunks      : {3 <= result_count <= 5}")
    print(f"- top_k=5 latency < 1s    : {latency_ms < 1000} ({latency_ms}ms)")
    print(f"- citations are available : {bool(response.get('citations'))}")
    print(f"- citation-ready fields   : {_has_citation_fields(response.get('citations', []))}")


def _has_citation_fields(citations) -> bool:
    required = {"citation_id", "title", "source_url", "doc_id", "chunk_id", "score"}
    return bool(citations) and all(required <= set(item) for item in citations)


if __name__ == "__main__":
    main()
