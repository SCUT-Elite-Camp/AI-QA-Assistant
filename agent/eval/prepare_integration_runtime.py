"""Build a fresh, explicitly isolated real-Confluence ACL/BM25/vector fixture.

The Web migration must have created an empty SQLite DB first. Original sources,
indexes and Milvus collections are never changed. Holdouts are frozen here,
before any quality run; plaintext source projections stay outside the repo.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for folder in ('agent', 'data-pipeline', 'data-persistence', 'toolset', ''):
    sys.path.insert(0, str(ROOT / folder))
from eval.research_product_acceptance import load_cases, load, save, sha256
from toolset.tool_layer.evidence_metadata import source_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--resume-vectors', action='store_true')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    source = args.sources.resolve()
    if source == runtime or source in runtime.parents or runtime in source.parents:
        raise ValueError('fixture_must_be_separate_from_original_sources')
    docs = runtime / 'documents'
    if docs.exists() and not args.resume_vectors:
        raise ValueError('fixture_already_prepared_use_new_directory')
    db_path = runtime / 'permissions.db'
    if not db_path.is_file():
        raise ValueError('migrate_empty_web_database_first')
    cases = load_cases(source, args.metadata)
    holdouts = load(Path(__file__).parent / 'datasets/integration_holdout.v1.json')['cases']
    versions = {p['doc_id']: p['version'] for p in load(args.metadata)['pages'] if p.get('doc_id')}
    frozen = {d['doc_id']: d for c in cases for d in c['frozen_manifest']['documents']}
    allowed = set(frozen) | {d for c in holdouts for d in c['allowed_document_ids']}
    forbidden = sorted(p.stem for p in source.glob('*.json') if p.stem not in allowed
                       and '.atlassian.net/' in str(load(p).get('source_url', '')))[0]
    projections = {}
    for doc_id in sorted(allowed | {forbidden}):
        doc = load(source / (doc_id + '.json'))
        doc['version'] = frozen.get(doc_id, {}).get('version', versions.get(doc_id))
        doc['source_version'] = str(doc['version'])
        doc['content_hash'] = source_metadata(doc)['content_hash']
        projections[doc_id] = doc
        if args.resume_vectors:
            previous = load(docs / (doc_id + '.json'))
            if previous != doc:
                raise ValueError('frozen_source_drift_resume_forbidden:' + doc_id)
    docs.mkdir(parents=True, exist_ok=args.resume_vectors)
    if not args.resume_vectors:
        for doc_id, doc in projections.items():
            save(docs / (doc_id + '.json'), doc)
    for case in holdouts:
        sources = [load(docs / (id + '.json')) for id in case['allowed_document_ids']]
        projection = {'documents': [{'doc_id': d['doc_id'], 'version': d['version'], 'content_hash': d['content_hash']} for d in sources]}
        case.update(source_scope={'document_ids': case['allowed_document_ids'], 'knowledge_base_ids': []},
                    source_projection_manifest=projection, frozen_manifest=projection,
                    question_sha256=sha256(case['question'].encode()), judge_sources=sources)
    if args.resume_vectors:
        if load(runtime / 'frozen_holdouts.json') != holdouts:
            raise ValueError('frozen_holdout_drift_resume_forbidden')
    else:
        save(runtime / 'frozen_holdouts.json', holdouts)
    with sqlite3.connect(db_path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        if args.resume_vectors:
            if db.execute('SELECT marker FROM research_acceptance_fixture').fetchone() != ('isolated',):
                raise ValueError('unmarked_fixture_resume_forbidden')
        elif db.execute('SELECT count(*) FROM users').fetchone()[0] != 0:
            raise ValueError('fixture_database_not_empty')
        for user in (() if args.resume_vectors else ('accept-alice', 'accept-bob', 'accept-admin', 'accept-disabled')):
            db.execute('INSERT INTO users(id,email,name,avatar,username,provider,provider_id,role,disabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (user, user+'@example.test', user, '', user, 'github', user, 'admin' if user == 'accept-admin' else 'user', int(user == 'accept-disabled'), int(time.time())))
        for doc_id in ([] if args.resume_vectors else sorted(allowed | {forbidden})):
            db.execute('INSERT INTO files(id,user_id,name,original_name,mime_type,size,storage_path,visibility,doc_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('fixture-'+doc_id, 'accept-alice' if doc_id in allowed else 'accept-bob', doc_id, doc_id, 'text/plain', 1, str(docs/(doc_id+'.json')), 'private', doc_id, int(time.time())))
        if not args.resume_vectors:
            db.execute('CREATE TABLE research_acceptance_fixture(marker TEXT)')
            db.execute("INSERT INTO research_acceptance_fixture VALUES('isolated')")
    from retrieval.bm25_index import BM25Index
    bm25 = BM25Index()
    bm25.build_from_documents(str(docs))
    bm25.save(str(runtime / 'bm25.pkl'))
    from pipeline.embedder import embed_texts
    from storage.milvus_store import MilvusStore
    from pymilvus import utility
    store = MilvusStore(collection_name=args.collection)
    store.connect()
    if utility.has_collection(store.collection_name):
        raise ValueError('vector_collection_not_fresh')
    documents = [load(p) for p in sorted(docs.glob('*.json'))]
    rows = [(d,c) for d in documents for c in d.get('chunks', []) if c.get('text')]
    vectors = embed_texts([c['text'] for d,c in rows])
    store.insert_chunks(vectors, [c['chunk_id'] for d,c in rows], [c['text'] for d,c in rows],
        [d['doc_id'] for d,c in rows], [c.get('index',0) for d,c in rows],
        [d.get('source_url','') for d,c in rows], [d.get('title','') for d,c in rows],
        [d.get('space','') for d,c in rows], ['confluence' for d,c in rows])
    fixture = {'marker':'isolated', 'documents':len(documents), 'chunks':len(rows), 'collection':args.collection,
        'forbidden_doc_id':forbidden, 'revocation_doc_id':cases[0]['allowed_document_ids'][0],
        'source_export':str(source), 'metadata':str(args.metadata), 'documents_dir':str(docs), 'permission_db':str(db_path)}
    save(runtime / 'fixture.json', fixture)
    print(json.dumps(fixture), flush=True)


if __name__ == '__main__':
    main()
