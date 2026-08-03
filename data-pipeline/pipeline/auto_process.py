"""
自动增量处理脚本 (A-MEM 管线)。

扫描 data-persistence/data/raws 下的新增/修改文件，
通过 A-MEM 全管线: 语义分割 → 知识卡片 → 图谱链接 → 入库。
"""

import asyncio
import concurrent.futures
import json
import os
import sys
from pathlib import Path

# ── sys.path ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(PROJECT_ROOT),
    str(PROJECT_ROOT / "data-pipeline"),
    str(PROJECT_ROOT / "data-persistence"),
    str(PROJECT_ROOT / "toolset"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from models.document import Document
from parsers.registry import parse_file, supported_extensions
from pipeline.embedder import embed_texts
from pipeline.quality import check_document_quality, should_skip
from retrieval.bm25_index import BM25Index
from storage.document_store import save_document
from storage.milvus_store import MilvusStore

# 配置默认目录
RAWS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "raws"
DOCS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "documents"


def _run_async(coro, timeout: int = 60):
    """安全地在同步代码中运行异步协程"""
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result(timeout=timeout)
    except RuntimeError:
        return asyncio.run(coro)


def _scan_folder(folder_path: str) -> list[str]:
    files: list[str] = []
    exts = supported_extensions()
    for root, _dirs, filenames in os.walk(folder_path):
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in exts:
                files.append(os.path.abspath(os.path.join(root, fname)))
    return files


def get_new_or_modified_files(raw_files: list[str]) -> list[str]:
    to_process = []
    for file_path in raw_files:
        abs_path = os.path.abspath(file_path)
        doc_id = Document.generate_doc_id(abs_path)
        json_path = DOCS_DIR / f"{doc_id}.json"

        if not json_path.exists():
            to_process.append(file_path)
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                doc_data = json.load(f)
            stored_last_updated = doc_data.get("last_updated")
            current_last_updated = Document.generate_last_updated(abs_path)
            if stored_last_updated != current_last_updated:
                to_process.append(file_path)
        except Exception:
            to_process.append(file_path)

    return to_process


def auto_process_raws(
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
    enable_cards: bool = True,
    enable_linking: bool = True,
    llm_model: str = "llama3.1",
    llm_base_url: str = "http://127.0.0.1:11434/v1",
) -> None:
    """自动扫描新增/修改文件，通过 A-MEM 管线增量入库。"""
    os.makedirs(str(RAWS_DIR), exist_ok=True)
    os.makedirs(str(DOCS_DIR), exist_ok=True)

    print(f"==================================================")
    print(f" [Start] A-MEM 自动增量解析入库")
    print(f" 原始文件扫描目录: {RAWS_DIR}")
    print(f" 管线: 语义分割 → 知识卡片 → 图谱链接 → 入库")
    print(f"==================================================")

    raw_files = _scan_folder(str(RAWS_DIR))
    if not raw_files:
        print(f" [Info] 未找到支持的原始文件 ({supported_extensions()})。")
        return

    print(f" [Scan] 共扫描到 {len(raw_files)} 个支持的文件")
    files_to_process = get_new_or_modified_files(raw_files)

    if not files_to_process:
        print(" [Finish] 所有文件均已是最新状态，无需处理！")
        return

    print(f" [Process] 检测到 {len(files_to_process)} 个待入库文件:")
    for f in files_to_process:
        print(f"  - {f}")

    # ── 初始化 Milvus ────────────────────────────────
    milvus = MilvusStore(host=milvus_host, port=milvus_port)
    try:
        milvus.connect()
        print(" [Milvus] 成功连接到 Milvus 向量库")
    except Exception as e:
        print(f" [Error] 无法连接到 Milvus: {e}")
        sys.exit(1)

    # ── 初始化 A-MEM 组件 ────────────────────────────
    from segmenter.similarity_segmenter import SimilaritySegmenter
    from precompressor.compressor_factory import create_compressor

    segmenter = SimilaritySegmenter(similarity_threshold=0.65)
    compressor = create_compressor("entropy_compress")  # P₀ 预压缩

    card_store = None
    stm_manager = None
    card_linker = None
    card_evolver = None

    if enable_cards:
        try:
            from knowledge_cards.card_store import CardStore
            from knowledge_cards.card_builder import CardConstructor
            from knowledge_cards.stm_buffer import STMBufferManager
            from knowledge_cards.card_linker import CardLinker
            from knowledge_cards.card_evolver import CardEvolver

            card_store = CardStore(
                milvus_host=milvus_host, milvus_port=milvus_port
            )
            _run_async(card_store.init(), timeout=30)

            cc = CardConstructor(
                llm_base_url=llm_base_url, llm_model=llm_model,
            )
            stm_manager = STMBufferManager(
                token_threshold=2000, card_constructor=cc,
            )
            card_linker = CardLinker(
                card_store=card_store,
                llm_base_url=llm_base_url, llm_model=llm_model,
            ) if enable_linking else None
            card_evolver = CardEvolver(
                llm_base_url=llm_base_url, llm_model=llm_model,
            )

            print(" [A-MEM] 知识卡片组件初始化完成")
        except Exception as e:
            print(f" [Warning] A-MEM 组件初始化失败，仅做语义分段: {e}")
            enable_cards = False

    # ── 逐文件处理 ────────────────────────────────────
    processed_count = 0
    total_segments = 0
    total_cards = 0
    total_links = 0

    for i, file_path in enumerate(files_to_process, 1):
        print(f"\n [Ingest] [{i}/{len(files_to_process)}] {file_path}")
        try:
            # 1. 解析
            doc = parse_file(file_path)
            print(f"  → 解析完成，全文 {len(doc.content)} 字符")

            # 2. 预压缩
            text = doc.content
            try:
                text = compressor.compress(text, compress_rate=0.6)
                print(f"  → 预压缩: {len(doc.content)} → {len(text)} 字符 "
                      f"({len(text)/max(len(doc.content),1):.0%})")
            except Exception:
                pass

            # 3. 语义分割
            segments = segmenter.segment(text, doc_id=doc.doc_id)
            if not segments:
                print(f"  [Warning] 未生成语义段落，跳过")
                continue

            unique_topics = len(set(s.topic_id for s in segments))
            print(f"  → 语义分割: {len(segments)} 段, {unique_topics} 个话题")
            total_segments += len(segments)

            # 4. 质量检查
            chunk_proxies = [
                type("Chunk", (), {"text": s.text, "index": i})()
                for i, s in enumerate(segments)
            ]
            quality_report = check_document_quality(
                doc.doc_id, doc.title, chunk_proxies, doc.content,
            )
            print(f"  → 质量检查: {quality_report.summary()}")
            if should_skip(quality_report):
                print(f"  [Rejected] 质量不达标，跳过入库")
                continue

            # 5. 段落向量化 + 入库
            seg_texts = [s.text for s in segments]
            seg_embeddings = embed_texts(seg_texts)

            # 清理旧数据
            try:
                delete_expr = f"doc_id == '{doc.doc_id}'"
                milvus.collection.delete(expr=delete_expr)
                print(f"  → 已清理旧向量")
            except Exception:
                pass

            # 写入 doc_chunks
            chunk_ids = [f"{doc.doc_id}_seg_{s.segment_id}" for s in segments]
            milvus.insert_chunks(
                embeddings=seg_embeddings,
                chunk_ids=chunk_ids,
                chunk_texts=seg_texts,
                doc_ids=[doc.doc_id] * len(segments),
                chunk_indices=list(range(len(segments))),
                source_urls=[doc.source_url] * len(segments),
                spaces=[doc.space] * len(segments),
            )
            print(f"  → 语义段已写入 doc_chunks ({len(segments)} 条)")

            # 写入 semantic_segments
            if card_store:
                try:
                    _run_async(
                        card_store.insert_segments(segments, seg_embeddings),
                        timeout=60,
                    )
                    print(f"  → 语义段已写入 semantic_segments ({len(segments)} 条)")
                except Exception as e:
                    print(f"  [Warning] semantic_segments 写入失败: {e}")

            # 6. 知识卡片提取 (LLM)
            all_cards = []
            if enable_cards and stm_manager:
                for seg in segments:
                    cards = stm_manager.add(seg)
                    if cards:
                        all_cards.extend(cards)
                all_cards.extend(stm_manager.flush_all())

                if all_cards:
                    card_texts = [c.combined_text() for c in all_cards]
                    card_embeddings = embed_texts(card_texts)
                    for c, emb in zip(all_cards, card_embeddings):
                        c.embedding = emb

                    _run_async(
                        card_store.insert_cards(all_cards),
                        timeout=120,
                    )
                    total_cards += len(all_cards)
                    print(f"  → 知识卡片: {len(all_cards)} 张")

                    # 卡片链接
                    if card_linker and len(all_cards) > 1:
                        try:
                            _, new_links = card_linker.link_cards(all_cards)
                            if new_links:
                                stored = card_store.add_links_batch(new_links)
                                total_links += stored
                                print(f"  → 卡片链接: {stored} 条")
                        except Exception as e:
                            print(f"  [Warning] 卡片链接失败: {e}")

                    # 卡片演化
                    if card_evolver:
                        try:
                            existing_ids = card_store.get_all_card_ids()
                            if existing_ids:
                                existing_cards = _run_async(
                                    card_store.get_cards_by_ids(
                                        existing_ids[:min(50, len(existing_ids))]
                                    ),
                                    timeout=30,
                                )
                                existing_embs = {}
                                for cid, cdata in existing_cards.items():
                                    content = cdata.get("content", "")
                                    if content:
                                        try:
                                            existing_embs[cid] = embed_texts(
                                                [content]
                                            )[0]
                                        except Exception:
                                            pass
                                if existing_embs:
                                    kept = card_evolver.evolve(
                                        all_cards, existing_embs, {},
                                    )
                                    if len(kept) < len(all_cards):
                                        print(
                                            f"  → 卡片演化: "
                                            f"{len(all_cards) - len(kept)} 张被吸收"
                                        )
                        except Exception as e:
                            print(f"  [Warning] 卡片演化跳过: {e}")
                else:
                    print(f"  → 知识卡片: 0 张")

            # 7. 保存 JSON 元数据
            json_data = doc.model_dump(mode="json")
            json_data["segments"] = [
                {
                    "segment_id": s.segment_id,
                    "text": s.text,
                    "topic_id": s.topic_id,
                    "boundary_score": s.boundary_score,
                }
                for s in segments
            ]
            json_data["segment_count"] = len(segments)
            json_data["card_count"] = len(all_cards) if enable_cards else 0

            save_document(doc.doc_id, json_data)
            print(f"  → JSON 已保存: data/documents/{doc.doc_id}.json")
            processed_count += 1

        except Exception as e:
            print(f"  [Error] 处理失败: {file_path}, 错误: {e}")
            import logging
            logging.getLogger(__name__).exception(f"Failed: {file_path}")

    # ── BM25 增量更新 ───────────────────────────────────
    if processed_count > 0:
        print(f"\n [BM25] 正在增量更新 BM25 倒排索引...")
        bm25 = BM25Index()
        bm25_index_path = BM25Index.default_index_path()
        if os.path.exists(bm25_index_path):
            bm25.load(bm25_index_path)

        processed_doc_ids = [
            Document.generate_doc_id(f) for f in files_to_process
        ]
        bm25.build_from_documents(doc_ids=processed_doc_ids)
        bm25.save(bm25_index_path)
        print(f"  → BM25 索引已增量更新")

    print(
        f"\n [Finish] A-MEM 增量入库完成！"
        f" 文档: {processed_count},"
        f" 语义段: {total_segments},"
        f" 知识卡片: {total_cards},"
        f" 链接: {total_links}"
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="A-MEM 自动增量解析入库"
    )
    parser.add_argument("--milvus-host", default="localhost")
    parser.add_argument("--milvus-port", default="19530")
    parser.add_argument("--no-cards", action="store_true",
                        help="禁用知识卡片（仅做语义分段）")
    parser.add_argument("--no-links", action="store_true",
                        help="禁用卡片链接")
    parser.add_argument("--llm-model", default="llama3.1")
    parser.add_argument("--llm-base-url",
                        default="http://127.0.0.1:11434/v1")
    args = parser.parse_args()

    auto_process_raws(
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
        enable_cards=not args.no_cards,
        enable_linking=not args.no_links,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )
