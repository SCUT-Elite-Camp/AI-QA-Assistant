"""Offline MiniCheck validation. Never invoked by the Chat pipelines.

Use reviewed, externally stored cases. Native source access is checked before
each forward pass; no generated judge calls, remote code, or silent truncation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import time


ROOT = Path(__file__).resolve().parents[2]
GOLD = {"supported", "contradicted", "insufficient_evidence"}
MODEL_REPOSITORY = "lytang/MiniCheck-DeBERTa-v3-Large"


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cases(path: Path, expected_sha256: str, *, allow_non_english: bool = False) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("frozen_dataset_changed")
    data = json.loads(raw)
    cases = data["cases"]
    if data.get("reviewer") != "Codex" or data.get("frozen_before_inference") is not True:
        raise ValueError("reviewed_frozen_cases_required")
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)) or not cases:
        raise ValueError("unique_cases_required")
    split_docs = {split: set() for split in ("dev", "holdout")}
    for case in cases:
        if case["expected_verdict"] not in GOLD or not case.get("review_reason") or not case["evidence"]:
            raise ValueError("reviewed_case_required")
        if case["split"] in split_docs:
            split_docs[case["split"]].update(item["doc_id"] for item in case["evidence"])
    if split_docs["dev"] & split_docs["holdout"]:
        raise ValueError("holdout_documents_overlap_development")
    if not allow_non_english and any(
        c.get("claim_language") not in {"en", "en-US"}
        or c.get("source_language") not in {"en", "en-US"} for c in cases
    ):
        raise ValueError("english_cases_required_use_explicit_multilingual_opt_in")
    return data


def verify_sources(cases: list[dict], documents: Path, permissions, user_id: str) -> None:
    doc_ids = sorted({e["doc_id"] for case in cases for e in case["evidence"]})
    if set(permissions.get_accessible_doc_ids_strict(user_id, doc_ids=doc_ids)) != set(doc_ids):
        raise ValueError("current_source_access_denied")
    # This dictionary lasts one boundary only, never an authorization cache.
    originals = {}
    for doc_id in doc_ids:
        path = (documents / (doc_id + ".json")).resolve()
        if path.parent != documents.resolve():
            raise ValueError("invalid_document_identity")
        raw = path.read_bytes()
        document = json.loads(raw)
        if document.get("doc_id") != doc_id:
            raise ValueError("source_identity_changed")
        originals[doc_id] = (hashlib.sha256(raw).hexdigest(), document["content"])
    for case in cases:
        for evidence in case["evidence"]:
            digest, body = originals[evidence["doc_id"]]
            if digest != evidence["document_file_sha256"]:
                raise ValueError("frozen_source_changed")
            start, end = evidence["source_start"], evidence["source_end"]
            if not 0 <= start < end <= len(body) or body[start:end] != evidence["quote"]:
                raise ValueError("original_excerpt_changed")


def prepare_reviewed_case(case: dict, documents: Path, *, token_counter=None, max_context_chars=6000):
    """Adapt a frozen, manually reviewed binding, never a fabricated model run.

    The real acceptance caller checks current permissions before construction
    and before release. Original file hashes/offsets remain authoritative here.
    The local body projection has a separately derived, explicitly named locator.
    """
    from agent.evidence.verification_context import IDENTITY_FIELDS, build_verification_inputs
    from toolset.tool_layer.evidence_metadata import chunk_metadata
    sources, supports, citations = [], [], {}
    for fragment in case["evidence"]:
        doc_id = fragment["doc_id"]
        if doc_id not in citations:
            path = (documents/(doc_id + ".json")).resolve()
            if path.parent != documents.resolve():
                raise ValueError("invalid_document_identity")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != fragment["document_file_sha256"]:
                raise ValueError("frozen_source_changed")
            document = json.loads(raw)
            if document.get("doc_id") != doc_id:
                raise ValueError("source_identity_changed")
            body = document["content"]
            chunk_id = doc_id + "::reviewed-frozen-body"
            sources.append({**chunk_metadata(document, {"chunk_id":chunk_id, "text":body}),
                            "doc_id":doc_id, "chunk_id":chunk_id, "content":body, "source_type":"knowledge"})
            citations[doc_id] = len(sources)
        citation = citations[doc_id]
        source = sources[citation - 1]
        supports.append({**{key:source.get(key) for key in IDENTITY_FIELDS}, "citation_id":citation,
                         **{key:fragment[key] for key in ("quote", "source_start", "source_end")}})
    report = {"valid":True, "validation_kind":"binding", "claims":[{
        "claim_id":case["case_id"], "text":case["claim"], "supports":supports,
    }]}
    return build_verification_inputs(report, sources, token_counter=token_counter,
                                     max_context_chars=max_context_chars)[0]


def check_acl_denial(permissions, user_id: str, doc_id: str, output: Path) -> dict:
    """Downscope a marked disposable SQLite copy, restoring it in finally.

    The positive actor/native binding and the live database are never modified.
    A real existing document is denied by local ACL, not by question scope.
    """
    from agent.service.permission_service import PermissionService
    if not permissions.source_provider._load(doc_id):
        raise ValueError("forbidden_document_must_exist")
    if doc_id not in permissions.get_accessible_doc_ids_strict(user_id, doc_ids=[doc_id]):
        raise ValueError("negative_fixture_requires_verified_existing_source")
    path = output / "acl-denied.sqlite"
    fixture = sqlite3.connect(path)
    snapshot = sqlite3.connect(":memory:")
    original = sqlite3.connect(f"file:{Path(permissions.db_path).as_posix()}?mode=ro", uri=True)
    try:
        original.backup(fixture)
    finally:
        original.close()
    fixture.execute("CREATE TABLE claim_eval_disposable_fixture (marker TEXT)")
    fixture.execute("INSERT INTO claim_eval_disposable_fixture VALUES ('disposable')")
    fixture.commit()
    fixture.backup(snapshot)
    baseline = "\n".join(fixture.iterdump())
    denied = False
    try:
        owner = fixture.execute("SELECT id FROM users WHERE id != ? LIMIT 1", (user_id,)).fetchone()
        files = fixture.execute("SELECT id FROM files WHERE doc_id=?", (doc_id,)).fetchall()
        if not files:
            raise ValueError("acl_fixture_requires_existing_file")
        if not owner:
            owner = ("claim-eval-disposable-owner",)
            fixture.execute("""INSERT INTO users
                (id,email,name,avatar,username,provider,provider_id,created_at,role,disabled)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (owner[0], "claim-eval@example.invalid",
                "Disposable ACL Owner", "", owner[0], "fixture", owner[0], int(time.time()), "user", 0))
        fixture.execute("UPDATE users SET role='user' WHERE id=?", (user_id,))
        fixture.execute("UPDATE files SET user_id=?, visibility='private' WHERE doc_id=?", (owner[0], doc_id))
        for file_id, in files:
            fixture.execute("DELETE FROM file_permissions WHERE file_id=?", (file_id,))
        fixture.commit()
        probe = PermissionService(str(path), source_provider=permissions.source_provider)
        denied = probe.get_accessible_doc_ids_strict(user_id, doc_ids=[doc_id]) == []
        if not denied:
            raise ValueError("acl_negative_not_denied")
    finally:
        snapshot.backup(fixture)
        restored = baseline == "\n".join(fixture.iterdump())
        fixture.close()
        snapshot.close()
        if not restored:
            raise ValueError("acl_fixture_restore_failed")
    return {"forbidden_doc_id": doc_id, "local_acl_denied": denied,
            "disposable_copy_restored": restored, "live_database_modified": False}


def summarize(rows: list[dict]) -> dict:
    verified = [r for r in rows if r["verdict"] != "needs_review"]
    positive = [r for r in rows if r["expected_verdict"] == "supported"]
    negative = [r for r in rows if r["expected_verdict"] != "supported"]
    false_accepts = [r for r in negative if r["verdict"] == "supported"]
    false_rejects = [r for r in positive if r["verdict"] != "supported"]
    confusion = Counter((r["expected_verdict"], r["verdict"]) for r in rows)
    return {"cases": len(rows), "verified": len(verified), "needs_review": len(rows)-len(verified),
        "unsupported_cases": len(negative), "false_accepts": len(false_accepts),
        "false_accept_rate": len(false_accepts)/len(negative) if negative else None,
        "supported_cases": len(positive), "false_rejects": len(false_rejects),
        "false_reject_rate": len(false_rejects)/len(positive) if positive else None,
        "confusion": {f"{gold}->{pred}": count for (gold, pred), count in sorted(confusion.items())},
        "false_accept_ids": [r["case_id"] for r in false_accepts],
        "false_reject_ids": [r["case_id"] for r in false_rejects]}


def process_memory_mb() -> dict:
    if os.name != "nt":
        return {}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ("peak", "current", "qpp", "qp", "qnp", "qn", "page", "peakpage")]
    values = Counters()
    values.cb = ctypes.sizeof(values)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not query(kernel.GetCurrentProcess(), ctypes.byref(values), values.cb):
        raise OSError("process_memory_unavailable")
    return {"working_set_mb": values.current/1024**2, "peak_working_set_mb": values.peak/1024**2}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dataset", "documents", "permission-db", "model-dir", "output"):
        parser.add_argument("--"+key, type=Path, required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--split", nargs="+", choices=["dev", "holdout", "regression"], required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--forbidden-doc-id", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--single-benchmark", action="store_true")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Export source-bound structured inputs with tokenizer budgets; no classifier forward.")
    parser.add_argument("--max-context-chars", type=int, default=6000,
                        help="Preparation-only character budget; oversized context is not truncated.")
    parser.add_argument("--allow-non-english", action="store_true",
                        help="Explicit language capability test; default datasets must declare English claims and sources.")
    args = parser.parse_args()
    if ROOT == args.output.resolve() or ROOT in args.output.resolve().parents:
        raise ValueError("acceptance_output_must_be_outside_checkout")
    if args.output.exists() or args.batch_size < 1 or args.threads < 1 or args.max_context_chars < 1:
        raise ValueError("new_output_and_positive_budgets_required")
    if os.getenv("SOURCE_ACCESS_MODE", "native") != "native":
        raise ValueError("native_source_access_required")
    data = load_cases(args.dataset, args.dataset_sha256, allow_non_english=args.allow_non_english)
    cases = [c for c in data["cases"] if c["split"] in args.split]
    if not cases:
        raise ValueError("empty_case_selection")
    from agent.service.permission_service import PermissionService
    from agent.service.source_access import SourceAccessProvider
    permissions = PermissionService(str(args.permission_db), source_provider=SourceAccessProvider(
        documents_dir=args.documents, mode="native"))
    verify_sources(cases, args.documents, permissions, args.user_id)
    args.output.mkdir(parents=True)
    save(args.output/"acl-negative.json", check_acl_denial(permissions, args.user_id, args.forbidden_doc_id, args.output))
    from agent.evidence.minicheck_identity import verified_minicheck_weights
    identity, use_safetensors = verified_minicheck_weights(args.model_dir)
    if args.prepare_only:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False)
        def count_input(premise, claim):
            return len(tokenizer(premise + tokenizer.eos_token + claim, truncation=False)["input_ids"])
        prepared = [prepare_reviewed_case(case, args.documents, token_counter=count_input,
                                         max_context_chars=args.max_context_chars) for case in cases]
        verify_sources(cases, args.documents, permissions, args.user_id)
        with (args.output/"verification-inputs.jsonl").open("x", encoding="utf-8") as output:
            for item in prepared:
                output.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        summary = {"cases":len(prepared), "ready":sum(p.status == "ready" for p in prepared),
                   "needs_review":dict(Counter(p.reason for p in prepared if p.status != "ready")),
                   "dataset_sha256":args.dataset_sha256, "context_policy":"bound-structure.v1",
                   "annotation_kind":"reviewed_frozen_binding", "classifier_calls":0,
                   "model_identity":identity, "max_context_chars":args.max_context_chars, "max_input_tokens":512}
        save(args.output/"preparation-summary.json", summary)
        print(json.dumps(summary), flush=True)
        return
    import torch
    import transformers
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(20261015)
    loaded = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False)
    model, loading = AutoModelForSequenceClassification.from_pretrained(args.model_dir,
        local_files_only=True, trust_remote_code=False, dtype=torch.float32, output_loading_info=True,
        use_safetensors=use_safetensors)
    if loading.get("missing_keys") or loading.get("mismatched_keys") or loading.get("error_msgs"):
        raise ValueError("classifier_weights_not_fully_loaded")
    loading = {key:sorted(value) if isinstance(value, set) else value for key, value in loading.items()}
    save(args.output/"loading-info.json", loading)
    model.eval()
    load_seconds = time.perf_counter()-loaded
    labels = model.config.id2label
    if set(labels.values()) != {"0", "1"}:
        raise ValueError("unexpected_classifier_label_mapping")

    def encode(case):
        premise = "\n".join(e["quote"] for e in case["evidence"])
        # MiniCheck's published encoder concatenates using its EOS token.
        return tokenizer(premise + tokenizer.eos_token + case["claim"], truncation=False)

    def forward(batch):
        encoded = [encode(c) for c in batch]
        lengths = [len(c["input_ids"]) for c in encoded]
        if max(lengths) > 512:
            raise ValueError("input_too_long_no_silent_truncation")
        inputs = tokenizer.pad(encoded, padding=True, return_tensors="pt")
        started = time.perf_counter()
        with torch.inference_mode():
            logits = model(**inputs).logits
        elapsed = (time.perf_counter()-started)*1000
        if not torch.isfinite(logits).all():
            raise ValueError("nonfinite_classifier_output")
        return logits.softmax(-1).tolist(), elapsed, lengths

    toy = {"evidence":[{"quote":"A student is studying in the library."}], "claim":"A student is in the library."}
    forward([toy])  # Public synthetic warmup, excluded from quality/latency counts.
    rows, batches = [], []
    with (args.output/"predictions.jsonl").open("x", encoding="utf-8") as output:
        for start in range(0, len(cases), args.batch_size):
            batch = cases[start:start+args.batch_size]
            boundary_start = time.perf_counter()
            verify_sources(batch, args.documents, permissions, args.user_id)
            access_ms = (time.perf_counter()-boundary_start)*1000
            probabilities, elapsed, lengths = forward(batch)
            batches.append({"forward_ms":elapsed, "access_ms":access_ms, "size":len(batch)})
            for case, probs, length in zip(batch, probabilities, lengths):
                label = labels[max(range(len(probs)), key=probs.__getitem__)]
                verdict = "supported" if label == "1" else "not_supported"
                row = {key:case[key] for key in ("case_id", "group_id", "split", "category", "claim_language", "expected_verdict")}
                row.update(verdict=verdict, native_label=label,
                           native_probabilities={labels[i]: prob for i, prob in enumerate(probs)},
                           tokens=length, batch_id=len(batches), batch_forward_ms=elapsed, batch_size=len(batch))
                rows.append(row)
                output.write(json.dumps(row,ensure_ascii=False)+"\n")
            output.flush()
            print(f"minicheck: {len(rows)}/{len(cases)}", flush=True)
    single = []
    if args.single_benchmark:
        benchmark = [c for c in data["cases"] if c["split"] == "dev"][:6]
        for repeat in range(2):
            for case in benchmark:
                verify_sources([case], args.documents, permissions, args.user_id)
                probs, elapsed, lengths = forward([case])
                single.append({"case_id":case["case_id"], "repeat":repeat, "forward_ms":elapsed,
                               "tokens":lengths[0], "native_label":labels[max(range(len(probs[0])), key=probs[0].__getitem__)]})
    verify_sources(cases, args.documents, permissions, args.user_id)
    summary = {"overall":summarize(rows), "by_split":{}, "by_language":{}, "by_category":{}}
    for field, key in (("split","by_split"), ("claim_language","by_language"), ("category","by_category")):
        for value in sorted({r[field] for r in rows}):
            summary[key][value] = summarize([r for r in rows if r[field] == value])
    summary["runtime"] = {"candidate":"minicheck", "identity":identity, "dataset_sha256":args.dataset_sha256,
        "policy":"trained_argmax_no_tuning", "test_language_policy":"explicit_multilingual" if args.allow_non_english else "english",
        "native_three_way":False, "load_seconds":load_seconds,
        "device":"cpu", "cpu":platform.processor(), "logical_cpus":os.cpu_count(), "threads":args.threads,
        "torch":torch.__version__, "transformers":transformers.__version__, "parameters":sum(p.numel() for p in model.parameters()),
        "loading_info":loading,
        "batches":batches, "single_request_benchmark":single, **process_memory_mb()}
    if single:
        timings = sorted(x["forward_ms"] for x in single)
        summary["runtime"]["single_forward_p50_ms"] = statistics.median(timings)
        summary["runtime"]["single_forward_p95_ms"] = timings[min(len(timings)-1, int(len(timings)*0.95))]
    save(args.output/"summary.json", summary)
    print(json.dumps(summary["overall"]), flush=True)


if __name__ == "__main__":
    main()
