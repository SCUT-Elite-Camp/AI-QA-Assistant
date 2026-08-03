"""
A-MEM 完整处理管线。

替代旧的固定大小分块 → 向量化流程，改为:
  解析文档 → 预压缩 → 语义分割 → 段落入库 + 知识卡片提取 + 图谱链接 + 卡片演化

用法:
    python -m pipeline.amem_pipeline <folder_path>

管线阶段:
  P₀: 预压缩 (PreCompressor)         — 过滤低信息量内容
  B₂: 语义分割 (SimilaritySegmenter)  — 句子级相似度边界检测 + topic 聚类
  P₁: 段落入库 (doc_chunks + semantic_segments) — 兼容标准检索 + A-MEM 检索
  P_s1: 知识卡片构建 (CardConstructor) — LLM 批量提取结构化知识卡片
  P_s2: 卡片链接 (CardLinker)         — 向量 top-k + LLM judge 建立图谱
  P_s3: 卡片演化 (CardEvolver)        — 新卡片与已有卡片合并/更新/冲突检测
"""

import asyncio
import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ── sys.path ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(_PROJECT_ROOT),
    str(_PROJECT_ROOT / "data-pipeline"),
    str(_PROJECT_ROOT / "data-persistence"),
    str(_PROJECT_ROOT / "toolset"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from models.document import Document
from parsers.registry import parse_file, supported_extensions
from pipeline.embedder import embed_texts

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════

DEFAULT_CHUNK_SIZE = 500    # 语义段作为 chunk 时的最大字符数（仅用于 doc_chunks 兼容）
DEFAULT_OVERLAP = 100       # 仅对大段做滑动窗口切割时的重叠


def _run_async(coro, timeout: int = 60):
    """安全地在同步代码中运行异步协程"""
    try:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result(timeout=timeout)
    except RuntimeError:
        return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════
# 主处理函数
# ═══════════════════════════════════════════════════════════

def process_folder_amem(
    folder_path: str,
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
    enable_precompress: bool = True,
    compress_method: str = "entropy_compress",
    compress_rate: float = 0.6,
    segment_threshold: float = 0.65,
    enable_cards: bool = True,
    enable_linking: bool = True,
    enable_evolution: bool = True,
    llm_model: str = "llama3.1",
    llm_base_url: str = "http://127.0.0.1:11434/v1",
) -> list[Document]:
    """A-MEM 全管线处理文件夹中的所有 PDF/DOCX 文件。

    流程: 解析 → 预压缩 → 语义分割 → 段落入库 → 卡片提取 → 链接 → 演化 → BM25

    Args:
        folder_path: 原始文件目录
        milvus_host/port: Milvus 连接信息
        enable_precompress: 是否开启预压缩
        compress_method: 压缩方法 (entropy_compress / llmlingua2 / none)
        compress_rate: 压缩保留比例
        segment_threshold: 语义分割相似度阈值 (0~1, 越低越细)
        enable_cards: 是否启用知识卡片提取
        enable_linking: 是否启用卡片链接
        enable_evolution: 是否启用卡片演化
        llm_model: LLM 模型名
        llm_base_url: LLM API 地址

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

    # ── 初始化各组件 ──────────────────────────────────
    from storage.milvus_store import MilvusStore
    from retrieval.bm25_index import BM25Index
    from segmenter.similarity_segmenter import SimilaritySegmenter
    from precompressor.compressor_factory import create_compressor

    milvus = MilvusStore(host=milvus_host, port=milvus_port)
    segmenter = SimilaritySegmenter(similarity_threshold=segment_threshold)
    compressor = create_compressor(compress_method) if enable_precompress else None

    # A-MEM 组件（延迟初始化，避免 LLM 不可用时崩溃）
    card_store = None
    card_constructor = None
    card_linker = None
    card_evolver = None
    stm_manager = None

    if enable_cards:
        try:
            from knowledge_cards.card_store import CardStore
            from knowledge_cards.card_builder import CardConstructor
            from knowledge_cards.stm_buffer import STMBufferManager

            card_store = CardStore(
                milvus_host=milvus_host, milvus_port=milvus_port
            )
            _run_async(card_store.init(), timeout=30)

            card_constructor = CardConstructor(
                llm_base_url=llm_base_url,
                llm_model=llm_model,
            )
            stm_manager = STMBufferManager(
                token_threshold=2000,
                card_constructor=card_constructor,
            )
            print("  → A-MEM 组件初始化完成（CardStore + CardConstructor + STM）")

            if enable_linking:
                from knowledge_cards.card_linker import CardLinker
                card_linker = CardLinker(
                    card_store=card_store,
                    llm_base_url=llm_base_url,
                    llm_model=llm_model,
                )
            if enable_evolution:
                from knowledge_cards.card_evolver import CardEvolver
                card_evolver = CardEvolver(
                    llm_base_url=llm_base_url,
                    llm_model=llm_model,
                )
        except Exception as e:
            print(f"  ⚠ A-MEM 组件初始化失败，跳过知识卡片: {e}")
            enable_cards = False

    documents: list[Document] = []
    total_segments = 0
    total_cards = 0
    total_links = 0

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] 处理: {file_path}")
        try:
            # ─── P₀: 文档解析 ─────────────────────────
            doc = parse_file(file_path)
            print(f"  → 解析完成，全文 {len(doc.content)} 字符")

            # ─── P₀.₅: 预压缩（可选）──────────────────
            text_to_segment = doc.content
            if compressor:
                try:
                    text_to_segment = compressor.compress(
                        doc.content, compress_rate=compress_rate
                    )
                    kept_pct = len(text_to_segment) / max(len(doc.content), 1)
                    print(f"  → 预压缩: {len(doc.content)} → {len(text_to_segment)} 字符 ({kept_pct:.0%})")
                except Exception as e:
                    print(f"  ⚠ 预压缩失败，使用原文: {e}")

            # ─── B₂: 语义分割 ─────────────────────────
            if not text_to_segment.strip():
                print(f"  ⚠ 跳过（无有效内容）")
                continue

            segments = segmenter.segment(text_to_segment, doc_id=doc.doc_id)
            if not segments:
                print(f"  ⚠ 跳过（未生成语义段落）")
                continue

            unique_topics = len(set(s.topic_id for s in segments))
            print(f"  → 语义分割: {len(segments)} 段, {unique_topics} 个话题")

            total_segments += len(segments)

            # ─── P₁: 段落入库 (doc_chunks + semantic_segments) ──
            seg_texts = [s.text for s in segments]
            seg_embeddings = embed_texts(seg_texts)

            # 写入 doc_chunks（兼容标准向量检索）
            chunk_ids = [f"{doc.doc_id}_seg_{s.segment_id}" for s in segments]
            doc_ids = [doc.doc_id] * len(segments)
            chunk_indices = list(range(len(segments)))
            source_urls = [doc.source_url] * len(segments)
            spaces = [doc.space] * len(segments)

            milvus.insert_chunks(
                embeddings=seg_embeddings,
                chunk_ids=chunk_ids,
                chunk_texts=seg_texts,
                doc_ids=doc_ids,
                chunk_indices=chunk_indices,
                source_urls=source_urls,
                spaces=spaces,
            )
            print(f"  → 语义段已写入 doc_chunks ({len(segments)} 条)")

            # 写入 semantic_segments（供 CardRetriever 使用）
            if card_store:
                try:
                    _run_async(
                        card_store.insert_segments(segments, seg_embeddings),
                        timeout=60,
                    )
                    print(f"  → 语义段已写入 semantic_segments ({len(segments)} 条)")
                except Exception as e:
                    print(f"  ⚠ semantic_segments 写入失败: {e}")

            # ─── P_s1: 知识卡片提取 ─────────────────
            all_cards = []
            if enable_cards and stm_manager:
                for seg in segments:
                    cards = stm_manager.add(seg)
                    if cards:
                        all_cards.extend(cards)
                all_cards.extend(stm_manager.flush_all())

                if all_cards:
                    # 卡片向量化
                    card_texts = [c.combined_text() for c in all_cards]
                    card_embeddings = embed_texts(card_texts)
                    for c, emb in zip(all_cards, card_embeddings):
                        c.embedding = emb

                    # 写入 knowledge_cards
                    _run_async(
                        card_store.insert_cards(all_cards),
                        timeout=120,
                    )
                    total_cards += len(all_cards)
                    print(f"  → 知识卡片: {len(all_cards)} 张")

                    # ─── P_s2: 卡片链接 ─────────────
                    if card_linker and len(all_cards) > 1:
                        try:
                            linked_cards, new_links = card_linker.link_cards(all_cards)
                            if new_links:
                                stored = card_store.add_links_batch(new_links)
                                total_links += stored
                                print(f"  → 卡片链接: {stored} 条")
                        except Exception as e:
                            print(f"  ⚠ 卡片链接失败: {e}")

                    # ─── P_s3: 卡片演化 ─────────────
                    if card_evolver:
                        # 收集已有卡片用于演化判断
                        try:
                            existing_ids = card_store.get_all_card_ids()
                            if existing_ids:
                                existing_cards = _run_async(
                                    card_store.get_cards_by_ids(existing_ids[:50]),
                                    timeout=30,
                                )
                                existing_embs = {}
                                for cid, cdata in existing_cards.items():
                                    content = cdata.get("content", "")
                                    if content:
                                        try:
                                            existing_embs[cid] = embed_texts([content])[0]
                                        except Exception:
                                            pass

                                if existing_embs:
                                    kept = card_evolver.evolve(
                                        all_cards,
                                        existing_embs,
                                        {},
                                    )
                                    if len(kept) < len(all_cards):
                                        print(f"  → 卡片演化: {len(all_cards) - len(kept)} 张被吸收")
                        except Exception as e:
                            print(f"  ⚠ 卡片演化跳过: {e}")
                else:
                    print(f"  → 知识卡片: 0 张（内容不足以提取）")

            # 保存 JSON 元数据（沿用旧格式兼容）
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

            from storage.document_store import save_document
            save_document(doc.doc_id, json_data)
            print(f"  → JSON 已保存: data/documents/{doc.doc_id}.json")

            documents.append(doc)

        except Exception as e:
            print(f"  ❌ 处理失败: {file_path}，错误: {e}")
            logger.exception(f"Failed to process {file_path}")

    # ─── 构建 BM25 索引 ──────────────────────────────
    if documents:
        print(f"\n构建 BM25 索引（基于语义段落）...")
        bm25 = BM25Index()
        bm25.build_from_documents()
        bm25_index_path = BM25Index.default_index_path()
        bm25.save(bm25_index_path)
        print(f"  → BM25 索引已保存: {bm25_index_path}")

    print(
        f"\n处理完成！"
        f" 文档: {len(documents)}, "
        f"语义段: {total_segments}, "
        f"知识卡片: {total_cards}, "
        f"链接: {total_links}"
    )
    return documents


def _scan_folder(folder_path: str) -> list[str]:
    """递归扫描，返回支持的文件路径"""
    files: list[str] = []
    exts = supported_extensions()
    for root, _dirs, filenames in os.walk(folder_path):
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in exts:
                files.append(os.path.join(root, fname))
    return files


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="A-MEM 全管线：语义分割 + 知识卡片 + 图谱链接",
    )
    parser.add_argument("folder", help="包含待处理 PDF/DOCX 文件的文件夹路径")
    parser.add_argument("--milvus-host", default="localhost")
    parser.add_argument("--milvus-port", default="19530")
    parser.add_argument("--no-precompress", action="store_true", help="禁用预压缩")
    parser.add_argument("--compress-method", default="entropy_compress")
    parser.add_argument("--compress-rate", type=float, default=0.6)
    parser.add_argument("--segment-threshold", type=float, default=0.65,
                        help="语义分割相似度阈值 (0~1)")
    parser.add_argument("--no-cards", action="store_true", help="禁用知识卡片提取")
    parser.add_argument("--no-links", action="store_true", help="禁用卡片链接")
    parser.add_argument("--no-evolution", action="store_true", help="禁用卡片演化")
    parser.add_argument("--llm-model", default="llama3.1")
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:11434/v1")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    process_folder_amem(
        folder_path=args.folder,
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
        enable_precompress=not args.no_precompress,
        compress_method=args.compress_method,
        compress_rate=args.compress_rate,
        segment_threshold=args.segment_threshold,
        enable_cards=not args.no_cards,
        enable_linking=not args.no_links,
        enable_evolution=not args.no_evolution,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )
