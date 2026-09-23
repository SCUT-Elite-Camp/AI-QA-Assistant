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
from pipeline.auto_process import _index_document
from retrieval.bm25_index import BM25Index
from retrieval.section_bm25_index import SectionBM25Index
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
    section_collection = os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3")
    if section_collection.casefold() == milvus.collection_name.casefold():
        raise RuntimeError("SECTION_MILVUS_COLLECTION must differ from Evidence collection")
    section_milvus = MilvusStore(
        host=milvus_host, port=milvus_port, collection_name=section_collection,
    )
    milvus.connect()
    section_milvus.connect()
    documents: list[Document] = []

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] 处理: {file_path}")
        try:
            # 1. 解析文档（HtmlParser 可能返回多个文档：主文档 + 附件文档）
            docs = parse_file(file_path)
            total_chars = sum(len(d.content) for d in docs)
            print(f"  → 解析完成，全文 {total_chars} 字符，{len(docs)} 个文档")

            for doc in docs:
                if _index_document(
                    doc, chunk_size=chunk_size, overlap=overlap,
                    evidence_milvus=milvus, section_milvus=section_milvus,
                    has_milvus=True,
                ):
                    documents.append(doc)
        except Exception as e:
            print(f"  [FAIL] 处理文件时出错: {file_path}，错误: {e}")

    # 6. 全部完成后构建 BM25 索引
    print(f"\n构建 BM25 索引...")
    bm25 = BM25Index()
    bm25.build_from_documents()
    bm25_index_path = BM25Index.default_index_path()
    bm25.save(bm25_index_path)
    print(f"  → BM25 索引已保存: {bm25_index_path}")
    section_bm25 = SectionBM25Index()
    section_bm25.build_from_documents()
    section_bm25.save(SectionBM25Index.default_index_path())
    print(f"  → Section BM25 索引已保存: {SectionBM25Index.default_index_path()}")

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
