"""Run the complete Local Deep Research vertical slice through FastAPI.

The API service must already be running.  This script deliberately uses HTTP
instead of importing application services, so it exercises the same boundary
as a real client: create -> plan -> approve -> execute -> report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def configure_console() -> None:
    """Keep Chinese progress and Markdown readable in Windows terminals."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if user_id:
        headers["X-User-ID"] = user_id
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"无法连接 FastAPI：{url}。请先启动 uvicorn。"
        ) from exc


def wait_for_status(
    base_url: str,
    research_id: str,
    *,
    expected: set[str],
    timeout_seconds: float,
    interval_seconds: float,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    previous: tuple[Any, ...] | None = None
    while time.monotonic() < deadline:
        job = request_json(
            "GET", f"{base_url}/api/research/jobs/{research_id}"
        )
        snapshot = (
            job.get("status"),
            job.get("current_stage"),
            job.get("task_completed"),
            job.get("task_total"),
            job.get("evidence_count"),
            job.get("result_status"),
        )
        if snapshot != previous:
            print(
                f"[{label}] status={snapshot[0]} stage={snapshot[1] or '-'} "
                f"tasks={snapshot[2]}/{snapshot[3]} evidence={snapshot[4]} "
                f"result={snapshot[5] or '-'}",
                flush=True,
            )
            previous = snapshot
        status = str(job.get("status", ""))
        if status in expected:
            return job
        if status in TERMINAL_STATUSES:
            raise RuntimeError(
                "任务在到达预期状态前结束："
                f"status={status}, stage={job.get('failure_stage')}, "
                f"error={job.get('error_code')}"
            )
        time.sleep(interval_seconds)
    raise TimeoutError(f"等待 {label} 超时（{timeout_seconds:.0f} 秒）")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 FastAPI 演示完整 Deep Research 纵向链路。"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument(
        "--query",
        default="比较 Alpha 与 Beta 的部署状态，并给出原文依据",
    )
    parser.add_argument(
        "--document-id",
        action="append",
        dest="document_ids",
        help="可重复传入；默认使用 project-alpha 和 project-beta。",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument(
        "--save-report",
        type=Path,
        help="可选：把最终 Markdown 报告保存到指定文件。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    document_ids = args.document_ids or ["project-alpha", "project-beta"]

    print("\n=== CP2 Deep Research 完整链路测试 ===")
    health = request_json("GET", f"{base_url}/health")
    print(f"[1/7] FastAPI 健康检查通过：{health}")

    created = request_json(
        "POST",
        f"{base_url}/api/research/jobs",
        user_id=args.user_id,
        body={
            "query": args.query,
            "source_scope": {"document_ids": document_ids},
        },
    )
    research_id = str(created["research_id"])
    print(f"[2/7] Job 已创建：research_id={research_id}")

    planned = wait_for_status(
        base_url,
        research_id,
        expected={"awaiting_approval"},
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
        label="规划",
    )
    print(
        f"[3/7] 资料快照与计划已生成：manifest={planned.get('manifest_hash')}"
    )

    plan = request_json(
        "GET", f"{base_url}/api/research/jobs/{research_id}/plan"
    )
    tasks = plan.get("tasks") or []
    print(
        f"[4/7] Plan v{plan.get('version')}，共 {len(tasks)} 个任务："
    )
    for task in tasks:
        dependencies = ",".join(task.get("dependencies") or []) or "无"
        print(
            f"      - {task.get('task_id')}: {task.get('question')} "
            f"(依赖={dependencies})"
        )

    approved = request_json(
        "POST",
        f"{base_url}/api/research/jobs/{research_id}/approve",
        user_id=args.user_id,
        body={
            "plan_version": plan["version"],
            "manifest_hash": plan["manifest_hash"],
        },
    )
    if approved.get("status") != "ready":
        raise RuntimeError(f"审批后状态不是 ready：{approved}")
    print("[5/7] Plan 与 SourceManifest 审批成功，等待 Dispatcher 执行")

    completed = wait_for_status(
        base_url,
        research_id,
        expected={"completed"},
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
        label="执行",
    )
    if completed.get("task_completed") != completed.get("task_total"):
        raise RuntimeError("Job completed，但任务完成数与总数不一致")
    if int(completed.get("evidence_count") or 0) < 1:
        raise RuntimeError("Job completed，但没有生成 Verified Evidence")
    print(
        "[6/7] 执行完成："
        f"result={completed.get('result_status')}，"
        f"tasks={completed.get('task_completed')}/{completed.get('task_total')}，"
        f"evidence={completed.get('evidence_count')}"
    )

    report = request_json(
        "GET", f"{base_url}/api/research/jobs/{research_id}/report"
    )
    markdown = str(report.get("markdown") or "")
    if "[E:evidence-" not in markdown:
        raise RuntimeError("报告缺少 Evidence 引用")
    for doc_id in document_ids:
        if f"{doc_id} / line:" not in markdown:
            raise RuntimeError(f"报告证据索引缺少文档定位：{doc_id}")
    print("[7/7] 报告校验通过：包含 Evidence 引用和原文定位")

    if args.save_report:
        args.save_report.parent.mkdir(parents=True, exist_ok=True)
        args.save_report.write_text(markdown, encoding="utf-8")
        print(f"报告已保存：{args.save_report.resolve()}")

    print("\n=== 最终 Markdown 报告 ===\n")
    print(markdown)
    print("=== 完整链路测试通过 ===")
    return 0


if __name__ == "__main__":
    configure_console()
    try:
        raise SystemExit(main())
    except (RuntimeError, TimeoutError, KeyError, ValueError) as exc:
        print(f"\n完整链路测试失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
