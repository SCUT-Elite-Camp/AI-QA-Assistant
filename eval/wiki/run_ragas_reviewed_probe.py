"""Paired, full-cohort Ragas PROBE of Direct Evidence and Wiki-guided Evidence.

Questions and references come from the human-reviewed Wiki pages. They are
weak labels because the page content determines the questions. This is an
offline retrieval comparison, not the Agent's coverage policy or Gate D.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from eval.wiki.ragas_evaluator import (
    RagasConfig, RagasEvaluator, build_ragas_sample, ragas_version,
)
from pipeline.wiki.search import (
    BgeM3Encoder, BgeM3WikiVectorSearch, SQLiteFTSWikiSearch, WikiSearchBackend,
)
from storage.wiki_store import WikiStore


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_documents(path: Path) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for filename in sorted(path.glob("*.json")):
        document = json.loads(filename.read_text(encoding="utf-8"))
        if not document.get("active_version"):
            raise ValueError(f"inactive Evidence document: {filename.name}")
        for chunk in document["chunks"]:
            values.append({
                "document_id": document["doc_id"],
                "document_version_id": document["version_id"],
                "evidence_id": chunk["chunk_id"],
                "content": chunk["text"],
                "title": document["title"],
            })
    keys = [(item["document_version_id"], item["evidence_id"]) for item in values]
    if not values or len(set(keys)) != len(keys):
        raise ValueError("Evidence corpus is empty or has duplicate version/chunk IDs")
    return values


def _evidence_key(item: dict[str, str]) -> str:
    return f"{item['document_version_id']}:{item['evidence_id']}"


def _queries(db: sqlite3.Connection, revision: str, evidence_keys: set[str]) -> list[dict]:
    pages = db.execute(
        "SELECT page_id,page_type,title,payload FROM wiki_page_revisions "
        "WHERE revision=? AND status='PUBLISHED' AND page_type!='INDEX' ORDER BY page_id",
        (revision,),
    ).fetchall()
    result = []
    for row in pages:
        payload = json.loads(row["payload"])
        claims = [claim["text"] for section in payload.get("sections") or []
                  for claim in section.get("claims") or []]
        refs = {
            f"{source['document_version_id']}:{source['evidence_id']}"
            for source in db.execute(
                "SELECT document_version_id,evidence_id FROM wiki_page_sources "
                "WHERE revision=? AND page_id=?", (revision, row["page_id"]),
            )
        }
        if not claims or not refs or not refs <= evidence_keys:
            raise ValueError(f"reviewed page has missing Claim or original Evidence: {row['page_id']}")
        result.append({
            "query_id": f"reviewed-{row['page_id']}", "seed_page_id": row["page_id"],
            "page_type": row["page_type"], "query":
                f"{row['title']}在这些会议记录中有哪些相关事实、计划或待办？",
            "reference_answer": "\n".join(claims),
            "weak_reference_evidence_ids": sorted(refs),
        })
    if not result:
        raise ValueError("reviewed Wiki revision has no content-page questions")
    return result


def _top(vector: np.ndarray, matrix: np.ndarray, indices: list[int], limit: int) -> list[int]:
    scores = matrix[indices] @ vector
    return [indices[position] for position in np.argsort(-scores, kind="stable")[:limit]]


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _existing(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        identifier = row[key]
        if identifier in result:
            raise ValueError(f"duplicate resume record: {identifier}")
        result[identifier] = row
    return result


def _answer(client: Any, model: str, query: str, contexts: list[dict]) -> str:
    source_text = "\n\n".join(
        f"[E{index}] {item['title']}\n{item['content']}"
        for index, item in enumerate(contexts, 1)
    )
    response = client.chat.completions.create(
        model=model, temperature=0, max_tokens=900,
        messages=[
            {"role": "system", "content": (
                "你是会议记录问答助手。只依据提供的原始 Evidence 回答。"
                "严格区分已完成、计划、要求和待办；不能确定时说明缺少证据。"
                "用简洁中文回答，并在事实后标注 [E编号]。"
            )},
            {"role": "user", "content": f"问题：{query}\n\n原始 Evidence：\n{source_text}"},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def run(args: argparse.Namespace) -> dict:
    from openai import OpenAI

    if args.output_dir.exists() and not args.resume:
        raise FileExistsError(f"refusing to overwrite evaluation: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    store = WikiStore(args.wiki_db)
    with store.connection() as db:
        revision = db.execute(
            "SELECT source_scope,owner_id,knowledge_base_id,status FROM wiki_build_runs "
            "WHERE revision=?", (args.revision,),
        ).fetchone()
        if revision is None or revision["status"] != "PUBLISHED":
            raise ValueError("Ragas PROBE requires the isolated, activated reviewed revision")
        if db.execute(
            "SELECT 1 FROM wiki_reviewed_releases WHERE revision=?", (args.revision,),
        ).fetchone() is None:
            raise ValueError("revision lacks verified human-review provenance")
        scope = {key: revision[key] for key in (
            "source_scope", "owner_id", "knowledge_base_id",
        )}
        evidence = _load_documents(args.documents_dir)
        keys = {_evidence_key(item) for item in evidence}
        queries = _queries(db, args.revision, keys)
        index_count = db.execute(
            "SELECT COUNT(*) FROM wiki_page_vectors WHERE revision=? AND model_id='BAAI/bge-m3'",
            (args.revision,),
        ).fetchone()[0]
        page_count = db.execute(
            "SELECT COUNT(*) FROM wiki_page_revisions WHERE revision=?", (args.revision,),
        ).fetchone()[0]
        if index_count != page_count:
            raise ValueError("Wiki BGE-M3 index does not cover the exact reviewed revision")
    manifest = {
        "evaluation_label": "FULL_REVIEWED_WIKI_RAGAS_PROBE",
        "gate_d": "NOT_RUN", "query_origin": "all human-reviewed Wiki content pages; weak, page-derived labels",
        "agent_exploration_run": False,
        "wiki_revision": args.revision, "wiki_database_sha256": _digest(args.wiki_db),
        "document_files": {path.name: _digest(path) for path in sorted(args.documents_dir.glob("*.json"))},
        "model": args.model, "judge_model": args.judge_model,
        "ragas_version": ragas_version(), "scope": scope,
        "query_count": len(queries), "evidence_count": len(evidence), "wiki_page_count": page_count,
        "retrieval_cutoff": 20, "answer_context_cutoff": 10,
    }
    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("resume inputs differ from frozen PROBE manifest")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.output_dir / "queries.json").write_text(
            json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    from sentence_transformers import SentenceTransformer

    encoder = BgeM3Encoder()
    encoder._model = SentenceTransformer(
        str(args.bge_model_dir), device=args.bge_device, local_files_only=True,
    )
    if encoder._model.get_sentence_embedding_dimension() != 1024:
        raise ValueError("BGE-M3 Wiki encoder must have 1024 dimensions")
    started = time.perf_counter()
    evidence_matrix = np.asarray(encoder.embed([item["content"] for item in evidence]), dtype=np.float32)
    query_matrix = np.asarray(encoder.embed([item["query"] for item in queries]), dtype=np.float32)
    if evidence_matrix.shape != (len(evidence), 1024):
        raise ValueError("Direct Evidence BGE-M3 embeddings are incomplete")
    backend = WikiSearchBackend(SQLiteFTSWikiSearch(store), BgeM3WikiVectorSearch(store, encoder))
    evidence_lookup = {_evidence_key(item): index for index, item in enumerate(evidence)}
    all_indices = list(range(len(evidence)))
    client = OpenAI(api_key="local-evaluation", base_url=args.base_url, timeout=600, max_retries=0)
    traces_path = args.output_dir / "traces.jsonl"
    traces = _existing(traces_path, "record_id")
    for query, vector in zip(queries, query_matrix, strict=True):
        start = time.perf_counter()
        direct = _top(vector, evidence_matrix, all_indices, 20)
        direct_seconds = time.perf_counter() - start
        wiki_hits = backend.search(query["query"], **scope, top_k=3)
        guided_keys = {
            f"{source['document_version_id']}:{source['evidence_id']}"
            for page in wiki_hits for source in store.read_sources(page["page_id"], **scope)
        }
        guided_indices = [evidence_lookup[key] for key in guided_keys if key in evidence_lookup]
        guided = _top(vector, evidence_matrix, sorted(guided_indices), 20) if guided_indices else []
        combined = list(dict.fromkeys(direct[:5] + guided + direct))[:20]
        guided_seconds = time.perf_counter() - start
        for arm, indices in (("P0_DIRECT", direct), ("P1_WIKI_GUIDED", combined)):
            record_id = f"{query['query_id']}:{arm}"
            if record_id in traces:
                continue
            contexts = [evidence[index] for index in indices]
            answer_started = time.perf_counter()
            try:
                answer = _answer(client, args.model, query["query"], contexts[:10])
                error = "" if answer else "empty_answer"
            except Exception as exc:
                answer, error = "", f"{type(exc).__name__}: {exc}"
            record = {
                "record_id": record_id, "query_id": query["query_id"],
                "query_type": query["page_type"], "query": query["query"],
                "retrieval_path": arm, "answer": answer, "error": error,
                "retrieved_evidence_ids": [_evidence_key(item) for item in contexts],
                "retrieved_items": [{"evidence_id": _evidence_key(item), "content": item["content"]}
                                    for item in contexts],
                "wiki_page_ids": [page["page_id"] for page in wiki_hits] if arm == "P1_WIKI_GUIDED" else [],
                "retrieval_seconds": guided_seconds if arm == "P1_WIKI_GUIDED" else direct_seconds,
                "answer_seconds": time.perf_counter() - answer_started,
            }
            _append_jsonl(traces_path, record)
            traces[record_id] = record
            print(json.dumps({"record_id": record_id, "error": error,
                              "trace_count": len(traces)}, ensure_ascii=False), flush=True)

    scores_path = args.output_dir / "scores.jsonl"
    scores = _existing(scores_path, "record_id")
    reference_by_query = {item["query_id"]: item for item in queries}
    content_by_id = {_evidence_key(item): item["content"] for item in evidence}
    for record_id in sorted(traces):
        if record_id in scores:
            continue
        record = traces[record_id]
        if record["error"]:
            result = {"record_id": record_id, "error": record["error"]}
        else:
            reference = reference_by_query[record["query_id"]]
            sample = build_ragas_sample(
                record, reference_answer=reference["reference_answer"],
                reference_context_ids=reference["weak_reference_evidence_ids"],
                evidence_content=content_by_id,
            )
            evaluator = RagasEvaluator(RagasConfig(
                base_url=args.base_url, model=args.judge_model, timeout=900,
                max_tokens=4096,
            ))
            judge_started = time.perf_counter()
            metric = evaluator.score_many([sample])[0]
            result = ({"record_id": record_id, "metrics": metric,
                       "judge_seconds": time.perf_counter() - judge_started}
                      if isinstance(metric, dict) else
                      {"record_id": record_id, "error": f"{type(metric).__name__}: {metric}",
                       "judge_seconds": time.perf_counter() - judge_started})
        _append_jsonl(scores_path, result)
        scores[record_id] = result
        print(json.dumps({"scored": len(scores), "total": len(traces),
                          "record_id": record_id, "error": result.get("error", "")},
                         ensure_ascii=False), flush=True)

    by_arm: dict[str, list[dict]] = {"P0_DIRECT": [], "P1_WIKI_GUIDED": []}
    for record_id, row in scores.items():
        if "metrics" in row:
            by_arm[record_id.split(":")[-1]].append(row["metrics"])
    metrics = {
        arm: {name: round(sum(row[name] for row in values) / len(values), 4)
              for name in values[0]} if values else {}
        for arm, values in by_arm.items()
    }
    errors = [row for row in scores.values() if row.get("error")]
    report = {
        **manifest, "status": "PARTIAL",
        "probe_run_complete": not errors and len(scores) == len(queries) * 2,
        "raw_traces": len(traces), "scored_records": len(scores), "errors": len(errors),
        "metrics_by_arm": metrics,
        "elapsed_seconds_current_invocation": round(time.perf_counter() - started, 2),
        "limits": ["weak Wiki-derived references and queries", "local LLM judge",
                   "P1 is a deterministic Wiki-guided candidate pool, not actual Agent policy",
                   "BGE-M3 exact cosine Direct Evidence, not production Milvus latency",
                   "Gate D frozen human labels and production serving latency NOT_RUN"],
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-db", required=True, type=Path)
    parser.add_argument("--documents-dir", required=True, type=Path)
    parser.add_argument("--bge-model-dir", required=True, type=Path)
    parser.add_argument("--bge-device", default="cpu")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="qwen2.5:14b-instruct")
    parser.add_argument("--judge-model", default="qwen2.5:14b-instruct")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({key: result[key] for key in (
        "status", "query_count", "raw_traces", "scored_records", "errors", "metrics_by_arm",
    )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
