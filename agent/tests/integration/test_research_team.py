"""Real orchestration/storage/tools with an explicitly injected deterministic model."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from agent.schemas.research import (
    ResearchRequest, SourceScope, ResearchPlan, ResearchTask, ResearchBudget,
    AcceptanceCriterion, ResearchPlanRevisionRequest,
)
from deep_research.execution import ResearchRuntimeService
from deep_research.model_budget import completion_budget_scope, ResearchTokenBudgetExceeded
from deep_research.model_client import ResearchModelClient
from deep_research.progress import ResearchProgressService
from deep_research.repository import ResearchNotFoundError, SQLiteResearchRepository
from deep_research.team_contracts import ReportReview


class TeamPlanner:
    def create_plan(self, request, manifest, *, version=1):
        return ResearchPlan(research_id=manifest.research_id, version=version,
            objective=request.query, source_scope=request.source_scope, manifest_hash=manifest.manifest_hash,
            execution_mode='coordinator', source_files=[{'doc_id': d.doc_id, 'title': d.title, 'version': d.version} for d in manifest.documents],
            budget=ResearchBudget(max_tasks=4, max_actions=60, max_tool_calls=60, max_review_rounds=2),
            tasks=[ResearchTask(task_id=f'task-{i}', question=f'Check the {d.title} access procedure.',
                purpose='Verify current source access requirements.', source_ids=[d.doc_id],
                allowed_tools=['keyword_search', 'read_document_range'], max_actions=4,
                acceptance_criteria=[AcceptanceCriterion(criterion_id=f'criterion-{i}', dimension='evidence',
                    target='Establish the documented native permission requirement.')]) for i, d in enumerate(manifest.documents, 1)])


class TeamModel:
    def __init__(self, reject_first=False, reject_always=False, approve=True, parallel=True):
        self.reject_first = reject_first
        self.reject_always = reject_always
        self.approve = approve
        self.barrier = Barrier(2) if parallel else None
        self.lock = Lock()
        self.calls = []

    def json(self, role, instructions, data):
        with self.lock:
            self.calls.append((role, data))
        if role == 'explorer':
            if not data['observations'] and not data['evidence']:
                if self.barrier:
                    self.barrier.wait(timeout=5)
                return {'action': 'search', 'query': 'native permission access procedure'}
            if not data['evidence']:
                candidate = data['observations'][-1]['candidates_not_evidence'][0]
                return {'action': 'read', 'doc_id': candidate['doc_id'], 'locator': candidate['locator']}
            evidence = data['evidence'][0]
            return {'action': 'finish', 'findings': [{'statement': 'The documented procedure requires current native read permission.',
                'evidence_ids': [evidence['evidence_id']], 'quotes': {evidence['evidence_id']: 'current native read permission'},
                'covers': [c['criterion_id'] for c in data['task']['acceptance_criteria']]}], 'missing': []}
        if role == 'reviewer':
            reject = self.reject_always or self.reject_first and len([r for r, _ in self.calls if r == 'reviewer']) == 1
            return {'status': 'not_passed' if reject else 'passed',
                'checked_citation_numbers': sorted({s['citation_number'] for s in data['fresh_originals']}),
                'checked_block_ids': list(range(len(data['report_blocks']))),
                'issues': [{'issue_id': 'unsupported-1', 'kind': 'unsupported', 'description': 'Permanent availability is not established.',
                    'suggestion': 'Describe only the documented access requirement.', 'block_ids': [0], 'evidence_ids': []}] if reject else []}
        if role == 'repair':
            return {'action': 'finish', 'edits': [{'block_id': 0, 'replacement':
                'The documented access procedure requires a current native permission check before sources can support an answer. [1]'}]}
        if role == 'coordinator':
            return {'approved': self.approve, 'issues': [] if self.approve else ['The approved objective is not fully addressed.']}
        raise AssertionError(role)

    def report(self, data, language):
        self.calls.append(('compose', data))
        return ('## Summary\n\n' + ('The service is permanently available. [1]' if self.reject_first else
            'The recorded access procedure requires current native source read permission before an answer can be released. [1]')
            + '\n\n## Evidence and analysis\n\nThe procedure combines source authorization with an evidence check before releasing information to the user. [1]'
            + '\n\n## Limitations and uncertainty\n\nThese documents describe access procedures; they do not establish current deployment availability or operational readiness. [1]')


def service(tmp_path, model):
    docs = tmp_path / 'documents'
    docs.mkdir()
    for name in ['alpha', 'beta']:
        (docs / f'{name}.json').write_text(json.dumps({'doc_id': name, 'title': name.title() + ' access guide',
            'content': f'The {name} procedure requires current native read permission and an evidence check before releasing answers. '
                       'This document does not establish current deployment availability.'}), encoding='utf-8')
    runtime = ResearchRuntimeService.from_local_catalog(database_path=tmp_path / 'research.db', documents_dir=docs,
        planner=TeamPlanner(), team_model=model)
    job = runtime.control_plane.create_job(ResearchRequest(query='Explain the documented access procedures and their limits.',
        source_scope=SourceScope(document_ids=['alpha', 'beta'])), user_id='alice')
    return runtime, job


def approve(runtime, job):
    plan = runtime.control_plane.get_plan(job.research_id)
    runtime.control_plane.approve_job(job.research_id, plan_version=plan.version,
        manifest_hash=plan.manifest_hash, approved_by='alice')


def test_parallel_explorers_review_repair_second_review_and_release(tmp_path):
    model = TeamModel(reject_first=True)
    runtime, job = service(tmp_path, model)
    review_progress = []
    def capture_review_progress(rid, stage):
        if stage == 'checkpoint:review_report':
            review_progress.append(ResearchProgressService(runtime.control_plane.repository).get_progress(rid))
    runtime.team_runtime.stage_hook = capture_review_progress
    try:
        assert not model.calls  # Approval is an actual execution barrier.
        approve(runtime, job)
        runtime.scan_once()
        repo = runtime.control_plane.repository
        completed = repo.get_job(job.research_id)
        assert completed.status == 'completed'
        drafts = repo.list_team_entities('report_draft', job.research_id)
        reviews = repo.list_team_entities('report_review', job.research_id)
        assert [r.status for r in reviews] == ['not_passed', 'passed']
        assert [d.revision for d in drafts] == [1, 2]
        assert drafts[1].author_agent_id != drafts[0].author_agent_id
        report = repo.get_report(job.research_id)
        assert report.review_status == 'passed' and report.coordinator_approved
        assert report.revision == 2 and report.review_id == reviews[1].review_id
        assert 'permanently' not in report.markdown
        assert len({d['agent_id'] for role, d in model.calls if role == 'explorer'}) == 2
        assert len([r for r, _ in model.calls if r == 'coordinator']) == 1
        assert len([r for r, _ in model.calls if r == 'repair']) == 1
        reviewer_inputs = [data for role, data in model.calls if role == 'reviewer']
        assert [data['report_markdown'] for data in reviewer_inputs] == [draft.report.markdown for draft in drafts]
        second_review_stages = {stage.key: stage.status for stage in review_progress[1].stages}
        assert second_review_stages['review_report'] == 'running'
        assert second_review_stages['repair_report'] == 'completed'
        summary = ResearchProgressService(repo).team_summary(job.research_id)
        assert summary['drafts'][0]['review_status'] == 'not_passed'
        assert summary['drafts'][1]['review_status'] == 'passed'
    finally:
        runtime.close()


@pytest.mark.parametrize('always_reject,main_approve', [(True, True), (False, False)])
def test_no_report_release_on_review_or_coordinator_rejection(tmp_path, always_reject, main_approve):
    runtime, job = service(tmp_path, TeamModel(reject_always=always_reject, approve=main_approve))
    try:
        approve(runtime, job)
        runtime.scan_once()
        repo = runtime.control_plane.repository
        assert repo.get_job(job.research_id).status == 'failed'
        with pytest.raises(ResearchNotFoundError):
            repo.get_report(job.research_id)
        assert len(repo.list_team_entities('report_draft', job.research_id)) <= 3
    finally:
        runtime.close()


def test_parallel_completion_reservations_are_atomic_and_survive_restart(tmp_path):
    repo = SQLiteResearchRepository(tmp_path / 'quota.db')
    from agent.schemas.research import ResearchJob
    request = ResearchRequest(query='Check current permission.', source_scope={'document_ids': ['alpha']})
    repo.create_job(ResearchJob(research_id='research-quota', user_id='alice', request=request))
    def reserve():
        try:
            return repo.reserve_model_tokens('research-quota', 700, 1000)
        except ResearchTokenBudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(i is not None for i in ids) == 1
    repo.close()
    repo = SQLiteResearchRepository(tmp_path / 'quota.db')
    assert repo.model_tokens_used('research-quota') == 700
    with pytest.raises(ResearchTokenBudgetExceeded):
        repo.reserve_model_tokens('research-quota', 400, 1000)
    repo.close()


def test_plan_revision_preserves_independence_and_invalidates_old_approval(tmp_path):
    runtime, job = service(tmp_path, TeamModel())
    try:
        current = runtime.control_plane.get_plan(job.research_id)
        revision = runtime.control_plane.revise_plan(job.research_id, ResearchPlanRevisionRequest(
            base_version=current.version, objective=current.objective, tasks=list(reversed(current.tasks)),
            report_spec=current.report_spec), revised_by='alice')
        assert all(not t.dependencies for t in revision.tasks)
        assert revision.execution_mode == 'coordinator'
        assert revision.source_files == current.source_files
        with pytest.raises(Exception, match='current plan_version'):
            runtime.control_plane.approve_job(job.research_id, plan_version=current.version,
                manifest_hash=current.manifest_hash, approved_by='alice')
        assert not runtime.team.model.calls
    finally:
        runtime.close()


def test_model_and_tool_thread_pools_keep_identity_and_shared_durable_budget(tmp_path, monkeypatch):
    from contextvars import ContextVar
    from types import SimpleNamespace
    import requests
    from deep_research.model_budget import post_completion
    marker = ContextVar('team-test-actor', default=None)
    class MeteredModel(TeamModel):
        def json(self, role, instructions, data):
            assert marker.get() == 'alice'
            post_completion('https://model.test', 'test-key', {'max_tokens': 100}, 1)
            return super().json(role, instructions, data)
    model = MeteredModel()
    runtime, job = service(tmp_path, model)
    backend = runtime.tool_adapter.search_backend
    original_search = backend.search
    def search(*args, **kwargs):
        assert marker.get() == 'alice'
        return original_search(*args, **kwargs)
    monkeypatch.setattr(backend, 'search', search)
    monkeypatch.setattr(requests.Session, 'post', lambda *a, **kw: SimpleNamespace(status_code=200,
        raise_for_status=lambda: None, json=lambda: {'choices': [], 'usage': {'completion_tokens': 10}}))
    token = marker.set('alice')
    try:
        approve(runtime, job)
        runtime.scan_once()
        assert runtime.control_plane.get_job(job.research_id).status == 'completed'
        assert runtime.control_plane.repository.model_tokens_used(job.research_id) == 80
    finally:
        marker.reset(token)
        runtime.close()


@pytest.mark.parametrize('defect', ['unread_evidence', 'incomplete_review', 'cancel_before_release'])
def test_untrusted_results_cannot_become_a_released_report(tmp_path, defect):
    class DefectiveModel(TeamModel):
        runtime = None
        rid = None
        def json(self, role, instructions, data):
            result = super().json(role, instructions, data)
            if defect == 'unread_evidence' and role == 'explorer' and result['action'] == 'finish':
                result['findings'][0]['evidence_ids'] = ['invented-evidence']
            if defect == 'incomplete_review' and role == 'reviewer':
                result['checked_block_ids'] = []
            if defect == 'cancel_before_release' and role == 'coordinator':
                self.runtime.control_plane.cancel_job(self.rid)
            return result
    model = DefectiveModel()
    runtime, job = service(tmp_path, model)
    model.runtime, model.rid = runtime, job.research_id
    try:
        approve(runtime, job)
        runtime.scan_once()
        assert runtime.control_plane.get_job(job.research_id).status in {'failed', 'cancelled'}
        with pytest.raises(ResearchNotFoundError):
            runtime.control_plane.repository.get_report(job.research_id)
    finally:
        runtime.close()


def test_restart_reuses_explorers_but_requires_review_of_repaired_revision(tmp_path):
    class ProcessStopped(BaseException):
        pass
    model = TeamModel(reject_first=True)
    runtime, job = service(tmp_path, model)
    def interrupt(rid, stage):
        if stage == 'checkpoint:repair_report':
            runtime.control_plane.repository.reserve_model_tokens(rid, 800, 64000)
            raise ProcessStopped()
    runtime.team_runtime.stage_hook = interrupt
    approve(runtime, job)
    try:
        with pytest.raises(ProcessStopped):
            runtime.scan_once()
        assert runtime.control_plane.get_job(job.research_id).status == 'synthesizing'
        with pytest.raises(ResearchNotFoundError):
            runtime.control_plane.repository.get_report(job.research_id)
    finally:
        runtime.close()
    resumed_model = TeamModel(parallel=False)
    resumed = ResearchRuntimeService.from_local_catalog(database_path=tmp_path / 'research.db',
        documents_dir=tmp_path / 'documents', planner=TeamPlanner(), team_model=resumed_model)
    try:
        resumed.scan_once()
        assert resumed.control_plane.get_job(job.research_id).status == 'completed'
        assert not any(role == 'explorer' for role, _ in resumed_model.calls)
        assert sum(role == 'reviewer' for role, _ in resumed_model.calls) == 1
        assert resumed.control_plane.repository.model_tokens_used(job.research_id) == 800
        assert resumed.control_plane.repository.get_report(job.research_id).revision == 2
    finally:
        resumed.close()


def test_model_planner_receives_catalogue_and_returns_independent_strict_plan(tmp_path, monkeypatch):
    from deep_research.planner import ModelResearchPlanner, PlannerError
    runtime, job = service(tmp_path, TeamModel())
    try:
        planner = ModelResearchPlanner(api_base='https://model.test', api_key='test', model='thinking')
        calls = []
        def chat(payload):
            calls.append(payload)
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'tasks': [
                {'task_id': f'task-{i}', 'question': f'Check the {name} access requirements.',
                 'purpose': 'Establish documented permission checks.', 'dependencies': [], 'source_numbers': [i],
                 'criteria': ['Determine the native read permission requirement.']} for i, name in enumerate(['alpha', 'beta'], 1)]})}}]}
        monkeypatch.setattr(planner, '_chat', chat)
        plan = planner.create_plan(job.request, runtime.control_plane.get_manifest(job.research_id))
        packet = json.loads(calls[0]['messages'][1]['content'])
        assert len(packet['files']) == len(plan.source_files) == 2
        assert packet['question'] == job.request.query
        assert all(not t.dependencies for t in plan.tasks)
        monkeypatch.setattr(planner, '_chat', lambda _: (_ for _ in ()).throw(RuntimeError('quota unavailable')))
        with pytest.raises(PlannerError):
            planner.create_plan(job.request, runtime.control_plane.get_manifest(job.research_id))
    finally:
        runtime.close()


def test_cancel_racing_stage_write_cannot_resurrect_execution(tmp_path, monkeypatch):
    model = TeamModel()
    runtime, job = service(tmp_path, model)
    repo = runtime.control_plane.repository
    original = repo.transition_job
    cancelled = False
    def transition(rid, **kwargs):
        nonlocal cancelled
        if kwargs.get('current_stage') == 'parallel_exploration' and not cancelled:
            cancelled = True
            runtime.control_plane.cancel_job(rid)
        return original(rid, **kwargs)
    monkeypatch.setattr(repo, 'transition_job', transition)
    try:
        approve(runtime, job)
        runtime.scan_once()
        assert repo.get_job(job.research_id).status == 'cancelled'
        assert not model.calls
        with pytest.raises(ResearchNotFoundError):
            repo.get_report(job.research_id)
    finally:
        runtime.close()


def test_released_report_mutation_cannot_reuse_an_old_review(tmp_path):
    from deep_research.repository import ResearchConflictError
    runtime, job = service(tmp_path, TeamModel())
    try:
        approve(runtime, job)
        runtime.scan_once()
        repo = runtime.control_plane.repository
        report = repo.get_report(job.research_id)
        with pytest.raises(ResearchConflictError, match='requires_bound_review'):
            repo.save_report(report.model_copy(update={'markdown': report.markdown + '\n\nUnreviewed content. [1]'}))
        assert repo.get_report(job.research_id) == report
    finally:
        runtime.close()


def test_crash_after_report_storage_still_requires_completed_release_and_recovers(tmp_path, monkeypatch):
    from deep_research.access import ResearchAccessPolicy, ResearchAccessError
    class ProcessStopped(BaseException):
        pass
    model = TeamModel()
    runtime, job = service(tmp_path, model)
    def interrupt(rid, stage):
        if stage == 'report_persisted':
            raise ProcessStopped()
    runtime.team_runtime.stage_hook = interrupt
    approve(runtime, job)
    try:
        with pytest.raises(ProcessStopped):
            runtime.scan_once()
        repo = runtime.control_plane.repository
        report = repo.get_report(job.research_id)
        access = ResearchAccessPolicy()
        monkeypatch.setattr(access, 'authorize_job', lambda *args: {'alpha', 'beta'})
        with pytest.raises(ResearchAccessError, match='not_released'):
            access.validate_report(report, repo.get_job(job.research_id), runtime.control_plane.get_manifest(job.research_id))
    finally:
        runtime.close()
    resumed_model = TeamModel(parallel=False)
    resumed = ResearchRuntimeService.from_local_catalog(database_path=tmp_path / 'research.db',
        documents_dir=tmp_path / 'documents', planner=TeamPlanner(), team_model=resumed_model)
    try:
        resumed.scan_once()
        assert resumed.control_plane.get_job(job.research_id).status == 'completed'
        assert not resumed_model.calls
        access.validate_report(resumed.control_plane.repository.get_report(job.research_id),
            resumed.control_plane.get_job(job.research_id), resumed.control_plane.get_manifest(job.research_id))
    finally:
        resumed.close()


def test_legacy_approval_cannot_be_reinterpreted_as_harness_authorization(tmp_path, monkeypatch):
    from deep_research.service import ResearchControlPlaneError
    create = TeamPlanner.create_plan
    monkeypatch.setattr(TeamPlanner, 'create_plan', lambda self, *a, **kw:
        create(self, *a, **kw).model_copy(update={'execution_mode': 'legacy'}))
    model = TeamModel()
    runtime, job = service(tmp_path, model)
    try:
        with pytest.raises(ResearchControlPlaneError, match='retired workflow'):
            approve(runtime, job)
        assert runtime.control_plane.get_job(job.research_id).status == 'awaiting_approval'
        assert not model.calls
    finally:
        runtime.close()


def test_reviewer_reads_consume_shared_explorer_tool_budget(tmp_path, monkeypatch):
    create = TeamPlanner.create_plan
    def limited(self, *args, **kwargs):
        plan = create(self, *args, **kwargs)
        return plan.model_copy(update={'budget': plan.budget.model_copy(update={'max_tool_calls': 4})})
    monkeypatch.setattr(TeamPlanner, 'create_plan', limited)
    runtime, job = service(tmp_path, TeamModel())
    try:
        approve(runtime, job)
        runtime.scan_once()
        repo = runtime.control_plane.repository
        assert repo.get_job(job.research_id).status == 'failed'
        assert len(repo.list_team_entities('report_draft', job.research_id)) == 1
        with pytest.raises(ResearchNotFoundError):
            repo.get_report(job.research_id)
    finally:
        runtime.close()


def test_failed_dependency_blocks_every_descendant_without_starting_agents(tmp_path, monkeypatch):
    create = TeamPlanner.create_plan
    def chain(self, *args, **kwargs):
        plan = create(self, *args, **kwargs)
        second = plan.tasks[1].model_copy(update={'dependencies': [plan.tasks[0].task_id]})
        third = second.model_copy(update={'task_id': 'task-3', 'question': 'Determine unresolved source limitations.',
            'dependencies': [second.task_id], 'acceptance_criteria': [AcceptanceCriterion(criterion_id='criterion-3',
                dimension='evidence', target='Record remaining limitations.')]})
        return plan.model_copy(update={'tasks': [plan.tasks[0], second, third]})
    monkeypatch.setattr(TeamPlanner, 'create_plan', chain)
    class FailingExplorer(TeamModel):
        def json(self, role, instructions, data):
            self.calls.append((role, data))
            return {'action': 'invalid'}
    model = FailingExplorer(parallel=False)
    runtime, job = service(tmp_path, model)
    try:
        approve(runtime, job)
        runtime.scan_once()
        results = runtime.control_plane.repository.list_team_entities('agent_result', job.research_id)
        assert {r.task_id: r.status for r in results} == {'task-1': 'failed', 'task-2': 'blocked', 'task-3': 'blocked'}
        assert [data['task']['task_id'] for role, data in model.calls if role == 'explorer'] == ['task-1']
        with pytest.raises(ResearchNotFoundError):
            runtime.control_plane.repository.get_report(job.research_id)
    finally:
        runtime.close()


@pytest.mark.parametrize('drift_during_review', [False, True])
def test_development_full_catalog_executes_harness_but_still_rechecks_sources(tmp_path, monkeypatch, drift_during_review):
    import sqlite3
    from types import SimpleNamespace
    from unittest.mock import Mock
    from agent.config.settings import settings
    from agent.service.permission_service import PermissionService
    from deep_research.access import ResearchAccessPolicy
    monkeypatch.setattr(settings, 'RESEARCH_DEVELOPMENT_MODE', True)
    monkeypatch.setattr(settings, 'HOST', '127.0.0.1')
    class DevelopmentModel(TeamModel):
        def json(self, role, instructions, data):
            result = super().json(role, instructions, data)
            if role == 'reviewer' and drift_during_review:
                path = tmp_path / 'documents' / 'alpha.json'
                payload = json.loads(path.read_text(encoding='utf-8'))
                payload['content'] = 'Source content changed during review.'
                path.write_text(json.dumps(payload), encoding='utf-8')
            return result
    runtime, job = service(tmp_path, DevelopmentModel())
    db = tmp_path / 'web.db'
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE users (id TEXT, disabled INTEGER); INSERT INTO users VALUES ('alice',0);")
    provider = SimpleNamespace(list_document_ids=lambda: ['alpha', 'beta'],
        _load=lambda doc_id: json.loads((tmp_path / 'documents' / f'{doc_id}.json').read_text(encoding='utf-8')))
    permissions = PermissionService(str(db), source_provider=provider)
    native = Mock(side_effect=AssertionError('No native grant is required in development.'))
    monkeypatch.setattr(permissions, 'get_accessible_doc_ids_strict', native)
    runtime.control_plane.access_policy = ResearchAccessPolicy(permissions)
    try:
        approve(runtime, job)
        runtime.scan_once()
        assert runtime.control_plane.get_job(job.research_id).status == ('failed' if drift_during_review else 'completed')
        if drift_during_review:
            with pytest.raises(ResearchNotFoundError):
                runtime.control_plane.repository.get_report(job.research_id)
        else:
            assert runtime.control_plane.repository.get_report(job.research_id).review_status == 'passed'
        native.assert_not_called()
    finally:
        runtime.close()
