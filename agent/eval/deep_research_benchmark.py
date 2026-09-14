"""Reproducible G1/G2/G3 benchmark runner for CP2 Deep Research.

The runner deliberately talks to the public HTTP contracts so benchmark
results describe the demonstrable product rather than a test-only shortcut.
It never silently substitutes the current lexical fallback for Page Index.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


AGENT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_ROOT.parent
DOCUMENTS_DIR = PROJECT_ROOT / "data-persistence" / "data" / "documents"
DEFAULT_OUTPUT_ROOT = AGENT_ROOT / "outputs" / "deep_research_benchmark"
TERMINAL_RESEARCH_STATUSES = {"completed", "failed", "cancelled"}
GROUPS = ("fast_chat", "deep_research_current", "deep_research_page_index")


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _safe_setting(name: str, default: Any) -> Any:
    value = os.getenv(name)
    return default if value is None else value


def _document_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = _json_load(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    source_url = str(payload.get("source_url") or payload.get("address") or "")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    page_id = str(metadata.get("page_id") or "")
    if not page_id or "huifengagent.atlassian.net" not in source_url:
        return None
    content = str(payload.get("content") or "")
    content_hash = str(payload.get("content_hash") or _sha256_bytes(content.encode("utf-8")))
    return {
        "doc_id": str(payload.get("doc_id") or path.stem),
        "page_id": page_id,
        "title": str(payload.get("title") or path.stem),
        "version": payload.get("version") or payload.get("last_updated"),
        "last_updated": payload.get("last_updated"),
        "content_hash": content_hash,
        "source_url": source_url,
        "space": payload.get("space") or metadata.get("space_key"),
    }


def freeze_environment(output_dir: Path) -> dict[str, Any]:
    documents = [
        item
        for path in sorted(DOCUMENTS_DIR.glob("*.json"))
        if (item := _document_snapshot(path)) is not None
    ]
    manifest = {
        "schema_version": "deep-research-documents.v1",
        "document_count": len(documents),
        "documents": documents,
    }
    manifest["manifest_hash"] = _sha256_json(manifest["documents"])

    config = {
        "schema_version": "deep-research-benchmark.v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "git": {
            "branch": _git("branch", "--show-current"),
            "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain")),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "model": {
            "name": _safe_setting("LLM_MODEL", "qwen3.7-flash-2026-07-15"),
            "temperature": float(_safe_setting("LLM_TEMPERATURE", 0.1)),
            "max_tokens": int(_safe_setting("LLM_MAX_TOKENS", 2000)),
            "timeout_seconds": int(_safe_setting("LLM_TIMEOUT", 60)),
        },
        "retrieval": {
            "mode": _safe_setting("DEFAULT_RETRIEVAL_MODE", "hybrid"),
            "top_k": int(_safe_setting("DEFAULT_TOP_K", 5)),
            "min_score": float(_safe_setting("MIN_RETRIEVAL_SCORE", 0.0)),
            "embedding_model": _safe_setting(
                "LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
            ),
            "page_index_provider": "unavailable_until_capability_probe_passes",
        },
        "research": {
            "dispatcher_interval_seconds": float(
                _safe_setting("RESEARCH_DISPATCH_INTERVAL_SECONDS", 2.0)
            ),
            "max_agent_iterations": int(_safe_setting("MAX_AGENT_ITERATIONS", 5)),
            "max_repeated_tool_calls": int(
                _safe_setting("MAX_REPEATED_TOOL_CALLS", 2)
            ),
        },
        "documents_manifest_hash": manifest["manifest_hash"],
        "documents_count": manifest["document_count"],
    }
    config["config_hash"] = _sha256_json(config)
    _json_dump(output_dir / "frozen_environment.json", config)
    _json_dump(output_dir / "documents_manifest.json", manifest)
    return config


class ApiError(RuntimeError):
    def __init__(self, status: int | None, message: str) -> None:
        self.status = status
        super().__init__(message)


class ApiClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json", "X-User-ID": "benchmark-user"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(exc.code, detail) from exc
        except URLError as exc:
            raise ApiError(None, str(exc.reason)) from exc


def _case_scope(case: dict[str, Any]) -> dict[str, Any]:
    scope = case.get("source_scope") or case.get("source_manifest")
    if not isinstance(scope, dict):
        raise ValueError(f"case {case.get('case_id')} has no source_scope object")
    return {
        "document_ids": [str(item) for item in scope.get("document_ids", [])],
        "knowledge_base_ids": [str(item) for item in scope.get("knowledge_base_ids", [])],
        "topic": str(scope.get("topic") or ""),
    }


def _check_url(url: str, *, timeout_seconds: float = 15.0) -> dict[str, Any]:
    started = time.perf_counter()
    if not url:
        return {"url": url, "ok": False, "status": None, "error": "missing_url"}
    try:
        request = Request(url, method="GET", headers={"User-Agent": "CP2-Eval/1.0"})
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
        return {
            "url": url,
            "ok": 200 <= status < 400,
            "status": status,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except HTTPError as exc:
        # Authenticated Confluence may return 401/403 to this non-browser probe.
        return {
            "url": url,
            "ok": False,
            "status": exc.code,
            "error": "http_error",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except (URLError, ValueError) as exc:
        return {
            "url": url,
            "ok": False,
            "status": None,
            "error": str(exc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }


def _run_fast_chat(client: ApiClient, case: dict[str, Any], top_k: int) -> dict[str, Any]:
    response = client.request(
        "POST",
        "/api/chat",
        {
            "query": case["question"],
            "top_k": top_k,
            "filters": {"doc_ids": _case_scope(case)["document_ids"]},
            "retrieval_mode": "hybrid",
            "stream": False,
        },
    )
    citations = response.get("citations", []) if isinstance(response, dict) else []
    status = str(response.get("status") or "") if isinstance(response, dict) else ""
    if status != "success":
        raise RuntimeError(f"fast_chat_terminal_status:{status or 'missing'}")
    return {
        "response": response,
        "citations": citations,
        "source_checks": [
            _check_url(str(item.get("source_url") or "")) for item in citations
        ],
    }


def _wait_for_status(
    client: ApiClient,
    research_id: str,
    wanted: set[str],
    *,
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        job = client.request("GET", f"/api/research/jobs/{research_id}")
        if job.get("status") in wanted:
            return job
        time.sleep(0.5)
    raise TimeoutError(f"research status did not reach {sorted(wanted)}")


def _run_research(
    client: ApiClient,
    case: dict[str, Any],
    *,
    profile: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if profile == "page_index":
        capability = client.request("GET", "/api/tools")
        names = {
            str(item.get("name") or "")
            for item in capability
            if isinstance(item, dict)
        }
        page_index_names = {"page_index", "search_page_index", "navigate_page_index"}
        if not names.intersection(page_index_names):
            raise RuntimeError("page_index_provider_unavailable")

    deadline = time.monotonic() + timeout_seconds
    job = client.request(
        "POST",
        "/api/research/jobs",
        {
            "query": case["question"],
            "source_scope": _case_scope(case),
            "report_spec": {
                "format": "markdown",
                "language": case.get("report_language", "zh-CN"),
                "include_citations": True,
                "include_limitations": True,
            },
        },
    )
    research_id = str(job["research_id"])
    job = _wait_for_status(
        client,
        research_id,
        {"awaiting_approval", "failed", "cancelled"},
        deadline=deadline,
    )
    plan = None
    if job["status"] == "awaiting_approval":
        plan = client.request("GET", f"/api/research/jobs/{research_id}/plan")
        client.request(
            "POST",
            f"/api/research/jobs/{research_id}/approve",
            {
                "plan_version": plan["version"],
                "manifest_hash": plan["manifest_hash"],
            },
        )
        job = _wait_for_status(
            client,
            research_id,
            TERMINAL_RESEARCH_STATUSES,
            deadline=deadline,
        )

    progress = client.request("GET", f"/api/research/jobs/{research_id}/progress")
    events = client.request(
        "GET", f"/api/research/jobs/{research_id}/events?after_event_id=0&limit=100"
    )
    report = None
    citations: list[dict[str, Any]] = []
    if job["status"] == "completed":
        report = client.request("GET", f"/api/research/jobs/{research_id}/report")
        citations = report.get("citations", [])
    return {
        "research_id": research_id,
        "job": job,
        "plan": plan,
        "progress": progress,
        "events": events,
        "report": report,
        "citations": citations,
        "source_checks": [
            _check_url(str(item.get("source_url") or "")) for item in citations
        ],
        "retrieval_profile": profile,
    }


@dataclass
class RunEnvelope:
    schema_version: str
    run_id: str
    case_id: str
    group: str
    repetition: int
    started_at: str
    completed_at: str
    elapsed_ms: int
    config_hash: str
    success: bool
    result: dict[str, Any] | None
    error: dict[str, Any] | None


def run_benchmark(args: argparse.Namespace) -> int:
    dataset = _json_load(Path(args.dataset))
    cases = dataset.get("cases") if isinstance(dataset, dict) else dataset
    if not isinstance(cases, list) or not cases:
        raise ValueError("dataset must contain a non-empty cases list")
    unknown_groups = set(args.groups) - set(GROUPS)
    if unknown_groups:
        raise ValueError(f"unknown groups: {sorted(unknown_groups)}")

    output_root = Path(args.output_dir)
    config = freeze_environment(output_root / "config")
    _json_dump(output_root / "dataset_snapshot.json", dataset)
    client = ApiClient(args.base_url, timeout_seconds=args.request_timeout)
    failures = 0

    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        question = str(case.get("question") or "").strip()
        if not case_id or not question:
            raise ValueError("every case requires case_id and question")
        for group in args.groups:
            for repetition in range(1, args.repetitions + 1):
                run_id = f"{case_id}-{group}-r{repetition}-{uuid4().hex[:8]}"
                started_at = datetime.now(timezone.utc)
                started = time.perf_counter()
                result = None
                error = None
                try:
                    if group == "fast_chat":
                        result = _run_fast_chat(client, case, args.top_k)
                    elif group == "deep_research_current":
                        result = _run_research(
                            client,
                            case,
                            profile="current",
                            timeout_seconds=args.run_timeout,
                        )
                    else:
                        result = _run_research(
                            client,
                            case,
                            profile="page_index",
                            timeout_seconds=args.run_timeout,
                        )
                except Exception as exc:  # preserve every failed run
                    failures += 1
                    error = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "http_status": getattr(exc, "status", None),
                    }
                completed_at = datetime.now(timezone.utc)
                envelope = RunEnvelope(
                    schema_version="deep-research-run.v1",
                    run_id=run_id,
                    case_id=case_id,
                    group=group,
                    repetition=repetition,
                    started_at=started_at.isoformat(),
                    completed_at=completed_at.isoformat(),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    config_hash=config["config_hash"],
                    success=error is None,
                    result=result,
                    error=error,
                )
                _json_dump(output_root / "runs" / group / case_id / f"{run_id}.json", asdict(envelope))
                state = "PASS" if envelope.success else "FAIL"
                print(f"[{state}] {case_id} {group} repetition={repetition} run_id={run_id}")
    return 1 if failures else 0


def summarize(output_root: Path) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for path in sorted((output_root / "runs").glob("*/*/*.json")):
        payload = _json_load(path)
        group = str(payload.get("group") or "")
        if group in grouped:
            grouped[group].append(payload)

    result: dict[str, Any] = {"schema_version": "deep-research-summary.v1", "groups": {}}
    for group, rows in grouped.items():
        elapsed = [int(row.get("elapsed_ms") or 0) for row in rows]
        source_checks = [
            check
            for row in rows
            for check in ((row.get("result") or {}).get("source_checks") or [])
        ]
        result["groups"][group] = {
            "runs": len(rows),
            "successful_runs": sum(bool(row.get("success")) for row in rows),
            "failed_runs": sum(not bool(row.get("success")) for row in rows),
            "latency_mean_ms": round(statistics.mean(elapsed), 2) if elapsed else None,
            "latency_p50_ms": round(statistics.median(elapsed), 2) if elapsed else None,
            "source_links": len(source_checks),
            "broken_source_links": sum(not bool(item.get("ok")) for item in source_checks),
        }
    _json_dump(output_root / "summary.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="freeze code, model and document metadata")
    freeze.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT / "config"))

    run = subparsers.add_parser("run", help="run benchmark groups through public APIs")
    run.add_argument("--dataset", required=True)
    run.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    run.add_argument("--base-url", default="http://127.0.0.1:8000")
    run.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--top-k", type=int, default=5)
    run.add_argument("--request-timeout", type=float, default=120.0)
    run.add_argument("--run-timeout", type=float, default=600.0)

    summary = subparsers.add_parser("summarize", help="summarize preserved run envelopes")
    summary.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "freeze":
        payload = freeze_environment(Path(args.output_dir))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return run_benchmark(args)
    payload = summarize(Path(args.output_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
