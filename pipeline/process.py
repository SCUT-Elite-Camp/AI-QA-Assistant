"""
数据处理管线入口。

用法:
    python -m pipeline.process <folder_path>

示例:
    python -m pipeline.process data/raws/测试空间

流程:
    扫描文件夹 → 解析 PDF/DOCX → 切片 → 向量化 → 保存 JSON → 写入 Milvus → 构建 BM25 索引
"""

import os
from models.document import Document
from parsers.registry import parse_file, supported_extensions
from pipeline.chunker import chunk_text, chunk_from_blocks
from pipeline.embedder import embed_texts
from storage.document_store import save_document
from storage.milvus_store import MilvusStore


def _scan_folder(folder_path: str) -> list[str]:
    """扫描文件夹，返回所有支持的文件路径列表"""
    files: list[str] = []
    exts = supported_extensions()
    for root, _dirs, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in exts:
                files.append(os.path.join(root, fname))
    return files


def _document_to_json(doc: Document) -> dict:
    """将 Document 模型转为与 storage/document_store.py 兼容的 JSON dict"""
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "content": doc.content,
        "space": doc.space,
        "address": doc.address,
        "last_updated": doc.last_updated,
        "source_url": doc.source_url,
        "content_blocks": [
            {
                "block_type": cb.block_type.value,
                "level": cb.level,
                "text": cb.text,
                "rows": cb.rows,
                "headers": cb.headers,
                "bold": cb.bold,
                "italic": cb.italic,
            }
            for cb in doc.content_blocks
        ],
        "chunks": [
            {
                "index": ch.index,
                "text": ch.text,
                "chunk_id": ch.chunk_id,
            }
            for ch in doc.chunks
        ],
    }


def process_folder(
    folder_path: str,
    chunk_size: int = 500,
    overlap: int = 100,
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
) -> list[Document]:
    """
    处理文件夹中的所有 PDF/DOCX 文件。

    Args:
        folder_path: 包含待处理文件的文件夹路径
        chunk_size: 分块大小（字符数）
        overlap: 分块重叠大小（字符数）
        milvus_host: Milvus 服务地址
        milvus_port: Milvus 服务端口

    Returns:
        处理后的 Document 列表
    """
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        raise NotADirectoryError(f"路径不存在或不是文件夹: {folder_path}")

    files = _scan_folder(folder_path)
    if not files:
        print(f"未在 {folder_path} 中找到支持的文件（{supported_extensions()}）")
        return []

    print(f"找到 {len(files)} 个文件待处理")

    milvus = MilvusStore(host=milvus_host, port=milvus_port)
    documents: list[Document] = []

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] 处理: {file_path}")

        # 1. 解析文档
        doc = parse_file(file_path)
        print(f"  → 解析完成，全文 {len(doc.content)} 字符")

        # 2. 文本切片（优先使用块感知切片）
        if doc.content_blocks:
            chunks = chunk_from_blocks(doc.content_blocks, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
        else:
            chunks = chunk_text(doc.content, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
        doc.chunks = chunks
        print(f"  → 切片完成，共 {len(chunks)} 个分块")

        if not chunks:
            print(f"  ⚠ 跳过（无内容）")
            continue

        # 3. 向量化
        chunk_texts = [ch.text for ch in chunks]
        print(f"  → 正在向量化 {len(chunk_texts)} 个分块...")
        embeddings = embed_texts(chunk_texts)
        print(f"  → 向量化完成")

        # 4. 保存 JSON 到 data/documents/
        json_data = _document_to_json(doc)
        save_document(doc.doc_id, json_data)
        print(f"  → JSON 已保存: data/documents/{doc.doc_id}.json")

        # 5. 插入向量到 Milvus
        chunk_ids = [ch.chunk_id for ch in chunks]
        doc_ids = [doc.doc_id] * len(chunks)
        chunk_indices = [ch.index for ch in chunks]
        source_urls = [doc.source_url] * len(chunks)
        milvus.insert_chunks(
            embeddings=embeddings,
            chunk_ids=chunk_ids,
            chunk_texts=chunk_texts,
            doc_ids=doc_ids,
            chunk_indices=chunk_indices,
            source_urls=source_urls,
        )
        print(f"  → 向量已写入 Milvus")

        documents.append(doc)

    # 6. 全部完成后构建 BM25 索引
    print(f"\n构建 BM25 索引...")
    from retrieval.bm25_index import BM25Index
    bm25 = BM25Index()
    bm25.build_from_documents()
    bm25_index_path = BM25Index.default_index_path()
    bm25.save(bm25_index_path)
    print(f"  → BM25 索引已保存: {bm25_index_path}")

    print(f"\n处理完成！共 {len(documents)} 个文档")
    return documents


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="RAGent 数据处理管线：解析 PDF/DOCX → 切片 → 向量化 → 存储",
    )
    parser.add_argument("folder", help="包含待处理 PDF/DOCX 文件的文件夹路径")
    parser.add_argument("--chunk-size", type=int, default=500, help="分块大小（字符数，默认 500）")
    parser.add_argument("--overlap", type=int, default=100, help="分块重叠（字符数，默认 100）")
    parser.add_argument("--milvus-host", default="localhost", help="Milvus 服务地址")
    parser.add_argument("--milvus-port", default="19530", help="Milvus 服务端口")
    args = parser.parse_args()

    process_folder(
        args.folder,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
    )
