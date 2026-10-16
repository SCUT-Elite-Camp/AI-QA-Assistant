"""Read-only-source A/B/C/D retrieval probe with a disposable new Milvus index.

Run from the repository root. Output and all rebuilt projections must be outside
the checkout. Existing documents, BM25 and vector collections are never replaced.
Scoring is a separate Codex per-fact review of raw returned evidence.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT/'data-pipeline', ROOT/'data-persistence', ROOT/'toolset'):
    sys.path.insert(0, str(directory))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env');load_dotenv(ROOT/'agent/.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--original-documents', type=Path, default=ROOT/'data-persistence/data/documents')
    parser.add_argument('--resume', action='store_true', help='Resume an interrupted disposable build before retrieval starts')
    parser.add_argument('--existing-build', type=Path, help='Read an existing completed disposable build; write a fresh query run')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out == ROOT or ROOT in out.parents:
        raise ValueError('Probe output must be outside the checkout')
    out.mkdir(parents=True, exist_ok=args.resume)
    if args.resume and (out/'raw-results.jsonl').exists():
        raise FileExistsError('A completed/started retrieval run cannot be resumed or overwritten')
    os.environ['HF_HUB_OFFLINE'] = '1';os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    torch.set_num_threads(4)
    from models.document import Document
    from parsers.pdf_parser import PDFParser
    from parsers.xlsx_parser import XlsxParser
    from pipeline.ingestion.preparation import prepare_document
    from pipeline.indexing.embedder import embed_texts
    from pipeline.indexing.vectors import index_document_vectors
    from retrieval.bm25_index import BM25Index
    from retrieval.reranker import model_path, BEFORE_RERANK
    from tool_layer.search_tool import SearchTool
    from storage.milvus_store import MilvusStore
    from pymilvus import utility, Collection

    dataset = json.loads(args.cases.read_text(encoding='utf-8'))
    if args.resume and digest(out/'cases.frozen.json') != digest(args.cases):
        raise ValueError('Resume dataset differs from the frozen dataset')
    (out/'cases.frozen.json').write_bytes(args.cases.read_bytes())
    documents = sorted(args.original_documents.glob('*.json'))
    original_bm25 = Path(os.environ['BM25_INDEX_PATH'])
    old_name = os.environ['MILVUS_COLLECTION']
    original_hashes = {str(p): digest(p) for p in [*documents, original_bm25]}
    previous = json.loads((args.existing_build/'runtime.json').read_text(encoding='utf-8')) if args.existing_build else None
    if previous and (previous['dataset_sha256'] != digest(args.cases) or previous['old_collection'] != old_name):
        raise ValueError('Existing build dataset or original collection differs')
    collection_name = previous['new_collection'] if previous else 'test_disposable_rerank_' + out.name.replace('-', '_')[-45:]
    if not collection_name.startswith('test_disposable_rerank_'):
        raise ValueError('Only disposable probe builds may be reused')
    if collection_name == old_name:
        raise ValueError('Disposable collection cannot be the original collection')
    store = MilvusStore(collection_name=collection_name)
    store.connect()
    if utility.has_collection(collection_name) and not args.resume and not previous:
        raise FileExistsError(collection_name)
    if previous and not utility.has_collection(collection_name):
        raise FileNotFoundError(collection_name)
    if not utility.has_collection(old_name):
        raise FileNotFoundError(old_name)
    before = Collection(old_name).num_entities
    rebuilt_dir = args.existing_build/'documents' if previous else out/'documents'
    if not previous:
        rebuilt_dir.mkdir(exist_ok=args.resume)
    stats = previous['documents'] if previous else []
    for path in ([] if previous else documents):
        if args.resume and (rebuilt_dir/path.name).exists():
            done = Document.model_validate_json((rebuilt_dir/path.name).read_text(encoding='utf-8'))
            stats.append({'doc_id':done.doc_id,'title':done.title,'chunks':len(done.chunks),
                          'max_chars':max((len(c.text) for c in done.chunks),default=0),
                          'max_tokens':max((int(c.metadata.get('token_count',0)) for c in done.chunks),default=0)})
            continue
        raw = json.loads(path.read_text(encoding='utf-8'))
        doc = Document.model_validate(raw)
        if doc.doc_type in {'pdf','xlsx'} and Path(doc.address).is_file():
            parsed = (PDFParser() if doc.doc_type == 'pdf' else XlsxParser()).parse(doc.address)
            doc.content_blocks = parsed.content_blocks
            doc.content = parsed.content
            doc.parse_diagnostics = parsed.parse_diagnostics
        prepare_document(doc)
        (rebuilt_dir/path.name).write_text(doc.model_dump_json(indent=2), encoding='utf-8')
        stats.append({'doc_id':doc.doc_id,'title':doc.title,'chunks':len(doc.chunks),
                      'max_chars':max((len(c.text) for c in doc.chunks),default=0),
                      'max_tokens':max((int(c.metadata.get('token_count',0)) for c in doc.chunks),default=0)})
        print('prepared',doc.doc_id,len(doc.chunks),flush=True)
    if not previous:
        # A fresh disposable collection needs no per-document delete/flush.
        # Use the same production serialization and Milvus insert interface in
        # one batch; never apply this append-only build to an existing index.
        if args.resume and utility.has_collection(collection_name):
            raise ValueError('Resume requires an uncreated collection for an append-only build')
        from pipeline.indexing.vectors import provenance_columns
        rebuilt = [Document.model_validate_json(p.read_text(encoding='utf-8')) for p in sorted(rebuilt_dir.glob('*.json'))]
        pairs = [(doc, chunk) for doc in rebuilt for chunk in doc.chunks]
        chunks = [chunk for doc, chunk in pairs]
        embeddings = embed_texts([c.index_text or c.text for c in chunks])
        store.init_collection(dim=len(embeddings[0]));store.validate_chunk_schema()
        store.insert_chunks(embeddings=embeddings, chunk_ids=[c.chunk_id for c in chunks],
            chunk_texts=[c.text for c in chunks], doc_ids=[d.doc_id for d,c in pairs],
            chunk_indices=[c.index for c in chunks], source_urls=[d.source_url for d,c in pairs],
            titles=[d.title for d,c in pairs], spaces=[d.space for d,c in pairs],
            doc_types=[d.doc_type for d,c in pairs], **provenance_columns(chunks))
    rebuilt_bm25 = args.existing_build/'bm25_index.pkl' if previous else out/'bm25_index.pkl'
    if not previous:
        bm25 = BM25Index();bm25.build_from_documents(str(rebuilt_dir));bm25.save(str(rebuilt_bm25))
    manifest = {'dataset_sha256':digest(args.cases),'old_collection':old_name,
                'new_collection':collection_name,'original_entities_before':before,
                'new_entities':Collection(collection_name).num_entities,
                'reranker_model_path':str(model_path()),'scope':'local component diagnostic; no answer model or native/BFF acceptance',
                'rebuilt_documents':str(rebuilt_dir),'rebuilt_bm25':str(rebuilt_bm25),
                'variants':{'A':'original chunks, no reranker','B':'original chunks, reranker',
                            'C':'new chunks, no reranker','D':'new chunks, reranker'},'documents':stats}
    with (out/'raw-results.jsonl').open('x', encoding='utf-8') as handle:
        for variant, new, ranking in [('A',False,False),('B',False,True),('C',True,False),('D',True,True)]:
            os.environ['RERANK_ENABLED'] = str(ranking).lower()
            os.environ['MILVUS_COLLECTION'] = collection_name if new else old_name
            os.environ['BM25_INDEX_PATH'] = str(rebuilt_bm25) if new else str(original_bm25)
            tool = SearchTool(documents_dir=str(rebuilt_dir if new else args.original_documents))
            for case in dataset['cases']:
                start = time.perf_counter()
                candidate_trace = []
                previous_check = BEFORE_RERANK.get()
                def observe(rows):
                    if previous_check is not None:
                        previous_check(rows)
                    candidate_trace.extend(dict(row) for row in rows)
                trace_token = BEFORE_RERANK.set(observe)
                try:
                    rows = tool.search_direct(case['question'], top_k=5, mode='hybrid')
                    record = {'variant':variant,'case_id':case['case_id'],'status':'completed','rows':rows}
                except Exception as exc:
                    record = {'variant':variant,'case_id':case['case_id'],'status':'error','error':str(exc),'rows':[]}
                finally:
                    BEFORE_RERANK.reset(trace_token)
                record['rerank_candidates'] = candidate_trace
                record['elapsed_seconds'] = round(time.perf_counter()-start,4)
                handle.write(json.dumps(record,ensure_ascii=False)+'\n');handle.flush()
                print(variant,case['case_id'],record['status'],record['elapsed_seconds'],flush=True)
    manifest['original_entities_after'] = Collection(old_name).num_entities
    manifest['original_files_unchanged'] = all(digest(p)==sha for p,sha in original_hashes.items())
    manifest['original_hashes'] = original_hashes
    manifest['code_hashes'] = {str(p.relative_to(ROOT)):digest(p) for p in (
        ROOT/'toolset/tool_layer/search_tool.py', ROOT/'toolset/retrieval/reranker.py',
        ROOT/'toolset/retrieval/context.py', ROOT/'data-pipeline/pipeline/documents/table_chunks.py',
        ROOT/'data-pipeline/pipeline/ingestion/preparation.py', ROOT/'data-pipeline/parsers/xlsx_parser.py',
        ROOT/'data-pipeline/parsers/table_backends.py')}
    manifest['reranker_revision'] = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
    manifest['probe_cpu_threads'] = 4
    (out/'runtime.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if not manifest['original_files_unchanged'] or before != manifest['original_entities_after']:
        raise RuntimeError('Original index integrity changed during probe')
    print('Saved',out,flush=True)


if __name__ == '__main__':
    main()
