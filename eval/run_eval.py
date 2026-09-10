import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Setup paths to resolve imports correctly
project_root = Path(__file__).resolve().parent.parent
python_paths = [
    str(project_root),
    str(project_root / "data-pipeline"),
    str(project_root / "data-persistence"),
    str(project_root / "toolset"),
    str(project_root / "agent")
]
for p in python_paths:
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.ragas_eval import RagasEvaluator
from eval.evaluator import SystemEvaluator, format_summary_table


def main():
    parser = argparse.ArgumentParser(
        description="AI-QA-Assistant Ragas 自动化量化评测套件 (支持 Fast / Thinking 双模式对比)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["ragas", "retrieval", "all"],
        default="ragas",
        help="评测模式：'ragas'（RAG三元组自动化打分）、'retrieval'（仅检索评测）、'all'（全量评测）"
    )
    parser.add_argument(
        "--weight-mode",
        choices=["fast", "thinking", "compare"],
        default="compare",
        help="系统工作模式：'fast'（极速单轮直接RAG）、'thinking'（深度Agent编排思考模式）、'compare'（双模式横向对比）"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="自定义评测集路径（默认使用 eval/confluence_eval_dataset.json）"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="检索召回文档块数 (Top-K)"
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="限制评测样本数量（用于快速抽样测试）"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("      AI-QA-ASSISTANT RAGAS AUTOMATION EVALUATION SUITE      ")
    print("=" * 70)

    # 1. 运行 Ragas 评测 (核心)
    if args.mode in ["ragas", "all"]:
        ragas_eval = RagasEvaluator(dataset_path=args.dataset)
        if args.weight_mode == "compare":
            ragas_eval.evaluate_comparison(top_k=args.top_k, max_samples=args.max_samples)
        else:
            ragas_eval.evaluate_live(weight_mode=args.weight_mode, top_k=args.top_k, max_samples=args.max_samples)

    # 2. 运行纯检索指标评测 (可选)
    if args.mode in ["retrieval", "all"]:
        evaluator = SystemEvaluator()
        retrieval_res = evaluator.evaluate_retrieval_performance(mode="hybrid", top_k=args.top_k)
        print(format_summary_table("retrieval", retrieval_res))


if __name__ == "__main__":
    main()
