import json
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent

for path in (REPO_ROOT / "agent", BASE_DIR):
    path_text = str(path)
    if path_text in sys.path:
        sys.path.remove(path_text)
    sys.path.insert(0, path_text)

from agent.retrieval.retrieval_adapter import RetrievalAdapter
from agent.schemas.chat import ChatRequest
from agent.service.chat_service import ChatService
from tool_layer import SearchTool


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)

    tool = SearchTool(
        chunks_path=str(BASE_DIR / "data" / "chunks.jsonl"),
        documents_dir=str(BASE_DIR / "data" / "documents"),
    )
    agent_service = ChatService(retriever=RetrievalAdapter(retriever=tool))
    sample_count = len(getattr(tool.backend, "chunks", []))

    print("=" * 72)
    print("CP4 Demo: Toolset and Agent Layer Integration")
    print("=" * 72)
    print(f"Knowledge-base chunks: {sample_count}")

    response = agent_service.chat(ChatRequest(
        query="CP4_FRONTEND_CONTRACT: How should the Web layer display Agent answer citations status trace_id and retrieval fields?",
        top_k=5,
        retrieval_mode="hybrid",
    ))
    response_data = _to_dict(response)

    print("\n[Agent response]")
    print(json.dumps(response_data, ensure_ascii=False, indent=2))

    citations = response_data.get("citations", [])
    result_count = len(citations)

    print("\n[Acceptance]")
    print(f"- knowledge samples      : {sample_count}")
    print(f"- uses official Agent     : {agent_service.__class__.__module__.startswith('agent.')}")
    print(f"- status success          : {response_data.get('status') == 'success'}")
    print(f"- returns 3-5 chunks      : {3 <= result_count <= 5}")
    print(f"- citations are available : {bool(citations)}")
    print(f"- citation-ready fields   : {_has_citation_fields(citations)}")


def _has_citation_fields(citations) -> bool:
    required = {"citation_id", "title", "source_url", "doc_id", "chunk_id", "score"}
    return bool(citations) and all(required <= set(item) for item in citations)


def _to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


if __name__ == "__main__":
    main()
