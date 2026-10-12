import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "data-persistence"))
sys.path.insert(0, str(PROJECT_ROOT / "toolset"))


from models.document import Document
from parsers.registry import parse_file
from pipeline.auto_process import _index_document
from data_persistence.vector import MilvusStore
from retrieval.bm25_index import BM25Index

def process_specific_files(
    file_paths: list[str],
    chunk_size: int = 500,
    overlap: int = 100,
    milvus_host: str = "localhost",
    milvus_port: str = "19530"
) -> list[Document]:
    """
    仅针对传入的具体上传文件列表进行针对性解析、分块、向量化与入库。
    绝不进行全量目录扫描，提高上传效率。
    """
    print(f"==================================================")
    print(f" [Target Ingest] 针对性处理新增上传文件: {len(file_paths)} 个")
    print(f"==================================================")

    milvus = MilvusStore(host=milvus_host, port=milvus_port)
    has_milvus = False
    section_name = os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3")
    if section_name.casefold() == milvus.collection_name.casefold():
        raise RuntimeError("SECTION_MILVUS_COLLECTION must differ from Evidence collection")
    section_milvus = MilvusStore(
        host=milvus_host, port=milvus_port, collection_name=section_name,
    )
    try:
        milvus.connect()
        section_milvus.connect()
        has_milvus = True
        print(" [Milvus] Connected to Milvus vector store")
    except Exception as e:
        print(f" [Warning] Milvus unavailable ({e}), continuing without vector store")

    processed_docs: list[Document] = []

    for i, file_path in enumerate(file_paths, 1):
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            print(f"  [Warn] File not found: {abs_path}")
            continue

        print(f"\n [{i}/{len(file_paths)}] Processing uploaded file: {abs_path}")
        try:
            # 1. Parse uploaded document
            docs = parse_file(abs_path)
            doc_list = docs if isinstance(docs, list) else [docs]

            for doc in doc_list:
                if not doc.content or not doc.content.strip():
                    print(f"  [Skip] Empty document content for: {abs_path}")
                    continue

                if _index_document(
                    doc, chunk_size=chunk_size, overlap=overlap,
                    evidence_milvus=milvus, section_milvus=section_milvus,
                    has_milvus=has_milvus,
                ):
                    processed_docs.append(doc)

        except Exception as err:
            print(f"  [Error] Failed to process {abs_path}: {err}")

    # 6. Incrementally update BM25 index
    if processed_docs:
        print("\n [BM25] Updating BM25 inverted index...")
        bm25 = BM25Index()
        bm25.build_from_documents()
        bm25.save(BM25Index.default_index_path())
        print("  → BM25 index updated")

    print(f"\n [Finish] Targeted ingestion complete! Processed {len(processed_docs)} document(s).")
    return processed_docs

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Targeted document ingestion for uploaded files.")
    parser.add_argument("files", nargs="+", help="Specific uploaded file paths to process")
    args = parser.parse_args()

    process_specific_files(args.files)
