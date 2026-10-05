from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from attachment_service.vector_index import AttachmentVectorIndex


def test_attachment_vector_collection_is_independent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.delenv("ATTACHMENT_MILVUS_COLLECTION", raising=False)
    monkeypatch.delenv("MILVUS_COLLECTION", raising=False)

    index = AttachmentVectorIndex()

    assert index.collection == "attachment_evidence_cp2"


def test_attachment_vector_collection_rejects_knowledge_collection_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.setenv("ATTACHMENT_MILVUS_COLLECTION", " Doc_Chunks_CP2_BGEM3 ")
    monkeypatch.setenv("MILVUS_COLLECTION", "doc_chunks_cp2_bgem3")

    with pytest.raises(RuntimeError, match="must_be_isolated"):
        AttachmentVectorIndex()


def test_disabled_attachment_vector_index_does_not_block_service_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    monkeypatch.setenv("ATTACHMENT_MILVUS_COLLECTION", "same_collection")
    monkeypatch.setenv("MILVUS_COLLECTION", "same_collection")

    assert AttachmentVectorIndex().enabled is False


def test_search_uses_caller_vector_without_loading_embedding_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    index = AttachmentVectorIndex()
    calls = {"connect": 0, "embed": 0}

    class UnavailableStore:
        def connect(self):
            calls["connect"] += 1
            raise RuntimeError("milvus_down")

    def embed(_texts):
        calls["embed"] += 1
        return [[0.0] * 1024]

    monkeypatch.setattr(index, "_dependencies", lambda: (embed, UnavailableStore()))

    with pytest.raises(RuntimeError, match="milvus_down"):
        index.search_by_vector(["att_selected"], [0.0] * 1024, 5)

    assert calls == {"connect": 1, "embed": 0}


def test_vector_failure_uses_short_circuit_during_retry_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    monkeypatch.setenv("ATTACHMENT_VECTOR_RETRY_SECONDS", "30")
    index = AttachmentVectorIndex()
    calls = {"connect": 0}

    class UnavailableStore:
        def connect(self):
            calls["connect"] += 1
            raise RuntimeError("milvus_down")

    monkeypatch.setattr(index, "_dependencies", lambda: (lambda _: [], UnavailableStore()))

    with pytest.raises(RuntimeError, match="milvus_down"):
        index.search_by_vector(["att_selected"], [0.0] * 1024, 5)
    with pytest.raises(RuntimeError, match="attachment_vector_index_unavailable"):
        index.search_by_vector(["att_selected"], [0.0] * 1024, 5)

    assert calls["connect"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows uses isolated vector workers")
def test_replace_runs_embedding_in_short_lived_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "true")
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("attachment_service.vector_index.subprocess.run", run)
    index = AttachmentVectorIndex()
    index.replace("att_1", [{"evidence_id": "aev_1", "content": "正文"}])

    assert captured["command"][2] == "attachment_service.vector_worker"
    assert '"attachment_id": "att_1"' in captured["input"]
    assert captured["env"]["ATTACHMENT_VECTOR_CHILD"] == "1"
