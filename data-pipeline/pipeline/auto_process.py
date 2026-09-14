import os
import sys
import json
from pathlib import Path

# ── 解析项目根目录并将所有子项目目录加入 sys.path ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "data-persistence"))
sys.path.insert(0, str(PROJECT_ROOT / "toolset"))

from models.document import Document
from parsers.registry import parse_file, supported_extensions
from pipeline.chunker import chunk_text, chunk_from_blocks
from pipeline.embedder import embed_texts
from pipeline.structure import build_document_sections
from pipeline.confluence_snapshot import deduplicate_confluence_paths
from retrieval.bm25_index import BM25Index
from retrieval.section_bm25_index import SectionBM25Index
from storage.document_store import save_document
from storage.milvus_store import MilvusStore

# 配置默认目录
RAWS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "raws"
DOCS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "documents"

def _scan_folder(folder_path: str) -> list[str]:
    """递归扫描文件夹，返回所有支持的文件绝对路径"""
    files: list[str] = []
    exts = supported_extensions()
    for root, _dirs, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in exts:
                files.append(os.path.abspath(os.path.join(root, fname)))
    return deduplicate_confluence_paths(files)

def get_new_or_modified_files(raw_files: list[str]) -> list[str]:
    """根据已经保存的文档 JSON 和文件修改时间，筛选出新增或修改的文件"""
    to_process = []
    for file_path in raw_files:
        abs_path = os.path.abspath(file_path)
        doc_id = Document.generate_doc_id(abs_path)
        json_path = DOCS_DIR / f"{doc_id}.json"
        
        # 1. 如果对应的 JSON 文件不存在，说明是全新增文件
        if not json_path.exists():
            to_process.append(file_path)
            continue
            
        # 2. 如果 JSON 文件存在，比对修改时间 last_updated
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                doc_data = json.load(f)
            stored_last_updated = doc_data.get("last_updated")
            current_last_updated = Document.generate_last_updated(abs_path)
            
            # 如果修改时间不一致，说明文件被更新了
            if stored_last_updated != current_last_updated:
                to_process.append(file_path)
        except Exception:
            # 如果读取 JSON 失败，当作新文件重新处理以保证数据完整性
            to_process.append(file_path)
            
    return to_process


def _index_document(
    doc: Document,
    *,
    chunk_size: int,
    overlap: int,
    evidence_milvus: MilvusStore,
    section_milvus: MilvusStore | None,
    has_milvus: bool,
) -> bool:
    if doc.content_blocks:
        chunks = chunk_from_blocks(
            doc.content_blocks, doc.doc_id, chunk_size=chunk_size, overlap=overlap,
        )
    else:
        chunks = chunk_text(doc.content, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
    doc.chunks = chunks
    doc.sections = build_document_sections(doc)
    print(f"  → 分块完成，共 {len(chunks)} 个分块、{len(doc.sections)} 个章节")
    if not chunks:
        print("  [Warning] 分块内容为空，跳过该文档")
        return False

    chunk_texts = [chunk.text for chunk in chunks]
    section_texts = [section.navigation_text for section in doc.sections if section.navigation_text]
    print(f"  → 正在生成 {len(chunk_texts)} 个 Evidence 向量")
    embeddings = embed_texts(chunk_texts)
    section_embeddings = embed_texts(section_texts) if has_milvus and section_texts else []

    if has_milvus:
        # Section and Evidence use different collections and ID namespaces.
        assert section_milvus is not None
        section_milvus.init_collection(dim=len(section_embeddings[0]))
        section_milvus.collection.delete(expr=f'doc_id == "{doc.doc_id}"')
        section_milvus.collection.flush()
        section_rows = [section for section in doc.sections if section.navigation_text]
        section_milvus.insert_chunks(
            embeddings=section_embeddings,
            chunk_ids=[section.id for section in section_rows],
            chunk_texts=[section.navigation_text for section in section_rows],
            doc_ids=[doc.doc_id] * len(section_rows),
            chunk_indices=list(range(len(section_rows))),
            source_urls=[doc.source_url] * len(section_rows),
            titles=[section.title for section in section_rows],
            spaces=[doc.space] * len(section_rows),
            doc_types=["section"] * len(section_rows),
            collection_name=section_milvus.collection_name,
        )
        evidence_milvus.init_collection(dim=len(embeddings[0]))
        evidence_milvus.collection.delete(expr=f'doc_id == "{doc.doc_id}"')
        evidence_milvus.collection.flush()
        evidence_milvus.insert_chunks(
            embeddings=embeddings,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
            chunk_texts=chunk_texts,
            doc_ids=[doc.doc_id] * len(chunks),
            chunk_indices=[chunk.index for chunk in chunks],
            source_urls=[doc.source_url] * len(chunks),
            titles=[doc.title] * len(chunks),
            spaces=[doc.space] * len(chunks),
            doc_types=[doc.doc_type] * len(chunks),
        )

    # The active JSON projection is switched only after all enabled indexes succeed.
    save_document(doc.doc_id, doc.model_dump(mode="json"))
    print(f"  → JSON 元数据已保存至: data-persistence/data/documents/{doc.doc_id}.json")
    return True

def auto_process_raws(
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
    chunk_size: int = 500,
    overlap: int = 100,
) -> None:
    """自动扫描新增/修改文件并进行增量入库"""
    # 确保必要目录存在
    os.makedirs(str(RAWS_DIR), exist_ok=True)
    os.makedirs(str(DOCS_DIR), exist_ok=True)
    
    print(f"==================================================")
    print(f" [Start] 启动一键自动增量解析入库脚本")
    print(f" 原始文件扫描目录: {RAWS_DIR}")
    print(f"==================================================")
    
    raw_files = _scan_folder(str(RAWS_DIR))
    if not raw_files:
        print(f" [Info] 未在 {RAWS_DIR} 下找到任何支持的原始文件（支持格式: {supported_extensions()}）。")
        print(f" [Tip] 请将需要解析的文件放入该目录中。")
        return
        
    print(f" [Scan] 共扫描到 {len(raw_files)} 个支持的文件")
    files_to_process = get_new_or_modified_files(raw_files)
    
    if not files_to_process:
        print(" [Finish] 所有文件均已是最新状态，无需处理！")
        return
        
    print(f" [Process] 检测到 {len(files_to_process)} 个待入库的新增或已修改文件:")
    for f in files_to_process:
        print(f"  - {f}")
        
    # 初始化 Milvus 连接并测试是否能够连接
    milvus = MilvusStore(host=milvus_host, port=milvus_port)
    has_milvus = False
    section_milvus: MilvusStore | None = None
    try:
        milvus.connect()
        section_collection = os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3")
        if section_collection.casefold() == milvus.collection_name.casefold():
            raise RuntimeError("SECTION_MILVUS_COLLECTION must differ from Evidence collection")
        section_milvus = MilvusStore(
            host=milvus_host, port=milvus_port, collection_name=section_collection,
        )
        section_milvus.connect()
        has_milvus = True
        print(" [Milvus] 成功连接到 Milvus 向量库")
    except Exception as e:
        print(f" [Warning] 无法连接到 Milvus 服务（{e}）。将跳过向量库写入，仅生成 JSON 元数据和 BM25 索引。")
        
    processed_count = 0
    
    for i, file_path in enumerate(files_to_process, 1):
        print(f"\n [Ingest] [{i}/{len(files_to_process)}] 正在处理: {file_path}")
        try:
            docs = parse_file(file_path)
            print(f"  → 解析完成，共 {len(docs)} 个文档")
            for doc in docs:
                if _index_document(
                    doc, chunk_size=chunk_size, overlap=overlap,
                    evidence_milvus=milvus, section_milvus=section_milvus,
                    has_milvus=has_milvus,
                ):
                    processed_count += 1
            
        except Exception as e:
            print(f"  [Error] 处理文件时发生错误: {file_path}，错误详情: {e}")
            
    # 6. 重建全量 BM25 关键词索引
    if processed_count > 0:
        print(f"\n [BM25] 正在重建全量 BM25 倒排索引...")
        bm25 = BM25Index()
        bm25.build_from_documents()
        bm25_index_path = BM25Index.default_index_path()
        bm25.save(bm25_index_path)
        print(f"  → BM25 索引已更新并保存至: {bm25_index_path}")
        section_bm25 = SectionBM25Index()
        section_bm25.build_from_documents(str(DOCS_DIR))
        section_bm25.save(SectionBM25Index.default_index_path())
        print("  → Section BM25 索引已更新")
        print(f"\n [Finish] 自动解析入库任务完成！成功入库 {processed_count} 个文档。")
    else:
        print("\n [Info] 未有任何新文档成功处理入库。")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="一键增量解析入库脚本，扫描 data-persistence/data/raws 下的新增/修改文件并处理入库。"
    )
    parser.add_argument("--chunk-size", type=int, default=500, help="分块大小（字符数，默认 500）")
    parser.add_argument("--overlap", type=int, default=100, help="分块重叠（字符数，默认 100）")
    parser.add_argument("--milvus-host", default="localhost", help="Milvus 服务地址")
    parser.add_argument("--milvus-port", default="19530", help="Milvus 服务端口")
    args = parser.parse_args()
    
    auto_process_raws(
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )
