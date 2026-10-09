"""Security tests use production guards/SQL, not the component authorization double."""
import sqlite3
import time
from types import SimpleNamespace

import pytest

from agent.schemas.chat import ChatRequest, InternalChatRequest, SourceDependency
from agent.service.access_guard import AccessGuard, CURRENT_ACCESS_GUARD, check_model_access
from agent.service.permission_service import PermissionService, PermissionResolutionError
from agent.service.source_access import SourceAccessProvider
from toolset.tool_layer.evidence_metadata import source_metadata


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / 'acl.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
          CREATE TABLE users(id TEXT PRIMARY KEY,role TEXT,disabled INTEGER);
          CREATE TABLE files(id TEXT PRIMARY KEY,user_id TEXT,doc_id TEXT,visibility TEXT);
          CREATE TABLE file_permissions(file_id TEXT,grant_type TEXT,grant_id TEXT);
          CREATE TABLE user_departments(user_id TEXT,department_id TEXT);
          CREATE TABLE topic_members(topic_id TEXT,user_id TEXT,role TEXT);
          CREATE TABLE attachments(id TEXT,owner_id TEXT,scope TEXT,chat_id TEXT,topic_id TEXT,status TEXT,evidence_version INTEGER,expires_at INTEGER,deleted_at INTEGER);
          CREATE TABLE knowledge_bases(id TEXT,owner_user_id TEXT,deleted_at INTEGER);
          CREATE TABLE library_documents(id TEXT,owner_user_id TEXT,knowledge_base_id TEXT,deleted_at INTEGER,active_version_id TEXT,source_scope TEXT);
          CREATE TABLE document_versions(id TEXT,content_hash TEXT,status TEXT,storage_ref TEXT);
          INSERT INTO users VALUES ('alice','user',0),('bob','user',0),('admin','admin',0),('disabled','admin',1);
          INSERT INTO files VALUES ('f1','alice','doc1','private'),('f2','bob','doc2','private');
          INSERT INTO attachments VALUES ('att_one','alice','chat','chat-one',NULL,'ready',2,NULL,NULL);
          INSERT INTO attachments VALUES ('att_bob','bob','chat','chat-one',NULL,'ready',2,NULL,NULL);
          INSERT INTO knowledge_bases VALUES ('kb-one','alice',NULL);
          INSERT INTO library_documents VALUES ('library-one','alice','kb-one',NULL,'version-one','personal');
          INSERT INTO document_versions VALUES ('version-one','file-hash','READY','att_library');
        ''')
    documents = {id: {'doc_id': id, 'title': id, 'content': 'Authorized original evidence.', 'version': '1',
                 'source_url': 'https://example.atlassian.net/wiki/spaces/A/pages/123/title'} for id in ('doc1', 'doc2')}
    class Transport:
        def post(self, url, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {'hasPermission': True})
    provider = SourceAccessProvider(mode='native', account_bindings={'alice': {'site':'example.atlassian.net','account_id':'atlassian-alice'}},
        base_url='https://example.atlassian.net', email='fixture@example.test', token='fixture', transport=Transport(),
        document_loader=documents.get, document_ids_loader=lambda: list(documents))
    permissions = PermissionService(str(path), source_provider=provider)
    remote = {'owner_id':'alice','scope':'chat','chat_id':'chat-one','topic_id':None,'status':'ready','evidence_version':2}
    library = {'owner_id':'alice','scope':'library','knowledge_base_id':'kb-one','source_scope':'personal',
               'document_id':'library-one','version_id':'version-one','active':True,'sha256':'file-hash','status':'ready'}
    guard = AccessGuard(permissions, InternalChatRequest(query='question',user_id='alice',session_id='chat-one',
        attachment_context={'allowed_attachment_ids':['att_one','att_bob'],'selected_attachment_ids':['att_one']},
        memory_context={'actor':{'user_id':'alice','authenticated':True},'chat_id':'chat-one','revision':1,
                        'current_message_id':'current','current_sequence':2,'facts':[],'tail':[]}), 'security-trace')
    guard._private_source = lambda storage_id, evidence=False: ({'items':[{'content_hash':'block-hash'}]} if evidence else library if storage_id == 'att_library' else remote)
    return guard, path, documents, remote, library


def knowledge(documents):
    return SourceDependency(source_type='knowledge',doc_id='doc1',version='1',content_hash=source_metadata(documents['doc1'])['content_hash'])


def test_attachment_expiry_uses_drizzle_epoch_seconds(fixture):
    guard, path, *_ = fixture
    with sqlite3.connect(path) as db:
        db.execute("UPDATE attachments SET expires_at=? WHERE id='att_one'", (int(time.time()) + 60,))
    guard.prepare_tool('inspect_attachment', {'attachment_id': 'att_one'})
    with sqlite3.connect(path) as db:
        db.execute("UPDATE attachments SET expires_at=? WHERE id='att_one'", (int(time.time()) - 1,))
    with pytest.raises(PermissionResolutionError):
        guard.prepare_tool('inspect_attachment', {'attachment_id': 'att_one'})


def test_unknown_and_disabled_actor_never_reach_model(fixture):
    guard, *_ = fixture
    for user in ('', 'unknown', 'disabled'):
        other = AccessGuard(guard.permissions, ChatRequest(query='question',user_id=user), 'trace')
        with pytest.raises(PermissionResolutionError): other.sanitize_request()


def test_unbound_admin_does_not_bypass_source_native_permissions(fixture):
    guard, *_ = fixture
    assert guard.allowed_documents() == ['doc1']
    assert guard.permissions.get_accessible_doc_ids_strict('admin') == []
    assert guard.permissions.get_accessible_doc_ids_strict('bob') == []


@pytest.mark.parametrize('change',['local_revoke','source_drift','disabled'])
def test_recheck_after_tool_and_before_model_or_release(fixture, change):
    guard, path, docs, *_ = fixture
    guard.capture_tool('get_document', {'document':docs['doc1']}, [])
    if change == 'source_drift': docs['doc1']['content'] = 'Changed source.'
    else:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE files SET user_id='bob' WHERE doc_id='doc1'" if change == 'local_revoke' else "UPDATE users SET disabled=1 WHERE id='alice'")
    token = CURRENT_ACCESS_GUARD.set(guard)
    try:
        with pytest.raises(PermissionResolutionError): check_model_access()
        with pytest.raises(PermissionResolutionError): guard.provenance()
    finally: CURRENT_ACCESS_GUARD.reset(token)


@pytest.mark.parametrize('record',[{'doc_id':'doc1','text':'Stale indexed text'}, {'doc_id':'doc1','title':'Secret stale title'}, {'title':'Unbound derived summary'}])
def test_never_rebind_unverified_text_or_title_to_current_source(fixture, record):
    with pytest.raises(PermissionResolutionError): fixture[0].capture_tool('search_documents', {'items':[record]}, [])


def test_legacy_memory_and_soul_cannot_be_promoted_to_authorized_context(fixture):
    guard, _, docs, *_ = fixture
    guard.request = guard.request.model_copy(update={'soul_content':'Untrusted secret','topic_titles':['Secret title'],
        'memory_context':guard.request.memory_context.model_copy(update={'tail':[
            __import__('agent.schemas.chat',fromlist=['MemoryMessage']).MemoryMessage(id='old',sequence=1,revision=1,role='assistant',content='Legacy secret')
        ]})})
    clean = guard.sanitize_request()
    assert clean.memory_context.tail == [] and clean.soul_content is None and clean.topic_titles is None
    assert guard.provenance().dependencies == []


def test_inspect_authorizes_before_bytes_can_reach_vision_model(fixture):
    guard, path, *_ = fixture
    assert guard.prepare_tool('inspect_attachment', {'attachment_id':'att_one'})['attachment_id'] == 'att_one'
    with pytest.raises(PermissionResolutionError): guard.prepare_tool('inspect_attachment', {'attachment_id':'att_bob'})
    with sqlite3.connect(path) as db: db.execute("UPDATE attachments SET chat_id='other-chat' WHERE id='att_one'")
    with pytest.raises(PermissionResolutionError): guard.prepare_tool('inspect_attachment', {'attachment_id':'att_one'})


def test_three_source_dependencies_survive_and_revoke_transitively(fixture):
    guard, path, docs, remote, library = fixture
    deps = [knowledge(docs), SourceDependency(source_type='attachment',doc_id='att_one',version=2,content_hash='block-hash'),
            SourceDependency(source_type='personal',doc_id='library-one',document_id='library-one',knowledge_base_id='kb-one',version_id='version-one',content_hash='file-hash')]
    assert guard._inherit_if_allowed(deps)
    assert {d.source_type for d in guard.provenance().dependencies} == {'knowledge','attachment','personal'}
    with sqlite3.connect(path) as db: db.execute("UPDATE library_documents SET deleted_at=1 WHERE id='library-one'")
    with pytest.raises(PermissionResolutionError): guard.provenance()


@pytest.mark.parametrize('field,value',[('active',False),('source_scope','enterprise'),('knowledge_base_id','other-kb'),('sha256','changed-hash'),('status','indexing')])
def test_personal_projection_and_remote_version_must_both_match(fixture, field, value):
    guard, _, _, _, remote = fixture
    remote[field] = value
    dep = SourceDependency(source_type='personal',doc_id='library-one',document_id='library-one',knowledge_base_id='kb-one',version_id='version-one',content_hash='file-hash')
    with pytest.raises(PermissionResolutionError): guard._check_one(dep)


def test_attachment_edit_invalidates_old_reply_even_if_block_hash_remains(fixture):
    guard, path, *_ = fixture
    dep = SourceDependency(source_type='attachment',doc_id='att_one',version=2,content_hash='block-hash')
    assert guard._inherit_if_allowed([dep])
    with sqlite3.connect(path) as db: db.execute("UPDATE attachments SET evidence_version=3 WHERE id='att_one'")
    with pytest.raises(PermissionResolutionError): guard.provenance()
