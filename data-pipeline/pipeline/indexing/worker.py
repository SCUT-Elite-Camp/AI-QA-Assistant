"""Internal stdin vector worker, independent of any source type."""
import json
import sys
from pathlib import Path
from models.document import Document
from pipeline.indexing.vectors import index_document_vectors


def main() -> int:
    """Internal stdin protocol shared by every document source."""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "data-persistence"))
    try:
        request = json.load(sys.stdin)
        document = Document.model_validate(request["document"])
        from data_persistence.vector import MilvusStore
        from pipeline.indexing.embedder import embed_texts
        store = MilvusStore(
            host=request["host"], port=request["port"], collection_name=request["collection"],
        )
        index_document_vectors(document, store, embed=embed_texts)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
