import argparse
import json
import os
import sys
from pathlib import Path

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

from eval.evaluator import SystemEvaluator, format_summary_table


def main():
    parser = argparse.ArgumentParser(
        description="AI-QA-Assistant Performance Evaluation Suite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["all", "retrieval", "generation"],
        default="all",
        help="What component of the system to evaluate."
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=["vector", "bm25", "hybrid", "all_modes"],
        default="hybrid",
        help="Retrieval mode to evaluate (use 'all_modes' to compare all options)."
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of documents to retrieve (1-20)."
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Enable LLM-as-a-judge for faithfulness and relevance scoring (requires running LLM)."
    )
    parser.add_argument(
        "--dataset",
        choices=["local", "ms_marco"],
        default="local",
        help="Evaluation dataset to use ('local' for Chinese docs, 'ms_marco' for English MSMARCO)."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="eval_results.json",
        help="Filename/Path to save the detailed evaluation output."
    )

    args = parser.parse_args()
    
    # Resolve absolute path for output to keep it clear
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(__file__).parent / output_path

    print("=" * 60)
    print("      AI-QA-ASSISTANT PERFORMANCE EVALUATION SUITE      ")
    print("=" * 60)
    print(f"Working Directory: {Path(__file__).parent}")
    print(f"Output File:      {output_path}")
    print("-" * 60)

    # Initialize evaluator
    filename = "eval_questions_msmarco.json" if args.dataset == "ms_marco" else "eval_questions.json"
    questions_path = Path(__file__).parent / filename
    evaluator = SystemEvaluator(questions_path=str(questions_path))

    results = {}

    # 1. Retrieval Evaluation
    if args.mode in ["all", "retrieval"]:
        if args.retrieval_mode == "all_modes":
            retrieval_runs = {}
            for r_mode in ["vector", "bm25", "hybrid"]:
                run_res = evaluator.evaluate_retrieval_performance(mode=r_mode, top_k=args.top_k)
                retrieval_runs[r_mode] = run_res
                print(format_summary_table("retrieval", run_res))
            results["retrieval"] = retrieval_runs
        else:
            run_res = evaluator.evaluate_retrieval_performance(mode=args.retrieval_mode, top_k=args.top_k)
            print(format_summary_table("retrieval", run_res))
            results["retrieval"] = run_res

    # 2. Generation Evaluation
    if args.mode in ["all", "generation"]:
        gen_mode = "hybrid" if args.retrieval_mode == "all_modes" else args.retrieval_mode
        run_res = evaluator.evaluate_generation_performance(mode=gen_mode, top_k=args.top_k, use_judge=args.judge)
        print(format_summary_table("generation", run_res))
        results["generation"] = run_res


    # Save results to file
    try:
        # Create directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Detailed evaluation logs successfully saved to: {output_path}")
    except Exception as e:
        print(f"\n❌ Error writing output file: {e}")


if __name__ == "__main__":
    main()
