"""Prepare or run the English G1/G2 benchmark using agent/.env."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
for folder in (ROOT, AGENT, ROOT / "toolset", ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(folder))

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "freeze", "serve", "run"))
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "g1_g2_english_20261002")
    args = parser.parse_args()
    load_dotenv(AGENT / ".env", override=True)
    os.chdir(ROOT)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # A separate database prevents old queued research jobs from resuming in this round.
    os.environ["RESEARCH_DATABASE_PATH"] = str(output / "research_jobs.db")
    os.environ["RESEARCH_CHECKPOINT_PATH"] = str(output / "research_jobs.db.checkpoints")
    dataset_path = ROOT / "eval/deep_research_a/datasets/cases.en.v1.json"
    os.environ["DR_EVAL_DATASET_PATH"] = str(dataset_path)
    os.environ["DR_EVAL_MANIFEST_PATH"] = str(ROOT / "eval/deep_research_a/manifests/source_manifests.en.v1.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert dataset["language"] == "en-US" and len(dataset["cases"]) == 18
    assert not re.search(r"[\u4e00-\u9fff]", json.dumps(dataset, ensure_ascii=False))
    assert all(case["report_language"] == "en-US" for case in dataset["cases"])
    if not os.getenv("LLM_API_KEY") or not os.getenv("AGENT_API_KEY"):
        raise RuntimeError("Configure LLM_API_KEY and AGENT_API_KEY in agent/.env")
    from eval.deep_research_a.suite import validate_assets
    errors = validate_assets(verbose=False)
    if errors:
        raise RuntimeError("Source validation failed: " + "; ".join(errors))
    spec = importlib.util.spec_from_file_location("g1_g2_benchmark", AGENT / "eval/deep_research_benchmark.py")
    benchmark = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = benchmark
    spec.loader.exec_module(benchmark)
    if args.mode == "serve":
        import uvicorn
        uvicorn.run("app:app", host="127.0.0.1", port=args.port)
        return 0
    if args.mode == "run":
        benchmark_args = benchmark.build_parser().parse_args([
            "run", "--dataset", str(dataset_path), "--output-dir", str(output / "runs"),
            "--base-url", f"http://127.0.0.1:{args.port}", "--groups", "fast_chat", "deep_research_current",
            "--repetitions", "3", "--request-timeout", "120", "--run-timeout", "600",
        ])
        return benchmark.run_benchmark(benchmark_args)
    frozen = benchmark.freeze_environment(output / "config")
    print(json.dumps({"cases": 18, "runs_planned": 108, "language": "en-US",
                      "model": frozen["model"]["name"], "embedding": frozen["retrieval"]["embedding_model"],
                      "source_validation": "passed", "config": str(output / "config"),
                      "online_benchmark_started": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
