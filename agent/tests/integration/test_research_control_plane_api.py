from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.research_routes import get_research_control_plane, router
from deep_research.manifest import InMemoryDocumentResolver
from deep_research.repository import SQLiteResearchRepository
from deep_research.service import ResearchControlPlane


def _client(tmp_path: Path) -> tuple[TestClient, ResearchControlPlane]:
    control_plane = ResearchControlPlane(
        SQLiteResearchRepository(tmp_path / "research.db"),
        source_resolver=InMemoryDocumentResolver(
            {
                "doc-a": {
                    "doc_id": "doc-a",
                    "title": "Local A",
                    "content": "A 的收入为 10。",
                },
                "doc-b": {
                    "doc_id": "doc-b",
                    "title": "Local B",
                    "content": "B 的收入为 20。",
                },
            }
        ),
    )
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_research_control_plane] = lambda: control_plane
    return TestClient(application), control_plane


def test_api_create_view_and_approve_real_control_plane_entities(tmp_path: Path) -> None:
    client, control_plane = _client(tmp_path)
    response = client.post(
        "/api/research/jobs",
        headers={"X-User-ID": "alice"},
        json={
            "query": "比较 A 和 B 的收入",
            "source_scope": {"document_ids": ["doc-a", "doc-b"]},
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "created"
    assert job["plan_version"] is None
    assert job["manifest_hash"] is None

    control_plane.resume_planning_job(job["research_id"])
    planned_job = client.get(f"/api/research/jobs/{job['research_id']}").json()
    assert planned_job["status"] == "awaiting_approval"
    assert planned_job["plan_version"] == 1
    assert planned_job["manifest_hash"]

    plan_response = client.get(f"/api/research/jobs/{job['research_id']}/plan")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["research_id"] == job["research_id"]
    assert plan["manifest_hash"] == planned_job["manifest_hash"]
    assert len(plan["tasks"]) == 3

    wrong = client.post(
        f"/api/research/jobs/{job['research_id']}/approve",
        json={"plan_version": 1, "manifest_hash": "wrong-hash"},
    )
    assert wrong.status_code == 409
    assert wrong.json()["detail"]["code"] == "research_manifest_hash_conflict"

    approved = client.post(
        f"/api/research/jobs/{job['research_id']}/approve",
        headers={"X-User-ID": "alice"},
        json={
            "plan_version": 1,
            "manifest_hash": planned_job["manifest_hash"],
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"

    trace = client.get(f"/api/research/jobs/{job['research_id']}/evaluation-trace")
    assert trace.status_code == 200
    assert trace.json() == {
        "observations": [], "verified_evidence": [], "findings": [],
        "claims": [], "verifications": [],
    }


def test_api_cannot_create_job_from_external_source_scope(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        "/api/research/jobs",
        json={
            "query": "禁止网络来源",
            "source_scope": {"document_ids": ["https://example.com"]},
        },
    )
    assert response.status_code == 422


def test_api_opens_complete_source_only_inside_frozen_manifest(tmp_path: Path) -> None:
    client, control_plane = _client(tmp_path)
    created = client.post(
        "/api/research/jobs",
        json={
            "query": "核验 A",
            "source_scope": {"document_ids": ["doc-a"]},
        },
    ).json()
    control_plane.resume_planning_job(created["research_id"])

    source = client.get(
        f"/api/research/jobs/{created['research_id']}/documents/doc-a/source"
    )
    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/plain")
    assert source.text == "A 的收入为 10。"

    outside_manifest = client.get(
        f"/api/research/jobs/{created['research_id']}/documents/doc-b/source"
    )
    assert outside_manifest.status_code == 404


def test_api_revision_creates_v2_and_rejects_old_approval(tmp_path: Path) -> None:
    client, control_plane = _client(tmp_path)
    created = client.post(
        "/api/research/jobs",
        json={
            "query": "比较 A 和 B 的收入",
            "source_scope": {"document_ids": ["doc-a", "doc-b"]},
        },
    ).json()
    control_plane.resume_planning_job(created["research_id"])
    plan = client.get(
        f"/api/research/jobs/{created['research_id']}/plan"
    ).json()
    plan["tasks"][0]["question"] = "先核验 A 的收入和版本"

    revised = client.post(
        f"/api/research/jobs/{created['research_id']}/plan/revisions",
        headers={"X-User-ID": "alice"},
        json={
            "base_version": 1,
            "objective": "比较 A、B 收入并核验版本",
            "tasks": plan["tasks"],
            "report_spec": plan["report_spec"],
            "revision_note": "增加版本核验",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["version"] == 2

    old_approval = client.post(
        f"/api/research/jobs/{created['research_id']}/approve",
        json={"plan_version": 1, "manifest_hash": plan["manifest_hash"]},
    )
    assert old_approval.status_code == 409
    assert old_approval.json()["detail"]["code"] == "research_plan_version_conflict"

    approved = client.post(
        f"/api/research/jobs/{created['research_id']}/approve",
        json={"plan_version": 2, "manifest_hash": plan["manifest_hash"]},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"


def test_conflict_choice_persists_report_without_clearing_quality_gaps(tmp_path: Path) -> None:
    from agent.schemas.research import (
        ResearchCitation, ResearchConflict, ResearchConflictAlternative,
        ResearchJobStatus, ResearchLimitation, ResearchReport, ResearchResultStatus,
    )

    client, control_plane = _client(tmp_path)
    created = client.post('/api/research/jobs', json={
        'query': '比较 A 和 B 的收入',
        'source_scope': {'document_ids': ['doc-a', 'doc-b']},
    }).json()
    research_id = created['research_id']
    repository = control_plane.repository
    job = repository.get_job(research_id)
    repository.update_job(job.model_copy(update={
        'status': ResearchJobStatus.COMPLETED,
        'current_stage': 'completed',
        'result_status': ResearchResultStatus.DEGRADED,
    }))
    citations = [ResearchCitation(
        number=i, evidence_id=f'evidence-{i}', doc_id=doc_id,
        title=f'Source {i}', locator='line:1-1', excerpt=f'收入 {i * 10}',
        content_hash='12345678',
    ) for i, doc_id in enumerate(['doc-a', 'doc-b'], 1)]
    report = ResearchReport(
        report_id='report-original', research_id=research_id,
        markdown='# Income\n\n来源 [1] 与 [2] 不一致。\n',
        result_status=ResearchResultStatus.DEGRADED,
        citations=citations,
        evidence_ids=['evidence-1', 'evidence-2'],
        conflicts=[ResearchConflict(
            conflict_id='conflict-income', subject='收入', summary='两个来源不一致',
            alternatives=[ResearchConflictAlternative(
                citation_number=i, evidence_id=f'evidence-{i}',
                source_title=f'Source {i}', value_summary=f'收入 {i * 10}',
            ) for i in (1, 2)],
        )],
        limitations=[ResearchLimitation(code='required_coverage_missing', message='缺少日期')],
    )
    repository.save_report(report)
    try:
        invalid = client.post(f'/api/research/jobs/{research_id}/messages', json={'message': '采用来源 9'})
        assert invalid.status_code == 200
        assert invalid.json()['action'] == 'clarify'
        assert repository.get_report(research_id).report_id == 'report-original'

        response = client.post(f'/api/research/jobs/{research_id}/messages', json={'message': '采用来源 2'})
        assert response.status_code == 200
        assert response.json()['action'] == 'conflict_resolved'
        persisted = client.get(f'/api/research/jobs/{research_id}/report').json()
        assert persisted['report_id'] != 'report-original'
        assert persisted['conflicts'][0]['resolution_status'] == 'resolved_by_user'
        assert '采用来源 [2]' in persisted['markdown']
        assert persisted['result_status'] == 'degraded'
        assert persisted['limitations'][0]['code'] == 'required_coverage_missing'
        assert persisted['citations'] == report.model_dump(mode='json')['citations']
        assert repository.get_report(research_id).evidence_ids == report.evidence_ids
        events = repository.list_events(research_id)
        assert any(event.event_type.value == 'conflict_resolved' for event in events)
    finally:
        repository.close()


def test_english_research_conversation_approve_and_cancel(tmp_path: Path) -> None:
    client, control_plane = _client(tmp_path)
    try:
        for command, expected in [('approve', 'approved'), ('cancel', 'cancelled')]:
            created = client.post('/api/research/jobs', json={
                'query': 'Compare source A and B.',
                'source_scope': {'document_ids': ['doc-a', 'doc-b']},
                'report_spec': {'language': 'en-US'},
            }).json()
            research_id = created['research_id']
            control_plane.resume_planning_job(research_id)
            response = client.post(f'/api/research/jobs/{research_id}/messages', json={'message': command})
            assert response.status_code == 200
            assert response.json()['action'] == expected
            assert not __import__('re').search(r'[\u3400-\u9fff]', response.json()['message'])
    finally:
        control_plane.repository.close()


def test_english_followup_distinguishes_provider_failure_from_missing_evidence(monkeypatch):
    from agent.api.research_routes import _answer_report_followup, EvidenceReportSynthesizer, settings
    from agent.schemas.research import ResearchCitation, ResearchReport, ResearchResultStatus
    report = ResearchReport(
        report_id='report-test', research_id='research-test', markdown='Count: 9 [1]',
        result_status=ResearchResultStatus.COMPLETE, evidence_ids=['ev1'],
        citations=[ResearchCitation(number=1, evidence_id='ev1', doc_id='doc-a', title='Source A', locator='line:1', excerpt='Total commits: 9', content_hash='12345678')],
    )
    monkeypatch.setattr(settings, 'LLM_API_KEY', 'test-only')
    prompts = []
    def unavailable(self, payload):
        prompts.append(payload['messages'][0]['content'])
        raise RuntimeError('provider quota exhausted')
    monkeypatch.setattr(EvidenceReportSynthesizer, '_chat', unavailable)
    answer = _answer_report_followup(report, 'What is the count?', 'en-US')
    assert 'quota' in answer
    assert 'English' in prompts[0]
    assert 'Chinese' not in prompts[0]
    assert 'does not reliably answer' not in answer


def test_followup_receives_report_context_and_rejects_unknown_citation(monkeypatch):
    from agent.api.research_routes import _answer_report_followup, EvidenceReportSynthesizer, settings
    from agent.schemas.research import ResearchCitation, ResearchReport, ResearchResultStatus
    report = ResearchReport(report_id='report-test', research_id='research-test', markdown='Release B minus A: -2 [3]', result_status=ResearchResultStatus.COMPLETE, evidence_ids=['ev1'], citations=[ResearchCitation(number=3, evidence_id='ev1', doc_id='doc-a', title='Counts', locator='line:1', excerpt='A: 7; B: 5', content_hash='12345678')])
    monkeypatch.setattr(settings, 'LLM_API_KEY', 'test-only')
    prompts = []
    def answer(self, payload):
        prompts.append(payload['messages'][0]['content'])
        return {'choices': [{'message': {'content': 'B minus A is -2 [3].'}}]}
    monkeypatch.setattr(EvidenceReportSynthesizer, '_chat', answer)
    assert _answer_report_followup(report, 'Repeat the change in this report.', objective='Compare releases A and B.') == 'B minus A is -2 [3].'
    assert report.markdown in prompts[0]
    assert 'Compare releases A and B.' in prompts[0]
    assert 'direction of subtraction' in prompts[0]
    monkeypatch.setattr(EvidenceReportSynthesizer, '_chat', lambda *args: {'choices': [{'message': {'content': 'A false claim [1].'}}]})
    assert 'does not reliably answer' in _answer_report_followup(report, 'Repeat the change.')


def test_long_research_conversation_keeps_complete_bodies_and_bounded_progress(tmp_path, monkeypatch):
    from agent.schemas.research import ResearchJobStatus, ResearchReport, ResearchResultStatus
    import agent.api.research_routes as routes
    client, control_plane = _client(tmp_path)
    repository = control_plane.repository
    answer = 'The dependency is unverified; the workflow is hard-coded. [1]\n\n' * 20
    question = 'Explain the confirmed state and the remaining limitations. ' * 12
    monkeypatch.setattr(routes, '_answer_report_followup', lambda *args, **kwargs: answer)
    try:
        created = client.post('/api/research/jobs', json={'query': 'Compare A and B.', 'source_scope': {'document_ids': ['doc-a', 'doc-b']}}).json()
        rid = created['research_id']
        job = repository.get_job(rid)
        repository.update_job(job.model_copy(update={'status': ResearchJobStatus.COMPLETED, 'current_stage': 'completed'}))
        repository.save_report(ResearchReport(report_id='r', research_id=rid, markdown='Report', result_status=ResearchResultStatus.COMPLETE))
        response = client.post(f'/api/research/jobs/{rid}/messages', json={'message': question})
        assert response.status_code == 200
        assert response.json()['message'] == answer
        events = client.get(f'/api/research/jobs/{rid}/events').json()['events']
        conversation = [e for e in events if e['event_type'] in {'user_message', 'assistant_message'}]
        assert len(conversation) == 2
        assert all(len(e['message']) <= 500 for e in conversation)
        assert conversation[0]['payload']['content'] == question.strip()
        assert conversation[1]['payload']['content'] == answer
        # Reproduce the legacy writer: SQLite stored the full body before its
        # post-insert schema validation raised. Reload must recover that row.
        repository._connection.execute('update research_events set message=?, payload_json=? where event_id=?',
                                       (answer, '{"action":"followup_answered"}', conversation[1]['event_id']))
        repository._connection.commit()
        restored = client.get(f'/api/research/jobs/{rid}/events')
        assert restored.status_code == 200
        legacy = next(e for e in restored.json()['events'] if e['event_id'] == conversation[1]['event_id'])
        assert len(legacy['message']) == 500
        assert legacy['payload']['content'] == answer
    finally:
        repository.close()
