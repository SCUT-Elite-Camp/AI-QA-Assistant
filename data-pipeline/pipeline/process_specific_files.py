import os
import sys
import json
from pathlib import Path

# Force offline mode for Hugging Face
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["DISABLE_SYMLINKS_WARNING"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "data-persistence"))
sys.path.insert(0, str(PROJECT_ROOT / "toolset"))

os.environ["LOCAL_EMBEDDING_MODEL_PATH"] = str(PROJECT_ROOT / "data-persistence" / "models" / "bge-small-en-v1.5")

from models.document import Document
from parsers.registry import parse_file
from pipeline.chunker import chunk_text, chunk_from_blocks
from pipeline.embedder import embed_texts
from storage.document_store import save_document
from storage.milvus_store import MilvusStore
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
    try:
        milvus.connect()
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

                # 2. Chunking
                if doc.content_blocks:
                    chunks = chunk_from_blocks(doc.content_blocks, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
                else:
                    chunks = chunk_text(doc.content, doc.doc_id, chunk_size=chunk_size, overlap=overlap)

                doc.chunks = chunks
                if not chunks:
                    continue

                # 3. Vectorization with local BGE
                chunk_texts = [ch.text for ch in chunks]
                print(f"  → Generating embeddings for {len(chunk_texts)} chunks...")
                embeddings = embed_texts(chunk_texts)

                # 4. Save JSON metadata to data-persistence/data/documents/
                json_data = doc.model_dump(mode="json")
                save_document(doc.doc_id, json_data)
                print(f"  → Metadata JSON saved: {doc.doc_id}.json")

                # 5. Write vectors to Milvus
                if has_milvus:
                    dim = len(embeddings[0])
                    milvus.init_collection(collection_name="doc_chunks", dim=dim)

                    # Clear existing chunks for doc_id if re-uploading
                    try:
                        milvus.collection.delete(expr=f"doc_id == '{doc.doc_id}'")
                    except Exception:
                        pass

                    chunk_ids = [ch.chunk_id for ch in chunks]
                    doc_ids = [doc.doc_id] * len(chunks)
                    chunk_indices = [ch.index for ch in chunks]
                    source_urls = [doc.source_url or os.path.basename(abs_path)] * len(chunks)
                    titles = [doc.title] * len(chunks)
                    spaces = [doc.space] * len(chunks)
                    doc_types = [doc.doc_type] * len(chunks)

                    milvus.insert_chunks(
                        embeddings=embeddings,
                        chunk_ids=chunk_ids,
                        chunk_texts=chunk_texts,
                        doc_ids=doc_ids,
                        chunk_indices=chunk_indices,
                        source_urls=source_urls,
                        titles=titles,
                        spaces=spaces,
                        doc_types=doc_types,
                    )
                    print(f"  → Successfully wrote {len(chunks)} chunks to Milvus")

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
