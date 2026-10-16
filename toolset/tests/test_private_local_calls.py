"""Co-located tools and guards must never synchronously call the Agent over HTTP."""
import asyncio
import base64
import hashlib
import hmac

from data_persistence.private_files import get_private_file_store
from pipeline.files.parsing import parse_context
from tool_layer.attachment_tools import SearchAttachmentsTool
from tool_layer.search_library_tool import SearchLibraryTool


def test_private_tools_and_access_guard_read_current_storage_without_http(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "secret")
    monkeypatch.setenv("ATTACHMENT_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    monkeypatch.setenv("ATTACHMENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    store = get_private_file_store()
    source = tmp_path / "notes.txt"
    source.write_text("Local context sentinel", encoding="utf-8")
    common = {"filename": source.name, "mime_type": "text/plain", "extension": ".txt",
              "size_bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "owner_id": "alice", "dedupe_domain": "user:alice", "status": "ready",
              "blob_path": str(source), "key_id": "test", "created_at": 1, "updated_at": 1}
    store.create_attachment({**common, "id": "att_local", "scope": "chat"})
    store.replace_evidence("att_local", parse_context(source, "att_local")["items"])
    store.create_attachment({**common, "id": "ver_local", "scope": "library", "active": 1,
                             "knowledge_base_id": "kb_alice", "document_id": "doc_local",
                             "version_id": "ver_local", "source_scope": "personal"})
    store.replace_evidence("ver_local", parse_context(source, "ver_local")["items"])

    def forbidden_http(*args, **kwargs):
        raise AssertionError("a local private operation attempted HTTP")

    monkeypatch.setattr("requests.get", forbidden_http)
    monkeypatch.setattr("urllib.request.urlopen", forbidden_http)
    attachments = SearchAttachmentsTool()
    attachments.set_request_context(["att_local"], ["att_local"])
    library = SearchLibraryTool()
    token = hmac.new(b"secret", b"alice:kb_alice", hashlib.sha256).hexdigest()
    library.set_request_context("alice", "kb_alice", token)

    async def on_agent_event_loop():
        from agent.service.access_guard import AccessGuard
        with monkeypatch.context() as context:
            context.setattr("data_persistence.vector.get_file_vector_store", forbidden_http)
            assert attachments.execute(query="sentinel")["items"]
        assert library.execute(query="sentinel", mode="bm25")["items"]
        assert AccessGuard._private_source("att_local")["owner_id"] == "alice"
        store.update_attachment("ver_local", active=0)
        assert library.execute(query="sentinel", mode="bm25")["items"] == []
        store.soft_delete("att_local")
        assert attachments.execute(query="sentinel")["items"] == []

    asyncio.run(on_agent_event_loop())
