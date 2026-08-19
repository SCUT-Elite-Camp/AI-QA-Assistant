from __future__ import annotations

import base64
import io
import importlib
import sys
import time
from uuid import uuid4
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-internal-secret")
    monkeypatch.setenv("ATTACHMENT_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
    monkeypatch.setenv("ATTACHMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATTACHMENT_SCANNER", "disabled")
    monkeypatch.setenv("ALLOW_FAKE_ATTACHMENT_SCANNER", "true")
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    sys.modules.pop("attachment_service.app", None)
    module = importlib.import_module("attachment_service.app")
    with TestClient(module.app) as client:
        yield module, client


def _headers(filename: str = "企业制度.txt") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-internal-secret",
        "X-Filename-B64": base64.urlsafe_b64encode(filename.encode()).decode().rstrip("="),
        "X-Owner-ID": "user-1",
        "X-Dedupe-Domain": "user:user-1",
        "X-Scope": "chat",
        "Content-Type": "text/plain",
    }


def _wait_status(client: TestClient, attachment_id: str, expected: set[str]) -> dict:
    for _ in range(40):
        response = client.get(f"/v1/attachments/{attachment_id}", headers={"Authorization": "Bearer test-internal-secret"})
        if response.status_code == 404 and "deleted" in expected:
            return {"status": "deleted"}
        payload = response.json()
        if payload.get("status") in expected:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"attachment did not reach {expected}")


def test_upload_parse_download_and_async_physical_delete(service) -> None:
    module, client = service
    payload = "错误码 DB-1042".encode()
    response = client.post("/v1/attachments/att_test01", headers=_headers(), content=payload)
    assert response.status_code == 201
    assert response.json()["filename"] == "企业制度.txt"
    assert _wait_status(client, "att_test01", {"ready"})["status"] == "ready"
    evidence = client.get("/v1/attachments/att_test01/evidence", headers={"Authorization": "Bearer test-internal-secret"}).json()["items"]
    assert evidence[0]["content"] == "错误码 DB-1042"
    download = client.get("/v1/attachments/att_test01/content", headers={"Authorization": "Bearer test-internal-secret"})
    assert download.content == payload
    blob_path = Path(module.STORE.get_attachment("att_test01")["blob_path"])
    assert blob_path.exists()
    assert client.delete("/v1/attachments/att_test01", headers={"Authorization": "Bearer test-internal-secret"}).status_code == 204
    _wait_status(client, "att_test01", {"deleted"})
    for _ in range(40):
        if not blob_path.exists():
            break
        time.sleep(0.05)
    assert not blob_path.exists()


def test_empty_search_browses_only_explicitly_allowed_attachment(service) -> None:
    _, client = service
    for attachment_id, content in (
        ("att_selected", "所选报告正文"),
        ("att_other", "其他报告正文"),
    ):
        response = client.post(
            f"/v1/attachments/{attachment_id}",
            headers=_headers(f"{attachment_id}.txt"),
            content=content.encode(),
        )
        assert response.status_code == 201
        _wait_status(client, attachment_id, {"ready"})

    response = client.post(
        "/v1/search",
        headers={"Authorization": "Bearer test-internal-secret"},
        json={"attachment_ids": ["att_selected"], "query": "", "top_k": 5},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items and {item["attachment_id"] for item in items} == {"att_selected"}


def test_promote_reencrypts_blob_into_topic_dedupe_domain(service) -> None:
    module, client = service
    payload = "企业私有附件".encode()
    response = client.post("/v1/attachments/att_promote01", headers=_headers(), content=payload)
    assert response.status_code == 201
    _wait_status(client, "att_promote01", {"ready"})
    original = module.STORE.get_attachment("att_promote01")
    original_path = Path(original["blob_path"])

    promoted = client.patch(
        "/v1/attachments/att_promote01/scope",
        headers={"Authorization": "Bearer test-internal-secret"},
        json={"scope": "topic", "expires_at": None, "dedupe_domain": "topic:topic-1"},
    )
    assert promoted.status_code == 200
    current = module.STORE.get_attachment("att_promote01")
    assert current["scope"] == "topic"
    assert current["dedupe_domain"] == "topic:topic-1"
    assert Path(current["blob_path"]) != original_path
    assert not original_path.exists()
    download = client.get(
        "/v1/attachments/att_promote01/content",
        headers={"Authorization": "Bearer test-internal-secret"},
    )
    assert download.content == payload


def test_topic_promotion_requires_topic_dedupe_domain(service) -> None:
    _, client = service
    response = client.post("/v1/attachments/att_promote02", headers=_headers(), content=b"safe text")
    assert response.status_code == 201
    _wait_status(client, "att_promote02", {"ready"})
    promoted = client.patch(
        "/v1/attachments/att_promote02/scope",
        headers={"Authorization": "Bearer test-internal-secret"},
        json={"scope": "topic", "expires_at": None},
    )
    assert promoted.status_code == 422


def test_malware_is_quarantined_and_content_is_inaccessible(service, monkeypatch: pytest.MonkeyPatch) -> None:
    module, client = service

    def reject(*_args, **_kwargs):
        raise module.MalwareDetected("detected")

    monkeypatch.setattr(module, "scan_file", reject)
    response = client.post("/v1/attachments/att_bad01", headers=_headers("bad.txt"), content=b"malicious")
    assert response.status_code == 201
    assert response.json()["status"] == "quarantined"
    content = client.get("/v1/attachments/att_bad01/content", headers={"Authorization": "Bearer test-internal-secret"})
    assert content.status_code == 404
    inspect = client.post(
        "/v1/attachments/att_bad01/inspect",
        headers={"Authorization": "Bearer test-internal-secret"},
        json={"question": "分析这个文件"},
    )
    assert inspect.status_code == 409


def test_readiness_fails_closed_when_scanner_self_test_failed(service) -> None:
    module, client = service
    original = module.SCANNER_READY
    module.SCANNER_READY = False
    try:
        response = client.get(
            "/health/ready",
            headers={"Authorization": "Bearer test-internal-secret"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "scanner_unavailable"
    finally:
        module.SCANNER_READY = original


def test_length_mismatch_and_internal_auth_are_rejected(service) -> None:
    _, client = service
    assert client.get("/v1/attachments/att_missing").status_code == 401
    assert client.post("/v1/attachments/att_bad%22id", headers=_headers(), content=b"safe").status_code == 400
    headers = _headers("a.txt")
    headers["Content-Length"] = "99"
    response = client.post("/v1/attachments/att_length", headers=headers, content=b"short")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "length_mismatch"


def test_excel_http_flow_preserves_sheet_and_cell_range(service) -> None:
    import openpyxl

    _, client = service
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "故障统计"
    sheet.append(["错误码", "次数"])
    sheet.append(["DB-1042", 3])
    payload = io.BytesIO()
    workbook.save(payload)
    headers = _headers("故障统计.xlsx")
    headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response = client.post("/v1/attachments/att_excele2e", headers=headers, content=payload.getvalue())
    assert response.status_code == 201
    assert _wait_status(client, "att_excele2e", {"ready"})["status"] == "ready"
    items = client.get(
        "/v1/attachments/att_excele2e/evidence",
        headers={"Authorization": "Bearer test-internal-secret"},
    ).json()["items"]
    assert items[0]["source_type"] == "table"
    assert items[0]["locator"] == {"sheet": "故障统计", "cell_range": "A1:B2"}
    assert "DB-1042" in items[0]["content"]


def test_correction_http_flow_reindexes_latest_version_and_keeps_history(service) -> None:
    module, client = service
    response = client.post(
        "/v1/attachments/att_correcte2e", headers=_headers(), content="错误码 DB-104Z".encode(),
    )
    assert response.status_code == 201
    _wait_status(client, "att_correcte2e", {"ready"})
    evidence = client.get(
        "/v1/attachments/att_correcte2e/evidence",
        headers={"Authorization": "Bearer test-internal-secret"},
    ).json()["items"][0]
    corrected = client.patch(
        f"/v1/attachments/att_correcte2e/evidence/{evidence['evidence_id']}",
        headers={"Authorization": "Bearer test-internal-secret"},
        json={
            "expected_version": 1, "corrected_content": "错误码 DB-1042",
            "reason": "OCR字符修正", "actor_id": "editor-1",
        },
    )
    assert corrected.status_code == 200
    current = corrected.json()["items"][0]
    assert current["version"] == 2
    assert current["original_content"] == "错误码 DB-104Z"
    assert current["content"] == "错误码 DB-1042"
    assert module.STORE.get_attachment("att_correcte2e")["evidence_version"] == 2
    revisions = client.get(
        f"/v1/attachments/att_correcte2e/evidence/{evidence['evidence_id']}/revisions",
        headers={"Authorization": "Bearer test-internal-secret"},
    ).json()["items"]
    assert revisions[0]["from_version"] == 1
    assert revisions[0]["to_version"] == 2
    assert revisions[0]["actor_id"] == "editor-1"
    new_search = client.post(
        "/v1/search", headers={"Authorization": "Bearer test-internal-secret"},
        json={"attachment_ids": ["att_correcte2e"], "query": "DB-1042", "top_k": 5},
    ).json()["items"]
    old_search = client.post(
        "/v1/search", headers={"Authorization": "Bearer test-internal-secret"},
        json={"attachment_ids": ["att_correcte2e"], "query": "DB-104Z", "top_k": 5},
    ).json()["items"]
    assert new_search and new_search[0]["version"] == 2
    assert old_search == []


def test_expiry_physically_removes_original_previews_evidence_and_search(service) -> None:
    import fitz

    module, client = service
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Enterprise policy DB-1042 troubleshooting instructions and recovery steps")
    payload = document.tobytes()
    document.close()
    headers = _headers("policy.pdf")
    headers["Content-Type"] = "application/pdf"
    response = client.post("/v1/attachments/att_expiree2e", headers=headers, content=payload)
    assert response.status_code == 201
    _wait_status(client, "att_expiree2e", {"ready"})
    record = module.STORE.get_attachment("att_expiree2e")
    blob_path = Path(record["blob_path"])
    derivative_paths = [Path(item["blob_path"]) for item in module.STORE.list_derivatives("att_expiree2e")]
    assert blob_path.exists() and derivative_paths and all(path.exists() for path in derivative_paths)
    assert module.STORE.list_evidence(["att_expiree2e"])
    module.STORE.update_attachment("att_expiree2e", expires_at=int(time.time()) - 1)
    assert module.STORE.expire() == ["att_expiree2e"]
    module.STORE.enqueue(f"job_{uuid4().hex}", "att_expiree2e", "delete")
    _wait_status(client, "att_expiree2e", {"deleted"})
    for _ in range(40):
        if (
            not blob_path.exists()
            and all(not path.exists() for path in derivative_paths)
            and module.STORE.list_evidence(["att_expiree2e"]) == []
        ):
            break
        time.sleep(0.05)
    assert not blob_path.exists()
    assert all(not path.exists() for path in derivative_paths)
    assert module.STORE.list_evidence(["att_expiree2e"]) == []
    search = client.post(
        "/v1/search", headers={"Authorization": "Bearer test-internal-secret"},
        json={"attachment_ids": ["att_expiree2e"], "query": "DB-1042", "top_k": 5},
    )
    assert search.json()["items"] == []
