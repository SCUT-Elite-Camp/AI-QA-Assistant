"""Review saved English online runs without substituting historical model metadata."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "agent", ROOT / "toolset", ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(path))
from dotenv import load_dotenv


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / "agent/.env", override=True)
    here = ROOT / "eval/deep_research_a"
    os.environ["DR_EVAL_DATASET_PATH"] = str(here / "datasets/cases.en.v1.json")
    os.environ["DR_EVAL_MANIFEST_PATH"] = str(here / "manifests/source_manifests.en.v1.json")
    experiment = args.experiment.resolve()
    frozen = json.loads((experiment / "runs/config/frozen_environment.json").read_text(encoding="utf-8"))
    baseline = json.loads((here / "config/frozen_baseline.json").read_text(encoding="utf-8"))
    baseline.update(baseline_id=experiment.name, dataset_version="cp2-deep-research-cases.en.v1")
    baseline["repository"]["head_commit"] = frozen["git"]["commit"]
    baseline["generation"].update(model=frozen["model"]["name"], api_base=frozen["model"]["api_base"],
                                  temperature=frozen["model"]["temperature"], max_tokens=frozen["model"]["max_tokens"])
    baseline["generation_config_sha256"] = hashlib.sha256(json.dumps(baseline["generation"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    baseline_path = experiment / "runs/config/review_baseline.json"
    baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    os.environ["DR_EVAL_BASELINE_PATH"] = str(baseline_path)
    converter = module("english_run_converter", here / "convert_benchmark_runs.py")
    judge = module("english_run_judge", here / "judge_records.py")
    suite = module("english_run_suite", here / "suite.py")
    cases = {case["case_id"]: case for case in converter.load(converter.DATASET)["cases"]}
    manifests = converter.load(converter.MANIFESTS)["manifests"]
    prompt = (here / "prompts/model_judge.v1.md").read_text(encoding="utf-8")
    client = judge.LLMClient()
    rows = []
    for path in sorted((experiment / "runs/runs").glob("*/*/*.json")):
        envelope = converter.load(path)
        case = cases[envelope["case_id"]]
        record = converter.convert(envelope, case, manifests[case["case_id"]], baseline, frozen_environment=frozen)
        destination = experiment / "review" / record["group"] / case["case_id"] / path.name
        if destination.exists():
            record = converter.load(destination)
        if args.judge and record.get("model_judge") is None:
            for attempt in range(3):
                try:
                    judge.judge_record(record, case, prompt, client)
                    record["judge_model"] = os.environ["LLM_MODEL"]
                    record.pop("judge_error", None)
                    break
                except Exception as exc:
                    record["model_judge"] = None
                    record["judge_error"] = {"type": type(exc).__name__, "message": str(exc), "attempt": attempt + 1}
        converter.dump(destination, record)
        scored = suite.score_run(record)
        converter.dump(destination.with_suffix(".score.json"), scored)
        rows.append({"run_id": record["run_id"], "case_id": record["case_id"], "group": record["group"],
                     "technical_success": envelope["success"], "model_judge": record.get("model_judge"),
                     "judge_error": record.get("judge_error"), "score": scored})
        print(f"Reviewed {record['case_id']} {record['group']}: technical_success={envelope['success']} judge={record.get('model_judge') is not None}", flush=True)
    converter.dump(experiment / "quality_review.json", rows)
    print(f"Reviewed {len(rows)} English runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
