import json

from parsers.markdown_parser import MarkdownParser
from pipeline.ingestion.discovery import get_new_or_modified_files
from pipeline.confluence.lifecycle import withdrawn_confluence_documents


def test_unchanged_export_is_not_reingested_by_path_or_mtime(tmp_path, monkeypatch):
    documents = tmp_path / 'documents'
    documents.mkdir()
    raw = tmp_path / 'index.md'
    raw.write_text('source text', encoding='utf-8')
    meta = {'space_id': '9', 'page_id': '123', 'version': 2, 'last_updated': '2026-08-01T00:00:00Z'}
    (tmp_path / 'page.meta.json').write_text(json.dumps(meta), encoding='utf-8')
    parsed = MarkdownParser().parse(str(raw))
    (documents / f'{parsed.doc_id}.json').write_text(parsed.model_dump_json(), encoding='utf-8')
    assert get_new_or_modified_files([str(raw)], documents) == []
    interrupted = parsed.model_dump(mode='json')
    interrupted['metadata']['sync_status'] = 'export_ready'
    projection = documents / f'{parsed.doc_id}.json'
    projection.write_text(json.dumps(interrupted), encoding='utf-8')
    assert get_new_or_modified_files([str(raw)], documents) == [str(raw)]
    projection.write_text(parsed.model_dump_json(), encoding='utf-8')
    meta['version'] = 3
    (tmp_path / 'page.meta.json').write_text(json.dumps(meta), encoding='utf-8')
    assert get_new_or_modified_files([str(raw)], documents) == [str(raw)]


def test_removed_attachment_is_retracted_while_its_parent_remains(tmp_path):
    documents, space = tmp_path / 'documents', tmp_path / 'exports' / 'RAG'
    documents.mkdir()
    space.mkdir(parents=True)
    (space / 'manifest.json').write_text(json.dumps({
        'source_type': 'confluence_cloud', 'space_id': '9', 'status': 'ok', 'full_sync': True,
        'pages': {'123': {}},
    }), encoding='utf-8')
    (space / 'attachments-manifest.json').write_text(json.dumps({
        'space_id': '9', 'status': 'ok', 'full_sync': True, 'attachments': {},
    }), encoding='utf-8')
    (documents / 'attachment.json').write_text(json.dumps({
        'doc_id': 'attachment', 'metadata': {'space_id': '9', 'page_id': '123', 'attachment_id': 'att10'},
    }), encoding='utf-8')
    assert [d.document_id for d in withdrawn_confluence_documents(documents, tmp_path / 'exports')] == ['attachment']
    # An incomplete attachment list must never be used as deletion evidence.
    (space / 'attachments-manifest.json').write_text(json.dumps({
        'space_id': '9', 'status': 'partial', 'full_sync': True, 'attachments': {},
    }), encoding='utf-8')
    assert withdrawn_confluence_documents(documents, tmp_path / 'exports') == []
