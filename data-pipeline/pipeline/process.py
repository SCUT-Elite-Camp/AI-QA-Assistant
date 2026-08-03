"""
数据处理管线入口。

用法:
    python -m pipeline.process <folder_path>

示例:
    python -m pipeline.process data/raws/测试空间

流程 (A-MEM 全管线):
    扫描文件夹 → 解析 PDF/DOCX → 预压缩 → 语义分割
    → 段落入库 (doc_chunks + semantic_segments)
    → 知识卡片提取 (LLM) → 卡片链接 (LLM) → 卡片演化 (LLM)
    → 构建 BM25 索引
"""

import os
import sys
from pathlib import Path

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

from pipeline.amem_pipeline import process_folder_amem


# 保持旧的函数签名作为兼容入口
def process_folder(
    folder_path: str,
    chunk_size: int = 500,
    overlap: int = 100,
    milvus_host: str = "localhost",
    milvus_port: str = "19530",
) -> list:
    """处理文件夹中的所有 PDF/DOCX 文件 (A-MEM 全管线)。

    参数保持向后兼容，chunk_size/overlap 参数已不再使用
    （语义分割替代了固定大小分块）。
    """
    return process_folder_amem(
        folder_path=folder_path,
        milvus_host=milvus_host,
        milvus_port=milvus_port,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="A-MEM 数据处理管线：语义分割 + 知识卡片 + 图谱链接",
    )
    parser.add_argument("folder", help="包含待处理 PDF/DOCX 文件的文件夹路径")
    parser.add_argument("--chunk-size", type=int, default=500,
                        help="（已废弃，语义分割替代固定分块）")
    parser.add_argument("--overlap", type=int, default=100,
                        help="（已废弃，语义分割替代固定分块）")
    parser.add_argument("--milvus-host", default="localhost")
    parser.add_argument("--milvus-port", default="19530")
    parser.add_argument("--no-precompress", action="store_true")
    parser.add_argument("--segment-threshold", type=float, default=0.65)
    parser.add_argument("--no-cards", action="store_true")
    parser.add_argument("--llm-model", default="llama3.1")
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:11434/v1")

    args = parser.parse_args()

    process_folder_amem(
        folder_path=args.folder,
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
        enable_precompress=not args.no_precompress,
        segment_threshold=args.segment_threshold,
        enable_cards=not args.no_cards,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )
