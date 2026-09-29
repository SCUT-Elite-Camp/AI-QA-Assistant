import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "data-pipeline", ROOT / "data-persistence", ROOT / "toolset"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import retrieval.bm25_index as bm25_module  # noqa: E402


def test_bm25_indexes_plain_text_but_returns_markdown_display_text(monkeypatch, tmp_path):
    (tmp_path / "doc.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bm25_module, "load_document", lambda doc_id: {
        "chunks": [
            {
                "chunk_id": "plain-match",
                "index": 0,
                "text": "**展示文本一**",
                "index_text": "rarebanana",
            },
            {
                "chunk_id": "markdown-only-match",
                "index": 1,
                "text": "rarebanana",
                "index_text": "otherterm",
            },
            {
                "chunk_id": "unrelated",
                "index": 2,
                "text": "第三段",
                "index_text": "thirdterm",
            },
        ],
    })

    index = bm25_module.BM25Index()
    index.build_from_documents(docs_dir=str(tmp_path))

    result = index.search("rarebanana", top_k=1)[0]
    assert result["chunk_id"] == "plain-match"
    assert result["text"] == "**展示文本一**"
