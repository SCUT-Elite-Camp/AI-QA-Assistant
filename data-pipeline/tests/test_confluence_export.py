from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Callable

import pytest
import requests

from confluence_export import (
    ConfluenceClient,
    ConfluenceExporter,
    ConfluenceHTTPError,
    ConfluencePage,
    ConfluenceResponseError,
    ConfluenceStorageRenderer,
    load_confluence_config,
)
from parsers.markdown_parser import MarkdownParser
from pipeline.structure import build_document_sections
from shared_runtime.document_sections import stable_document_version_id


class FakeResponse:
    def __init__(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, handler: Callable[..., FakeResponse]) -> None:
        self.handler = handler
        self.headers: dict[str, str] = {}
        self.auth: tuple[str, str] | None = None
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float = 0) -> FakeResponse:
        self.calls.append((url, params))
        return self.handler(url=url, params=params, timeout=timeout)


def page_payload(
    page_id: str,
    title: str,
    *,
    parent_id: str = "",
    body: str = "<p>Body</p>",
    version: int = 1,
    parent_type: str = "page",
) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": title,
        "spaceId": "10",
        "parentId": parent_id,
        "parentType": parent_type,
        "position": 1,
        "version": {"number": version, "createdAt": "2026-09-08T00:00:00Z"},
        "body": {"storage": {"representation": "storage", "value": body}},
        "_links": {"webui": f"/wiki/spaces/TEST/pages/{page_id}"},
    }


def client_for(handler: Callable[..., FakeResponse], sleeps: list[float] | None = None) -> ConfluenceClient:
    return ConfluenceClient(
        base_url="https://example.atlassian.net/wiki",
        email="person@example.com",
        token="secret-token",
        session=FakeSession(handler),
        sleep=(sleeps.append if sleeps is not None else lambda _value: None),
    )


def test_v2_cursor_pagination_and_storage_body() -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        if "cursor=next" in url:
            return FakeResponse(200, {"results": [page_payload("2", "Child", parent_id="1")], "_links": {}})
        return FakeResponse(200, {
            "results": [page_payload("1", "Root")],
            "_links": {"next": "/wiki/api/v2/spaces/10/pages?cursor=next"},
        })

    client = client_for(handler)
    space = client.get_space_by_key("test")
    pages = client.list_pages(str(space["id"]))

    assert [page.page_id for page in pages] == ["1", "2"]
    session = client.session
    assert isinstance(session, FakeSession)
    assert session.calls[1][1] == {"status": "current", "body-format": "storage", "limit": 100}
    assert session.calls[2][1] is None


def test_429_honours_retry_after_without_exposing_token() -> None:
    responses = iter([
        FakeResponse(429, {}, {"Retry-After": "3"}),
        FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]}),
    ])
    sleeps: list[float] = []
    client = client_for(lambda **_kwargs: next(responses), sleeps)

    assert client.get_space_by_key("TEST")["id"] == "10"
    assert sleeps == [3.0]


def test_timeout_and_5xx_are_retried_but_403_is_not() -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def transient(**_kwargs: Any) -> FakeResponse:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.Timeout("temporary")
        if attempts["count"] == 2:
            return FakeResponse(503, {})
        return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})

    client = client_for(transient, sleeps)
    assert client.get_space_by_key("TEST")["id"] == "10"
    assert attempts["count"] == 3
    assert sleeps == [1, 2.0]

    forbidden = client_for(lambda **_kwargs: FakeResponse(403, {}))
    with pytest.raises(ConfluenceHTTPError) as error:
        forbidden.get_space_by_key("TEST")
    assert error.value.status_code == 403
    assert "secret-token" not in str(error.value)


def test_malformed_api_response_fails_closed() -> None:
    client = client_for(lambda **_kwargs: FakeResponse(200, {"unexpected": []}))
    with pytest.raises(ConfluenceResponseError):
        client.get_space_by_key("TEST")


def test_client_rejects_unsafe_identifiers_and_non_https_base() -> None:
    with pytest.raises(ValueError):
        ConfluenceClient(base_url="http://example.test/wiki", email="a", token="b")
    client = client_for(lambda **_kwargs: FakeResponse(200, {}))
    with pytest.raises(ValueError):
        client.get_page("../secret")
    with pytest.raises(ValueError):
        client.get_space_by_key("BAD/KEY")


def test_client_normalises_browser_space_url_to_cloud_rest_root() -> None:
    client = ConfluenceClient(
        base_url="https://example.atlassian.net/wiki/spaces/TEST/pages/123",
        email="a@example.com", token="token", session=FakeSession(lambda **_kwargs: FakeResponse(200, {})),
    )
    assert client.base_url == "https://example.atlassian.net/wiki"
    assert client._url("/api/v2/spaces") == "https://example.atlassian.net/wiki/api/v2/spaces"


def test_environment_overrides_local_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".confluence.env"
    env_file.write_text(
        "CONFLUENCE_BASE=https://file.atlassian.net/wiki\n"
        "CONFLUENCE_EMAIL=file@example.com\n"
        "CONFLUENCE_TOKEN=file-token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFLUENCE_BASE", "https://env.atlassian.net/wiki")
    monkeypatch.setenv("CONFLUENCE_EMAIL", "env@example.com")
    monkeypatch.setenv("CONFLUENCE_TOKEN", "env-token")

    config = load_confluence_config(env_file)

    assert config == {
        "base_url": "https://env.atlassian.net/wiki",
        "email": "env@example.com",
        "token": "env-token",
    }


def test_storage_markdown_and_section_tree_keep_structure() -> None:
    page = ConfluencePage(
        page_id="42", title="Meeting Minutes", space_id="10", parent_id="",
        position=1, version=3, last_updated="2026-09-08T00:00:00Z",
        source_url="https://example.atlassian.net/wiki/spaces/TEST/pages/42",
        storage_html="""
            <p local-id="hello">Hi all,</p>
            <h2 local-id="review">Quick Review</h2><p>Review text.</p>
            <p local-id="recap"><strong>Quick Recap</strong></p><p>Recap text.</p>
            <p local-id="actions"><strong>Action Items</strong></p>
            <ul><li>First action<ul><li>Nested action</li></ul></li></ul>
            <table><tr><th>Owner</th><th>Task</th></tr><tr><td>Alice</td><td>Ship</td></tr></table>
            <p><a href="/wiki/spaces/TEST">Space</a> <ac:link><ri:attachment ri:filename="plan.pdf" /></ac:link></p>
            <ac:structured-macro ac:name="warning"><ac:rich-text-body><p>Check this.</p></ac:rich-text-body></ac:structured-macro>
            <ac:structured-macro ac:name="third-party" ac:local-id="m1">opaque</ac:structured-macro>
        """,
    )
    rendered = ConfluenceStorageRenderer(
        base_url="https://example.atlassian.net/wiki", page=page,
    ).render()

    assert rendered.markdown.startswith("# Meeting Minutes\n")
    assert "### Quick Review" in rendered.markdown
    assert "  - Nested action" in rendered.markdown
    assert "| Owner | Task |" in rendered.markdown
    assert "https://example.atlassian.net/wiki/spaces/TEST" in rendered.markdown
    assert "/download/attachments/42/plan.pdf" in rendered.markdown
    assert any(item["code"] == "unsupported_macro" for item in rendered.warnings)

    metadata = {"page_id": "42", "title": "Meeting Minutes", "space_key": "TEST"}
    document = MarkdownParser().parse_text(rendered.markdown, source="index.md", metadata=metadata)
    sections = build_document_sections(document)
    root_children = [item.title for item in sections if item.parent_id == sections[0].id]

    assert "Hi all," not in [item.title for item in sections]
    assert root_children == ["Quick Review", "Quick Recap", "Action Items"]
    assert sections[0].subtree_block_ids
    assert all(item.line_start is not None and item.line_end is not None for item in sections)
    recap = next(item for item in sections if item.title == "Quick Recap")
    assert recap.provenance == "recovered_bold"


def test_existing_markdown_demotes_greeting_and_collapses_equivalent_title() -> None:
    markdown = """# Meeting Minutes of 2026/08/10 - CP2 reporting

# Hi all,

Thank you for attending.

## Quick Review

Review body.

# Follow-up Actions

## Alice

Ship the parser.
"""
    metadata = {"page_id": "8", "title": "Meeting Minutes of 2026-08-10 - CP2 reporting"}
    document = MarkdownParser().parse_text(markdown, source="index.md", metadata=metadata)
    sections = build_document_sections(document)

    assert [item.title for item in sections] == [
        "Meeting Minutes of 2026-08-10 - CP2 reporting",
        "Quick Review", "Follow-up Actions", "Alice",
    ]
    assert sections[1].parent_id == sections[0].id
    assert sections[2].parent_id == sections[0].id
    assert sections[3].parent_id == sections[2].id


def test_confluence_local_id_keeps_block_identity_across_page_versions() -> None:
    parser = MarkdownParser()
    first = parser.parse_text(
        "# Page\n\n<!-- confluence-local-id: stable-1 -->\nParagraph.\n",
        source="index.md", metadata={"page_id": "1", "title": "Page"},
    )
    second = parser.parse_text(
        "# Page\n\nNew introduction.\n\n<!-- confluence-local-id: stable-1 -->\nParagraph changed.\n",
        source="index.md", metadata={"page_id": "1", "title": "Page"},
    )

    first_block = next(block for block in first.content_blocks if block.locator.get("confluence_local_id"))
    second_block = next(block for block in second.content_blocks if block.locator.get("confluence_local_id"))
    assert first_block.locator["block_id"] == second_block.locator["block_id"]


def test_long_section_uses_bounded_deterministic_extractive_summary() -> None:
    body = " ".join(f"Sentence {number} explains a production detail." for number in range(100))
    markdown = f"# Page\n\n## Details\n\n{body}\n"
    document = MarkdownParser().parse_text(
        markdown, source="index.md", metadata={"page_id": "1", "title": "Page"},
    )

    first = build_document_sections(document)
    second = build_document_sections(document)
    details = next(item for item in first if item.title == "Details")

    assert details.summary_type == "extractive"
    assert details.summary == next(item for item in second if item.title == "Details").summary
    assert len(details.summary) < len(body)
    assert not details.summary.startswith("## Details")


def test_full_export_is_idempotent_and_prunes_only_tracked_pages(tmp_path: Path) -> None:
    state = {"include_child": True}

    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        pages = [page_payload("1", "Parent", body="<h1>Overview</h1><p>Parent body.</p>")]
        if state["include_child"]:
            pages.append(page_payload("2", "Child", parent_id="1", body="<p>Child body.</p>"))
        return FakeResponse(200, {"results": pages, "_links": {}})

    exporter = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path)
    first = exporter.export_space("TEST")
    second = exporter.export_space("TEST")

    assert first["exported"] == 2
    assert second["exported"] == 0
    assert second["skipped"] == 2
    child_relative = Path(first["pages"]["2"]["relative_path"])
    child_dir = tmp_path / "TEST" / child_relative
    assert (child_dir / "index.md").is_file()
    assert (child_dir / "page.storage.xhtml").read_text(encoding="utf-8") == "<p>Child body.</p>"
    metadata = json.loads((child_dir / "page.meta.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 2
    assert metadata["source_content_sha256"] == hashlib.sha256(b"<p>Child body.</p>").hexdigest()
    assert metadata["normalized_content_sha256"] == hashlib.sha256(
        (child_dir / "index.md").read_bytes()
    ).hexdigest()
    assert metadata["content_sha256"] == metadata["normalized_content_sha256"]
    tree = json.loads((child_dir / "section-tree.json").read_text(encoding="utf-8"))
    assert tree["nodes"][0]["title"] == "Child"
    assert tree["schema_version"] == 2
    assert tree["generator_version"] == ConfluenceExporter.artifact_version
    assert tree["space_id"] == "10"
    assert tree["section_id_version"] == 1
    assert tree["source_content_sha256"] == metadata["source_content_sha256"]
    assert tree["normalized_content_sha256"] == metadata["normalized_content_sha256"]
    assert tree["document_version_id"] == stable_document_version_id(
        source_scope="enterprise",
        knowledge_base_id="10",
        document_id="2",
        version=1,
        content_sha256=tree["content_sha256"],
    )
    assert all(node["version_id"] == tree["document_version_id"] for node in tree["nodes"])
    assert tree["blocks"]
    assert any(item["code"] == "section_tree_low_quality" for item in tree["warnings"])
    assert {
        "block_id", "block_type", "line_start", "line_end",
        "char_start", "char_end", "confluence_local_id",
    } <= tree["blocks"][0].keys()

    untracked = child_dir / "keep.txt"
    untracked.write_text("owned by user", encoding="utf-8")
    state["include_child"] = False
    third = exporter.export_space("TEST")

    assert "2" not in third["pages"]
    assert not (child_dir / "index.md").exists()
    assert not (child_dir / "page.storage.xhtml").exists()
    assert untracked.read_text(encoding="utf-8") == "owned by user"


def test_old_section_tree_contract_is_regenerated(tmp_path: Path) -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        return FakeResponse(200, {"results": [page_payload("1", "Page")], "_links": {}})

    exporter = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path)
    first = exporter.export_space("TEST")
    page_dir = tmp_path / "TEST" / Path(first["pages"]["1"]["relative_path"])
    tree_path = page_dir / "section-tree.json"
    stale_tree = json.loads(tree_path.read_text(encoding="utf-8"))
    stale_tree["schema_version"] = 1
    stale_tree.pop("blocks")
    tree_path.write_text(json.dumps(stale_tree), encoding="utf-8")

    second = exporter.export_space("TEST")
    refreshed = json.loads(tree_path.read_text(encoding="utf-8"))

    assert second["exported"] == 1
    assert second["skipped"] == 0
    assert refreshed["schema_version"] == 2
    assert refreshed["blocks"]


def test_export_without_raw_storage_artifact_is_regenerated(tmp_path: Path) -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        return FakeResponse(200, {
            "results": [page_payload("1", "Page", body="<p>Authoritative body.</p>")],
            "_links": {},
        })

    exporter = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path)
    first = exporter.export_space("TEST")
    page_dir = tmp_path / "TEST" / Path(first["pages"]["1"]["relative_path"])
    (page_dir / "page.storage.xhtml").unlink()

    second = exporter.export_space("TEST")

    assert second["exported"] == 1
    assert (page_dir / "page.storage.xhtml").read_text(encoding="utf-8") == "<p>Authoritative body.</p>"


def test_section_tree_with_wrong_document_identity_is_regenerated(tmp_path: Path) -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        return FakeResponse(200, {"results": [page_payload("1", "Page")], "_links": {}})

    exporter = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path)
    first = exporter.export_space("TEST")
    page_dir = tmp_path / "TEST" / Path(first["pages"]["1"]["relative_path"])
    tree_path = page_dir / "section-tree.json"
    stale_tree = json.loads(tree_path.read_text(encoding="utf-8"))
    stale_tree["document_version_id"] = "ver_stale_path_based_identity"
    for node in stale_tree["nodes"]:
        node["version_id"] = "ver_stale_path_based_identity"
    tree_path.write_text(json.dumps(stale_tree), encoding="utf-8")

    second = exporter.export_space("TEST")
    refreshed = json.loads(tree_path.read_text(encoding="utf-8"))

    assert second["exported"] == 1
    assert refreshed["document_version_id"] != "ver_stale_path_based_identity"
    assert all(
        node["version_id"] == refreshed["document_version_id"]
        for node in refreshed["nodes"]
    )


def test_page_only_export_resolves_ancestors_and_does_not_prune_manifest(tmp_path: Path) -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/pages/2"):
            return FakeResponse(200, page_payload("2", "Child", parent_id="1"))
        if url.endswith("/api/v2/pages/1"):
            return FakeResponse(200, page_payload("1", "Parent"))
        if url.endswith("/api/v2/spaces/10"):
            return FakeResponse(200, {"id": "10", "key": "TEST"})
        raise AssertionError(url)

    manifest = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path).export_page("2")

    assert manifest["full_sync"] is False
    assert set(manifest["pages"]) == {"2"}
    assert manifest["pages"]["2"]["relative_path"].startswith("Parent__1/Child__2")
    assert not (tmp_path / "TEST" / "Parent__1" / "index.md").exists()


def test_page_only_export_supports_folder_ancestor(tmp_path: Path) -> None:
    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/pages/2"):
            return FakeResponse(200, page_payload("2", "Child", parent_id="9", parent_type="folder"))
        if url.endswith("/api/v2/folders/9"):
            return FakeResponse(200, {
                "id": "9", "title": "Meeting notes", "spaceId": "10",
                "parentId": "", "parentType": "page", "position": 1,
                "version": {"number": 1, "createdAt": "2026-09-01T00:00:00Z"},
            })
        if url.endswith("/api/v2/spaces/10"):
            return FakeResponse(200, {"id": "10", "key": "TEST"})
        raise AssertionError(url)

    manifest = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path).export_page("2")

    assert manifest["status"] == "ok"
    assert manifest["pages"]["2"]["relative_path"] == "Meeting notes__9/Child__2"


def test_full_export_moves_renamed_page_and_preserves_untracked_files(tmp_path: Path) -> None:
    state = {"title": "Old name"}

    def handler(*, url: str, params: dict[str, Any] | None, timeout: float) -> FakeResponse:
        if url.endswith("/api/v2/spaces"):
            return FakeResponse(200, {"results": [{"id": "10", "key": "TEST"}]})
        return FakeResponse(200, {
            "results": [page_payload("1", state["title"])], "_links": {},
        })

    exporter = ConfluenceExporter(client=client_for(handler), output_dir=tmp_path)
    first = exporter.export_space("TEST")
    old_dir = tmp_path / "TEST" / Path(first["pages"]["1"]["relative_path"])
    state["title"] = "New name"
    second = exporter.export_space("TEST")
    new_dir = tmp_path / "TEST" / Path(second["pages"]["1"]["relative_path"])

    assert new_dir != old_dir
    assert (new_dir / "index.md").is_file()
    assert not (old_dir / "index.md").exists()


def test_orphan_and_cycle_paths_are_explicit() -> None:
    exporter = object.__new__(ConfluenceExporter)
    orphan = ConfluencePage("1", "Orphan", "10", "missing", 1, 1, "", "", "")
    cycle_a = ConfluencePage("2", "A", "10", "3", 1, 1, "", "", "")
    cycle_b = ConfluencePage("3", "B", "10", "2", 1, 1, "", "", "")

    paths, warnings = exporter._page_paths({"1": orphan, "2": cycle_a, "3": cycle_b})

    assert paths["1"].parts[0] == "_orphans"
    assert warnings["1"][0]["code"] == "missing_parent"
    assert any(item["code"] == "page_cycle" for items in warnings.values() for item in items)


def test_windows_safe_page_segment() -> None:
    value = ConfluenceExporter._safe_segment('CON:<bad>|name?*__123')
    assert not any(character in value for character in '<>:"/\\|?*')
    assert value.endswith("__123")
    long_value = ConfluenceExporter._safe_page_segment("标题" * 100, "987654")
    assert len(long_value) <= 92
    assert long_value.endswith("__987654")


def test_deep_page_tree_is_compacted_to_windows_path_budget() -> None:
    exporter = object.__new__(ConfluenceExporter)
    pages: dict[str, ConfluencePage] = {}
    for number in range(1, 7):
        page_id = str(10000000 + number)
        parent_id = str(10000000 + number - 1) if number > 1 else ""
        pages[page_id] = ConfluencePage(
            page_id, f"Very long readable Confluence page title number {number}" * 2,
            "10", parent_id, number, 1, "", "", "",
        )

    paths, warnings = exporter._page_paths(pages, max_relative_length=120)
    deepest = paths["10000006"]

    assert len(str(deepest)) <= 120
    assert all(part.endswith(f"__{10000000 + index}") for index, part in enumerate(deepest.parts, 1))
    assert paths["10000005"].parts == deepest.parts[:-1]
    assert warnings["10000006"][0]["code"] == "path_compacted"
