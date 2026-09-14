from __future__ import annotations

import json
from pathlib import Path
import sys


AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from eval.deep_research_benchmark import _case_scope, summarize


def test_case_scope_normalizes_explicit_document_scope() -> None:
    scope = _case_scope(
        {
            "case_id": "case-1",
            "source_scope": {
                "document_ids": [123, "doc-2"],
                "knowledge_base_ids": ["RAG"],
            },
        }
    )
    assert scope == {
        "document_ids": ["123", "doc-2"],
        "knowledge_base_ids": ["RAG"],
        "topic": "",
    }


def test_summary_keeps_failures_and_broken_links(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "deep_research_current" / "case-1"
    run_dir.mkdir(parents=True)
    (run_dir / "ok.json").write_text(
        json.dumps(
            {
                "group": "deep_research_current",
                "success": True,
                "elapsed_ms": 120,
                "result": {
                    "source_checks": [
                        {"url": "https://example.test/a", "ok": True},
                        {"url": "", "ok": False},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "failed.json").write_text(
        json.dumps(
            {
                "group": "deep_research_current",
                "success": False,
                "elapsed_ms": 80,
                "result": None,
                "error": {"type": "RuntimeError", "message": "provider failed"},
            }
        ),
        encoding="utf-8",
    )

    summary = summarize(tmp_path)
    group = summary["groups"]["deep_research_current"]
    assert group["runs"] == 2
    assert group["successful_runs"] == 1
    assert group["failed_runs"] == 1
    assert group["broken_source_links"] == 1
    assert group["latency_mean_ms"] == 100
