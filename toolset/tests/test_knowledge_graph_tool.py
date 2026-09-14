from __future__ import annotations

import hashlib
import hmac

from storage.knowledge_graph_store import KnowledgeGraphStore
from tool_layer.knowledge_graph_tool import SearchKnowledgeGraphTool


def _seed(store: KnowledgeGraphStore, *, scope: str, owner: str, kb: str) -> None:
    node = {
        "id": f"node-{scope}-{owner or 'shared'}",
        "node_type": "concept",
        "canonical_name": "Tool Routing",
        "aliases": ["工具路由"],
    }
    source = {
        "target_kind": "node", "target_id": node["id"],
        "document_version_id": "ver-1", "evidence_id": "ev-1",
    }
    store.replace_revision(
        source_scope=scope, owner_id=owner, knowledge_base_id=kb,
        revision="r1", input_hash="hash", nodes=[node], edges=[], sources=[source],
    )


def test_graph_tool_returns_navigation_only_for_configured_enterprise_kb(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    _seed(store, scope="enterprise", owner="", kb="enterprise-kb")
    tool = SearchKnowledgeGraphTool(
        store, enterprise_knowledge_base_id="enterprise-kb",
    )

    result = tool.execute(query="工具路由", source_scope="enterprise")

    assert result["citation_authority"] is False
    assert result["nodes"][0]["evidence_ids"] == ["ev-1"]


def test_personal_graph_requires_signed_request_context(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    _seed(store, scope="personal", owner="alice", kb="personal-kb")
    tool = SearchKnowledgeGraphTool(store)

    assert tool.execute(query="Tool", source_scope="personal")["nodes"] == []
    secret = "test-secret"
    token = hmac.new(secret.encode(), b"alice:personal-kb", hashlib.sha256).hexdigest()
    tool.set_personal_context("alice", "personal-kb", token, secret=secret)
    result = tool.execute(query="Tool", source_scope="personal")

    assert result["nodes"][0]["canonical_name"] == "Tool Routing"
