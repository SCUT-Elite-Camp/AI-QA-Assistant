"""Adapt Toolset source formats to request-local citation evidence.

Authorization remains owned by AccessGuard; adapters do not grant access.
"""

from typing import Any

from agent.evidence.locator import canonical_chunk_id
from agent.schemas.tool_execution import Evidence
from toolset.tool_layer import BaseTool


def _execute_generic(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    raw_result = tool.execute(**arguments)
    if isinstance(raw_result, dict):
        data = raw_result
    else:
        data = {"result": raw_result}
    return data, []


def _provenance_fields(row: dict) -> dict:
    return {key: row[key] for key in (
        "evidence_ref", "content_hash", "normalized_content_hash",
        "source_content_hash", "source_version", "read_status",
        "locator", "source_scope", "knowledge_base_id", "document_id", "version_id",
    ) if row.get(key) is not None}


def _execute_search(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
    direct_retrieval: bool = False,
) -> tuple[dict[str, Any], list[Evidence]]:
    query = arguments["query"]
    mode = arguments.get("mode", "hybrid")
    top_k = arguments.get("top_k", 5)
    filters = arguments.get("filters")
    min_score = float(getattr(tool, "min_score", 0.0))

    search_arguments = dict(
        query=query,
        top_k=top_k,
        mode=mode,
        filters=filters,
        min_score=min_score,
        trace_id=trace_id,
    )
    search = getattr(tool, "search_direct", None) if direct_retrieval else None
    if direct_retrieval and not callable(search):
        raise ValueError("direct_retrieval_not_supported")
    rows = (search if callable(search) else tool.search)(**search_arguments)
    evidence = [
        Evidence(
            doc_id=row["doc_id"],
            chunk_id=canonical_chunk_id(row["doc_id"], row.get("chunk_id"), row.get("chunk_index")),
            chunk_index=row.get("chunk_index", 0),
            title=row["title"],
            content=row.get("chunk_text", row.get("content", "")),
            source_url=row.get("source_url", ""),
            score=row["score"],
            retrieval_query=query,
            retrieval_mode=mode,
            retrieval_attempt=retrieval_attempt,
            **_provenance_fields(row),
        )
        for row in [*rows, *[context for parent in rows for context in parent.get('context_chunks', [])]]
    ]
    return {"result_count": len(evidence)}, evidence


def _execute_document_tool(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    data = tool.execute(**arguments)
    if not isinstance(data, dict):
        raise ValueError("document tools must return a dictionary")

    evidence: list[Evidence] = []
    if tool.name == "find_documents":
        return data, []
    documents = data.get("documents")
    if not isinstance(documents, list):
        raise ValueError("get_document must return a documents array")
    for document in documents:
        if not isinstance(document, dict) or not document.get("doc_id"):
            raise ValueError("get_document must return document metadata")
        doc_id = str(document["doc_id"])
        title = str(document.get("title") or doc_id)
        all_chunks = document.get("chunks", [])
        for chunk in all_chunks:
            if not isinstance(chunk, dict):
                continue
            index = int(chunk.get("index", 0))
            content = str(chunk.get("text") or chunk.get("chunk_text") or "").strip()
            if not doc_id or not content:
                continue
            evidence.append(Evidence(
                doc_id=doc_id,
                chunk_id=str(chunk.get("chunk_id") or f"{doc_id}::chunk_{index}"),
                chunk_index=index,
                title=title,
                content=content,
                source_url=str(document.get("source_url") or ""),
                score=1.0,
                retrieval_query=doc_id,
                retrieval_mode="document",
                retrieval_attempt=retrieval_attempt,
                **_provenance_fields({**document, **chunk}),
            ))
    return data, evidence


def _execute_library_tool(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    data = tool.execute(**arguments)
    if not isinstance(data, dict):
        raise ValueError("search_library must return a dictionary")
    if data.get("error"):
        raise RuntimeError("personal_source_service_unavailable")

    query = str(arguments.get("query") or "personal library search")
    mode = str(arguments.get("mode") or "hybrid")
    evidence: list[Evidence] = []
    primary = data.get('items', [])
    for item in [*primary, *[context for parent in primary for context in parent.get('context_chunks', [])]]:
        if not isinstance(item, dict):
            continue
        document_id = str(item.get("document_id") or "")
        evidence_id = str(item.get("evidence_id") or "")
        content = str(item.get("content") or "").strip()
        if not document_id or not evidence_id or not content:
            continue
        evidence.append(Evidence(
            doc_id=document_id,
            chunk_id=evidence_id,
            chunk_index=max(0, int(item.get("chunk_index", 0))),
            title=str(item.get("filename") or document_id),
            content=content,
            source_url=str(item.get("source_url") or ""),
            score=min(1.0, max(0.0, float(item.get("score", 0.0)))),
            retrieval_query=query,
            retrieval_mode=mode,
            retrieval_attempt=retrieval_attempt,
            source_type="personal",
            evidence_id=evidence_id,
            locator=(item.get("locator") if isinstance(item.get("locator"), dict) else None),
            source_scope=str(item.get("source_scope") or "personal"),
            knowledge_base_id=str(item.get("knowledge_base_id") or "") or None,
            document_id=document_id,
            version_id=str(item.get("version_id") or "") or None,
            content_hash=item.get("content_hash"),
            source_version=item.get("source_version"),
            evidence_ref=item.get("evidence_ref"),
            read_status=item.get("read_status"),
        ))
    return data, evidence


def _execute_attachment_tool(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    data = tool.execute(**arguments)
    if not isinstance(data, dict):
        raise ValueError("attachment tools must return a dictionary")
    if data.get("error"):
        raise RuntimeError("attachment_source_service_unavailable")

    query = str(
        arguments.get("query")
        or arguments.get("question")
        or "attachment inspection"
    )
    evidence: list[Evidence] = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        attachment_id = str(
            item.get("attachment_id") or arguments.get("attachment_id") or ""
        )
        evidence_id = str(item.get("evidence_id") or "")
        content = str(item.get("content") or "").strip()
        if not attachment_id or not evidence_id or not content:
            continue
        raw_score = item.get("score", item.get("confidence", 0.8))
        score = 0.8 if raw_score is None else min(1.0, max(0.0, float(raw_score)))
        evidence.append(Evidence(
            doc_id=attachment_id,
            chunk_id=evidence_id,
            chunk_index=0,
            title=str(item.get("filename") or f"附件 {attachment_id}"),
            content=content,
            source_url=f"/api/attachments/{attachment_id}/content",
            score=score,
            retrieval_query=query,
            retrieval_mode="attachment",
            retrieval_attempt=retrieval_attempt,
            source_type="attachment",
            attachment_id=attachment_id,
            evidence_id=evidence_id,
            locator=item.get("locator") if isinstance(item.get("locator"), dict) else {},
            version=max(1, int(item.get("version", 1))),
            confidence=item.get("confidence"),
            content_hash=item.get("content_hash"),
            evidence_ref=item.get("evidence_ref"),
            source_version=item.get("source_version"),
            normalized_content_hash=item.get("normalized_content_hash"),
            source_content_hash=item.get("source_content_hash"),
            read_status=item.get("read_status"),
            content_kind=item.get("content_kind", "excerpt"),
        ))
    return data, evidence


def _execute_wiki_evidence_tool(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    data = tool.execute(**arguments)
    if not isinstance(data, dict):
        raise ValueError("Wiki Evidence tool must return a dictionary")
    query = str(arguments.get("query") or "Wiki Evidence search")
    mode = str(arguments.get("mode") or "hybrid")
    evidence: list[Evidence] = []
    for row in data.get("items", []):
        if not isinstance(row, dict):
            continue
        source_scope = str(
            row.get("source_scope") or arguments.get("source_scope") or ""
        )
        document_id = str(row.get("document_id") or row.get("doc_id") or "")
        attachment_id = str(row.get("attachment_id") or "")
        doc_id = str(row.get("doc_id") or document_id or attachment_id)
        chunk_id = str(row.get("chunk_id") or row.get("evidence_id") or "")
        content = str(
            row.get("chunk_text") or row.get("content") or ""
        ).strip()
        if not doc_id or not chunk_id or not content:
            continue
        evidence.append(Evidence(
            doc_id=doc_id,
            chunk_id=chunk_id,
            chunk_index=max(0, int(row.get("chunk_index") or 0)),
            title=str(row.get("title") or row.get("filename") or doc_id),
            content=content,
            source_url=str(row.get("source_url") or ""),
            score=min(1.0, max(0.0, float(row.get("score") or 0.0))),
            retrieval_query=query,
            retrieval_mode=f"wiki_{mode}",
            retrieval_attempt=retrieval_attempt,
            source_type=(
                "personal" if source_scope == "personal" else "knowledge"
            ),
            attachment_id=attachment_id or None,
            evidence_id=str(row.get("evidence_id") or chunk_id),
            source_scope=source_scope or None,
            knowledge_base_id=row.get("knowledge_base_id") or None,
            document_id=document_id or doc_id,
            version_id=row.get("version_id") or None,
            locator=(
                row.get("locator")
                if isinstance(row.get("locator"), dict)
                else {}
            ),
        ))
    return {
        "result_count": len(evidence),
        "citation_authority": True,
    }, evidence


_ADAPTERS = {
    "search_documents": _execute_search,
    "find_documents": _execute_document_tool,
    "get_document": _execute_document_tool,
    "search_library": _execute_library_tool,
    "search_attachments": _execute_attachment_tool,
    "read_attachment_context": _execute_attachment_tool,
    "wiki_search_evidence": _execute_wiki_evidence_tool,
}
RETRIEVAL_TOOLS = frozenset(_ADAPTERS) - {"wiki_search_evidence"}


def execute_tool(
    tool: BaseTool,
    arguments: dict[str, Any],
    *,
    trace_id: str,
    retrieval_attempt: int,
    direct_retrieval: bool = False,
) -> tuple[dict[str, Any], list[Evidence]]:
    adapter = _ADAPTERS.get(tool.name, _execute_generic)
    if tool.name == "search_documents" and direct_retrieval and not callable(getattr(tool, "search_direct", None)):
        raise ValueError("direct_retrieval_not_supported")
    if tool.name == "search_documents" and not callable(getattr(tool, "search", None)):
        adapter = _execute_generic
    if adapter is _execute_search:
        return adapter(tool, arguments, trace_id=trace_id, retrieval_attempt=retrieval_attempt,
                       direct_retrieval=direct_retrieval)
    return adapter(tool, arguments, trace_id=trace_id, retrieval_attempt=retrieval_attempt)
