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
from retrieval.bm25_index import BM25Index
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
    return files

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
    try:
        milvus.connect()
        has_milvus = True
        print(" [Milvus] 成功连接到 Milvus 向量库")
    except Exception as e:
        print(f" [Warning] 无法连接到 Milvus 服务（{e}）。将跳过向量库写入，仅生成 JSON 元数据和 BM25 索引。")
        
    processed_count = 0
    
    for i, file_path in enumerate(files_to_process, 1):
        print(f"\n [Ingest] [{i}/{len(files_to_process)}] 正在处理: {file_path}")
        try:
            # 1. 文档解析
            doc = parse_file(file_path)
            print(f"  → 解析完成，全文 {len(doc.content)} 字符")
            
            # 2. 智能切片（优先使用 ContentBlock，否则按普通文本切）
            if doc.content_blocks:
                chunks = chunk_from_blocks(doc.content_blocks, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
            else:
                chunks = chunk_text(doc.content, doc.doc_id, chunk_size=chunk_size, overlap=overlap)
            doc.chunks = chunks
            print(f"  → 分块完成，共 {len(chunks)} 个分块")
            
            if not chunks:
                print(f"  [Warning] 分块内容为空，跳过该文件")
                continue
                
            # 3. 文本向量化
            chunk_texts = [ch.text for ch in chunks]
            print(f"  → 正在对 {len(chunk_texts)} 个分块生成语义向量...")
            embeddings = embed_texts(chunk_texts)
            print(f"  → 向量生成完毕")
            
            # 4. 保存 JSON 元数据
            json_data = doc.model_dump(mode="json")
            save_document(doc.doc_id, json_data)
            print(f"  → JSON 元数据已保存至: data-persistence/data/documents/{doc.doc_id}.json")
            
            # 5. 写入向量数据到 Milvus（若可用）
            if has_milvus:
                dim = len(embeddings[0])
                milvus.init_collection(dim=dim)
                
                # 若文件为修改过的，先清理旧分块
                try:
                    delete_expr = f"doc_id == '{doc.doc_id}'"
                    milvus.collection.delete(expr=delete_expr)
                    print(f"  → 已清理旧向量分块 (doc_id: {doc.doc_id})")
                except Exception as de:
                    print(f"  [Warning] 清理旧向量分块失败或集合为空: {de}")
                    
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
                    source_urls=source_urls
                )
                print(f"  → 向量数据已成功写入 Milvus 向量库")
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
