from __future__ import annotations

import json
from pathlib import Path
import sys
import pytest


AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from eval.deep_research_benchmark import _case_scope, summarize


@pytest.mark.parametrize('provider_error,expected_runs',[
    ('insufficient_quota',1), ('temporary upstream error',4),
])
def test_benchmark_preserves_failed_run_and_stops_only_on_provider_quota(tmp_path,monkeypatch,provider_error,expected_runs):
    from argparse import Namespace
    from eval import deep_research_benchmark as benchmark
    dataset = tmp_path/'cases.json'
    dataset.write_text(json.dumps({'cases':[{'case_id':'one','question':'Question one'},
        {'case_id':'two','question':'Question two'}]}),encoding='utf8')
    monkeypatch.setattr(benchmark,'freeze_environment',lambda path:{'config_hash':'test'})
    def failed(*args):
        raise benchmark.BenchmarkRunError('fast_stream_terminal_status:None',partial_result={
            'stream_events':[{'event':'error','data':{'message':provider_error}}],
            'citations':[{'snippet':'Source text may contain insufficient_quota without a provider quota error.'}]})
    monkeypatch.setattr(benchmark,'_run_fast_chat',failed)
    output = tmp_path/'results'
    assert benchmark.run_benchmark(Namespace(dataset=dataset,case_ids=None,groups=['fast_chat'],
        output_dir=output,base_url='http://unused',request_timeout=1,repetitions=2,
        top_k=5,parallel_groups=False)) == 1
    records = list((output/'runs').glob('*/*/*.json'))
    assert len(records) == expected_runs
    assert all(not json.loads(path.read_text())['success'] for path in records)
    assert (output/'provider_interruption.json').exists() == (provider_error=='insufficient_quota')


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


def test_resume_skips_only_completed_repetitions_without_fabricating_runs(tmp_path,monkeypatch):
    from argparse import Namespace
    from eval import deep_research_benchmark as benchmark
    dataset=tmp_path/'cases.json';dataset.write_text(json.dumps({'cases':[{'case_id':'one','question':'Question'}]}))
    completed=tmp_path/'completed.json';completed.write_text(json.dumps([{'case_id':'one','group':'fast_chat','repetition':1,'origin':'previous-model-real-record'}]))
    calls=[]
    monkeypatch.setattr(benchmark,'freeze_environment',lambda path:{'config_hash':'test'})
    monkeypatch.setattr(benchmark,'_run_fast_chat',lambda *args:calls.append(args) or {'response':{'answer':'Recorded.'}})
    output=tmp_path/'out'
    assert benchmark.run_benchmark(Namespace(dataset=dataset,case_ids=None,groups=['fast_chat'],output_dir=output,
        base_url='http://unused',request_timeout=1,repetitions=3,top_k=5,parallel_groups=False,completed_coordinates=completed))==0
    records=[json.loads(p.read_text()) for p in (output/'runs').glob('*/*/*.json')]
    assert len(calls)==2
    assert sorted(r['repetition'] for r in records)==[2,3]
    assert json.loads((output/'completed_coordinates.json').read_text())[0]['origin']=='previous-model-real-record'


def test_case_scope_accepts_frozen_a_side_manifest_reference() -> None:
    scope = _case_scope(
        {
            "case_id": "DR-A-001",
            "category": "multi_document_summary",
            "source_manifest": "manifest:DR-A-001",
            "allowed_document_ids": ["doc-1", "doc-2"],
        }
    )
    assert scope == {
        "document_ids": ["doc-1", "doc-2"],
        "knowledge_base_ids": ["RAG"],
        "topic": "multi_document_summary",
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
