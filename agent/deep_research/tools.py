"""Manifest-scoped local Search and original-read adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import re
from typing import Any, Protocol

from agent.evidence.locator import canonical_chunk_id
from agent.schemas.research import SourceManifest
from .manifest import LocalDocumentResolver


class SearchBackend(Protocol):
    def search(self, query: str, **kwargs) -> list[dict]: ...


class LocalJsonSearchBackend:
    """Deterministic local fallback used by the fixed-fixture vertical slice.

    It deliberately implements only bounded lexical discovery over the JSON
    document catalog.  It does not replace the Tool Layer search backend in
    production, but gives Local Research a repeatable, network-free adapter
    for demos and recovery tests.
    """

    def __init__(self, documents_dir: str | Path) -> None:
        self.documents_dir = Path(documents_dir).resolve()

    def search(self, query: str, **kwargs: Any) -> list[dict]:
        top_k = max(1, int(kwargs.get("top_k", 5)))
        filters = kwargs.get("filters") or {}
        allowed_ids = {str(item) for item in filters.get("doc_ids", [])}
        query_tokens = self._tokens(query)
        rows: list[dict] = []
        title_tokens: set[str] = set()
        for path in sorted(self.documents_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            doc_id = str(payload.get("doc_id") or path.stem)
            if allowed_ids and doc_id not in allowed_ids:
                continue
            if payload.get("chunks"):
                title_tokens.update(self._tokens(str(payload.get("title") or "")))
            candidates = self._candidates(payload, doc_id)
            if not candidates:
                continue
            for index, locator, text in candidates:
                rows.append({
                    "doc_id": doc_id,
                    "chunk_id": locator,
                    "chunk_index": index,
                    "chunk_text": text,
                })
        # Rank sections, not one flattened document. Rare query terms should
        # outweigh recurring sprint headings and boilerplate.
        token_sets = [self._tokens(row["chunk_text"]) for row in rows]
        frequencies = Counter(token for tokens in token_sets for token in tokens)
        # The planner often repeats the full document title in every task.
        # Once a document is scoped, that must not swamp section-specific terms.
        has_section_terms = bool(query_tokens - title_tokens)
        weights = {token: math.log(1 + len(rows) / (1 + frequencies[token]))
                   * (0.1 if has_section_terms and token in title_tokens else 1.0)
                   for token in query_tokens}
        denominator = sum(weights.values()) or 1.0
        for row, tokens in zip(rows, token_sets):
            row["score"] = sum(weights[t] for t in query_tokens & tokens) / denominator
        rows.sort(key=lambda item: (-item["score"], item["doc_id"], item["chunk_index"]))
        # Round-robin ranked documents preserves comparisons while allowing
        # multiple distinct sections from the same document into the budget.
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            buckets.setdefault(row["doc_id"], []).append(row)
        selected = []
        while buckets and len(selected) < top_k:
            for doc_id in list(buckets):
                selected.append(buckets[doc_id].pop(0))
                if not buckets[doc_id]:
                    del buckets[doc_id]
                if len(selected) == top_k:
                    break
        return selected

    @staticmethod
    def _lines(payload: dict[str, Any]) -> list[str]:
        content = LocalDocumentResolver._searchable_text(payload)
        return [line.strip() for line in content.splitlines() if line.strip()]

    @classmethod
    def _candidates(
        cls,
        payload: dict[str, Any],
        doc_id: str,
    ) -> list[tuple[int, str, str]]:
        chunks = payload.get("chunks") or []
        candidates: list[tuple[int, str, str]] = []
        for position, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text") or chunk.get("chunk_text") or "").strip()
            if not text:
                continue
            try:
                index = int(chunk.get("index", position))
            except (TypeError, ValueError):
                index = position
            locator = canonical_chunk_id(doc_id, chunk.get("chunk_id"), index)
            candidates.append((index, locator, text))
        if candidates:
            return candidates
        return [
            (index, f"line:{index + 1}-{index + 1}", line)
            for index, line in enumerate(cls._lines(payload))
        ]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        tokens = set(
            re.findall(
                r"[A-Za-z][A-Za-z0-9_-]*|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]",
                text.casefold(),
            )
        )
        # Preserve identifiers, but also match source-code paths such as
        # intent_classifier.py against natural language 'intent classifier'.
        tokens.update(part for token in list(tokens) for part in re.split(r"[_-]", token) if part)
        return tokens


class LocalToolError(RuntimeError):
    pass


class LocalToolTimeout(LocalToolError):
    pass


class ManifestAccessError(LocalToolError):
    pass


@dataclass(frozen=True)
class ToolCallContext:
    research_id: str
    task_id: str
    trace_id: str
    user_id: str
    source_manifest: SourceManifest
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    locator_hint: str
    snippet: str
    score: float


@dataclass(frozen=True)
class OriginalRead:
    doc_id: str
    document_version: str | None
    locator: str
    excerpt: str
    content_hash: str


class LocalResearchToolAdapter:
    REQUIRED_TOOLS = frozenset({"list_documents", "keyword_search", "semantic_search", "read_document_range"})

    def __init__(self, search_backend: SearchBackend, documents_dir: str | Path) -> None:
        self.search_backend = search_backend
        self.documents_dir = Path(documents_dir).resolve()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-local-tool")

    @staticmethod
    def _allowed(context: ToolCallContext) -> dict[str, object]:
        return {item.doc_id: item for item in context.source_manifest.documents}

    def _run(self, callback, timeout: float):
        future = self._executor.submit(callback)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise LocalToolTimeout("research_tool_timeout") from exc

    def list_documents(self, context: ToolCallContext) -> list[dict]:
        return [item.model_dump(mode="json") for item in context.source_manifest.documents]

    def search(
        self,
        query: str,
        context: ToolCallContext,
        *,
        mode: str = "hybrid",
        top_k: int = 5,
        source_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        manifest_allowed = self._allowed(context)
        if source_ids is None:
            allowed = manifest_allowed
        else:
            requested = set(source_ids)
            outside = requested - set(manifest_allowed)
            if outside:
                raise ManifestAccessError(
                    "document_outside_manifest:" + ",".join(sorted(outside))
                )
            allowed = {
                doc_id: manifest_allowed[doc_id]
                for doc_id in source_ids
                if doc_id in manifest_allowed
            }
        rows = self._run(
            lambda: self.search_backend.search(
                query=query, top_k=top_k, mode=mode,
                filters={"doc_ids": list(allowed)}, trace_id=context.trace_id,
            ),
            context.timeout_seconds,
        )
        hits: list[SearchHit] = []
        for row in rows:
            doc_id = str(row.get("doc_id", ""))
            if doc_id not in allowed:
                continue
            index = int(row.get("chunk_index", 0))
            snippet = str(row.get("chunk_text") or row.get("text") or "").strip()
            if not snippet:
                continue
            hits.append(
                SearchHit(
                    doc_id=doc_id,
                    locator_hint=canonical_chunk_id(
                        doc_id,
                        row.get("chunk_id"),
                        index,
                    ),
                    snippet=snippet,
                    score=float(row.get("score", 0.0)),
                )
            )
        return hits

    def read_document_range(
        self,
        doc_id: str,
        context: ToolCallContext,
        *,
        start_line: int = 1,
        end_line: int | None = None,
        locator: str | None = None,
    ) -> OriginalRead:
        manifest_item = self._allowed(context).get(doc_id)
        if manifest_item is None:
            raise ManifestAccessError(f"document_outside_manifest:{doc_id}")
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise LocalToolError("invalid_document_range")

        def load():
            path = (self.documents_dir / f"{doc_id}.json").resolve()
            if path.parent != self.documents_dir or not path.is_file():
                raise ManifestAccessError(f"document_not_found:{doc_id}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            owner = payload.get("user_id") or payload.get("owner_id")
            if owner is not None and str(owner) != context.user_id:
                raise ManifestAccessError(f"document_forbidden:{doc_id}")
            return payload

        payload = self._run(load, context.timeout_seconds)
        content = LocalDocumentResolver._searchable_text(payload)
        content_hash = str(payload.get("content_hash") or hashlib.sha256(content.encode("utf-8")).hexdigest())
        if content_hash != manifest_item.content_hash:
            raise ManifestAccessError(f"document_version_changed:{doc_id}")
        version = payload.get("version") or payload.get("last_updated")
        if locator:
            requested_locator = canonical_chunk_id(doc_id, locator)
            for position, chunk in enumerate(payload.get("chunks") or []):
                if not isinstance(chunk, dict):
                    continue
                try:
                    index = int(chunk.get("index", position))
                except (TypeError, ValueError):
                    index = position
                chunk_locator = canonical_chunk_id(
                    doc_id,
                    chunk.get("chunk_id"),
                    index,
                )
                if chunk_locator != requested_locator:
                    continue
                excerpt = str(
                    chunk.get("text") or chunk.get("chunk_text") or ""
                ).strip()
                if not excerpt:
                    raise LocalToolError("empty_document_excerpt")
                return OriginalRead(
                    doc_id=doc_id,
                    document_version=(
                        str(version) if version is not None else None
                    ),
                    locator=chunk_locator,
                    excerpt=excerpt,
                    content_hash=content_hash,
                )
            raise LocalToolError(f"document_chunk_not_found:{requested_locator}")
        lines = content.splitlines() or [content]
        if start_line > len(lines):
            raise LocalToolError("document_range_out_of_bounds")
        effective_end = min(end_line or len(lines), len(lines))
        excerpt = "\n".join(lines[start_line - 1:effective_end]).strip()
        if not excerpt:
            raise LocalToolError("empty_document_excerpt")
        return OriginalRead(
            doc_id=doc_id,
            document_version=str(version) if version is not None else None,
            locator=f"line:{start_line}-{effective_end}",
            excerpt=excerpt,
            content_hash=content_hash,
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "LocalJsonSearchBackend", "LocalResearchToolAdapter", "LocalToolError", "LocalToolTimeout", "ManifestAccessError",
    "OriginalRead", "SearchHit", "ToolCallContext",
]
