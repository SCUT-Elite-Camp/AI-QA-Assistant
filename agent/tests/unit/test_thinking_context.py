"""Projection preserves whole source meaning without repeated raw tool metadata."""
import json
import pytest
from agent.runtime.context import EvidencePool
from agent.schemas.tool_execution import ToolExecutionResult
from agent.config.settings import Settings
from tests.unit.test_agent_runner import evidence

pytestmark=pytest.mark.no_storage


def test_full_read_noncontiguous_chunk_keeps_full_body_and_exact_quote_scope():
    body='# Release\n\nCondition A.\n\n<!-- parser metadata -->\n\nCondition B.'
    chunk='Condition A.\n\nCondition B.'
    pool=EvidencePool()
    pool.add('get_document',{'doc_ids':['a']},ToolExecutionResult(tool_call_id='read',tool_name='get_document',
        success=True,evidence=[evidence(text=chunk)],data={'documents':[{'doc_id':'a','content':body,'chunks':[{'text':chunk}]}]}))
    view,selected=pool.view(10000)
    payload=json.loads(view)
    assert payload['documents'][0]['content']==body
    assert payload['documents'][0]['references'][0]['quote_scope']==chunk
    assert selected[0]['content']==chunk and not payload['excerpts'] and 'chunks' not in view


def test_large_body_falls_back_to_whole_excerpt_and_catalog_is_bounded():
    pool=EvidencePool()
    pool.add('get_document',{'doc_ids':['a']},ToolExecutionResult(tool_call_id='read',tool_name='get_document',
        success=True,evidence=[evidence()],data={'documents':[{'doc_id':'a','content':'Long body. '*10000}]}))
    pool.catalog={str(i):{'doc_id':str(i),'title':'Long catalog item. '*50} for i in range(100)}
    view,selected=pool.view(2000)
    payload=json.loads(view)
    assert len(view)<=2000 and selected[0]['content']=='The release is planned.'
    assert not payload['documents'] and payload['excerpts'][0]['content']==selected[0]['content']
    assert payload['omitted_count']>0 and len(pool.catalog)==100


def test_relative_minicheck_path_resolves_against_project_root():
    from pathlib import Path
    # Explicit configured paths behave the same from agent/ and project root.
    settings=Settings(MINICHECK_MODEL_PATH='data-persistence/models/minicheck')
    path=Path(settings.MINICHECK_MODEL_PATH)
    assert path.is_absolute() and path.parts[-3:]==('data-persistence','models','minicheck')
