from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from parsers.markdown_parser import MarkdownParser
from pipeline.structure import build_document_sections
from shared_runtime.document_sections import stable_document_version_id


logger = logging.getLogger(__name__)


class ConfluenceError(RuntimeError):
    """Base error for the read-only Confluence export pipeline."""


class ConfluenceHTTPError(ConfluenceError):
    def __init__(self, status_code: int, url: str, message: str = "") -> None:
        safe_url = url.split("?", 1)[0]
        detail = f": {message}" if message else ""
        super().__init__(f"Confluence HTTP {status_code} for {safe_url}{detail}")
        self.status_code = status_code
        self.url = safe_url


class ConfluenceResponseError(ConfluenceError):
    """Raised when the API response does not match the expected contract."""


@dataclass(frozen=True)
class ConfluencePage:
    page_id: str
    title: str
    space_id: str
    parent_id: str
    position: int
    version: int
    last_updated: str
    source_url: str
    storage_html: str
    parent_type: str = "page"
    node_type: str = "page"


@dataclass(frozen=True)
class RenderedMarkdown:
    markdown: str
    warnings: list[dict[str, str]]


class ConfluenceClient:
    """Minimal read-only client for the Confluence Cloud REST API v2."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        token: str,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url or not email or not token:
            raise ValueError("Confluence base URL, email and API token are required")
        parsed_base = urlparse(base_url)
        if parsed_base.scheme != "https" or not parsed_base.netloc:
            raise ValueError("Confluence Cloud base URL must be an absolute HTTPS URL")
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        # People commonly paste a browser page/space URL. For direct Cloud
        # tenants every such URL shares the same REST root at <origin>/wiki.
        self.base_url = f"{origin}/wiki" if "/wiki" in parsed_base.path else base_url.rstrip("/")
        self.origin = origin
        self.session = session or requests.Session()
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json"})
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.sleep = sleep

    def get_space_by_key(self, space_key: str) -> dict[str, Any]:
        self._validate_space_key(space_key)
        payload = self._get_json("/api/v2/spaces", params={"keys": space_key, "limit": 2})
        results = payload.get("results")
        if not isinstance(results, list):
            raise ConfluenceResponseError("Space response is missing results")
        exact = [item for item in results if str(item.get("key", "")).casefold() == space_key.casefold()]
        if not exact:
            raise ConfluenceHTTPError(404, self._url("/api/v2/spaces"), f"space {space_key!r} not found")
        return exact[0]

    def get_space(self, space_id: str) -> dict[str, Any]:
        self._validate_content_id(space_id, "space id")
        payload = self._get_json(f"/api/v2/spaces/{space_id}")
        if not payload.get("id"):
            raise ConfluenceResponseError(f"Space {space_id} response is missing id")
        return payload

    def list_pages(self, space_id: str) -> list[ConfluencePage]:
        self._validate_content_id(space_id, "space id")
        path: str | None = f"/api/v2/spaces/{space_id}/pages"
        params: dict[str, Any] | None = {
            "status": "current", "body-format": "storage", "limit": 100,
        }
        pages: list[ConfluencePage] = []
        while path:
            payload = self._get_json(path, params=params)
            results = payload.get("results")
            if not isinstance(results, list):
                raise ConfluenceResponseError("Pages response is missing results")
            pages.extend(self._normalise_page(item) for item in results)
            next_path = payload.get("_links", {}).get("next")
            path = str(next_path) if next_path else None
            params = None
        return pages

    def get_page(self, page_id: str) -> ConfluencePage:
        self._validate_content_id(page_id, "page id")
        payload = self._get_json(
            f"/api/v2/pages/{page_id}", params={"body-format": "storage"},
        )
        return self._normalise_page(payload)

    def get_page_with_ancestors(self, page_id: str) -> list[ConfluencePage]:
        pages: list[ConfluencePage] = []
        seen: set[str] = set()
        current = self.get_page(page_id)
        while True:
            if current.page_id in seen:
                raise ConfluenceResponseError(f"Cycle detected in page ancestry at {current.page_id}")
            seen.add(current.page_id)
            pages.append(current)
            if not current.parent_id:
                break
            try:
                current = self.get_content_node(current.parent_id, current.parent_type)
            except ConfluenceHTTPError as exc:
                if exc.status_code == 404:
                    break
                raise
        return list(reversed(pages))

    def get_content_node(self, content_id: str, content_type: str) -> ConfluencePage:
        normalised_type = (content_type or "page").casefold()
        if normalised_type == "page":
            return self.get_page(content_id)
        if normalised_type == "folder":
            return self.get_folder(content_id)
        raise ConfluenceResponseError(f"Unsupported Confluence parent type: {content_type or 'unknown'}")

    def get_folder(self, folder_id: str) -> ConfluencePage:
        self._validate_content_id(folder_id, "folder id")
        value = self._get_json(f"/api/v2/folders/{folder_id}")
        identifier = str(value.get("id") or "")
        title = str(value.get("title") or "").strip()
        space_id = str(value.get("spaceId") or "")
        if not identifier or not title or not space_id:
            raise ConfluenceResponseError("Folder response is missing id, title or spaceId")
        version = value.get("version") or {}
        return ConfluencePage(
            page_id=identifier,
            title=title,
            space_id=space_id,
            parent_id=str(value.get("parentId") or ""),
            position=int(value.get("position") or 0),
            version=int(version.get("number") or 0),
            last_updated=str(version.get("createdAt") or value.get("createdAt") or ""),
            source_url="",
            storage_html="",
            parent_type=str(value.get("parentType") or "page"),
            node_type="folder",
        )

    def _get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._url(path_or_url)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    break
                self.sleep(min(2 ** attempt, 30))
                continue

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt + 1 >= self.max_attempts:
                    raise ConfluenceHTTPError(response.status_code, url)
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = float(min(2 ** attempt, 30))
                self.sleep(max(0.0, min(delay, 60.0)))
                continue
            if response.status_code >= 400:
                raise ConfluenceHTTPError(response.status_code, url)
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ConfluenceResponseError(f"Invalid JSON from {url.split('?', 1)[0]}") from exc
            if not isinstance(payload, dict):
                raise ConfluenceResponseError(f"Expected object response from {url.split('?', 1)[0]}")
            return payload
        raise ConfluenceError(f"Confluence request failed for {url.split('?', 1)[0]}: {type(last_error).__name__}")

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        if path_or_url.startswith("/wiki/"):
            return self.origin + path_or_url
        return urljoin(self.base_url + "/", path_or_url.lstrip("/"))

    def _normalise_page(self, value: dict[str, Any]) -> ConfluencePage:
        page_id = str(value.get("id") or "")
        title = str(value.get("title") or "").strip()
        space_id = str(value.get("spaceId") or "")
        if not page_id or not title or not space_id:
            raise ConfluenceResponseError("Page response is missing id, title or spaceId")
        try:
            self._validate_content_id(page_id, "page id")
            self._validate_content_id(space_id, "space id")
            if value.get("parentId"):
                self._validate_content_id(str(value["parentId"]), "parent page id")
        except ValueError as exc:
            raise ConfluenceResponseError(str(exc)) from exc
        body = value.get("body") or {}
        storage = body.get("storage") or {}
        storage_html = str(storage.get("value") or "") if isinstance(storage, dict) else ""
        version = value.get("version") or {}
        links = value.get("_links") or {}
        webui = str(links.get("webui") or "")
        source_url = self._url(webui) if webui else f"{self.base_url}/pages/{page_id}"
        return ConfluencePage(
            page_id=page_id,
            title=title,
            space_id=space_id,
            parent_id=str(value.get("parentId") or ""),
            position=int(value.get("position") or 0),
            version=int(version.get("number") or 0),
            last_updated=str(version.get("createdAt") or ""),
            source_url=source_url,
            storage_html=storage_html,
            parent_type=str(value.get("parentType") or "page"),
            node_type="page",
        )

    @staticmethod
    def _validate_content_id(value: str, label: str) -> None:
        if not str(value).isdigit():
            raise ValueError(f"Confluence {label} must contain digits only")

    @staticmethod
    def _validate_space_key(value: str) -> None:
        if not value or len(value) > 255 or not re.fullmatch(r"[\w.~+-]+", value, flags=re.UNICODE):
            raise ValueError("Confluence space key contains unsupported characters")


class ConfluenceStorageRenderer:
    """Convert Confluence storage XHTML into deterministic Markdown."""

    renderer_version = 1
    _known_macros = {"code", "info", "note", "warning", "panel", "expand", "status", "toc"}

    def __init__(self, *, base_url: str, page: ConfluencePage) -> None:
        self.base_url = base_url.rstrip("/")
        self.page = page
        self.warnings: list[dict[str, str]] = []

    def render(self) -> RenderedMarkdown:
        soup = BeautifulSoup(self.page.storage_html or "", "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        fragments = [f"# {self._escape(self.page.title)}"]
        for child in list((soup.body or soup).children):
            if isinstance(child, Tag):
                rendered = self._block(child)
                if rendered.strip():
                    fragments.append(rendered.strip())
        markdown = "\n\n".join(fragments).strip() + "\n"
        return RenderedMarkdown(markdown=markdown, warnings=self.warnings)

    def _block(self, tag: Tag) -> str:
        name = (tag.name or "").lower()
        prefix = self._local_id_comment(tag)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = min(6, int(name[1]) + 1)
            return prefix + f"{'#' * level} {self._inline_children(tag).strip()}"
        if name == "p":
            return prefix + self._inline_children(tag).strip()
        if name in {"ul", "ol"}:
            return self._render_list(tag, depth=0)
        if name == "table":
            return prefix + self._render_table(tag)
        if name == "blockquote":
            content = self._render_container(tag)
            return prefix + "\n".join(f"> {line}" if line else ">" for line in content.splitlines())
        if name == "pre":
            language = str(tag.get("data-language") or "")
            return prefix + f"```{language}\n{tag.get_text().rstrip()}\n```"
        if name == "ac:structured-macro":
            return prefix + self._render_macro(tag)
        if name in {"ac:task-list", "ac:task"}:
            return prefix + self._render_task(tag)
        if name in {"div", "section", "article", "main", "aside", "header", "footer"}:
            return self._render_container(tag)
        return self._render_container(tag)

    def _render_container(self, tag: Tag) -> str:
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, Tag):
                value = self._block(child)
                if value.strip():
                    parts.append(value.strip())
            elif isinstance(child, NavigableString) and child.strip():
                parts.append(self._escape(str(child).strip()))
        return "\n\n".join(parts)

    def _render_list(self, tag: Tag, depth: int) -> str:
        ordered = (tag.name or "").lower() == "ol"
        lines: list[str] = []
        number = int(tag.get("start") or 1) if ordered else 1
        for item in tag.find_all("li", recursive=False):
            local_id = self._local_id_comment(item).strip()
            if local_id:
                lines.append("  " * depth + local_id)
            inline_parts: list[str] = []
            nested: list[Tag] = []
            for child in item.children:
                if isinstance(child, Tag) and (child.name or "").lower() in {"ul", "ol"}:
                    nested.append(child)
                elif isinstance(child, Tag):
                    inline_parts.append(self._inline(child))
                elif isinstance(child, NavigableString):
                    inline_parts.append(self._escape(str(child)))
            marker = f"{number}." if ordered else "-"
            text = self._clean_inline("".join(inline_parts))
            lines.append(f"{'  ' * depth}{marker} {text}".rstrip())
            for nested_list in nested:
                lines.append(self._render_list(nested_list, depth + 1))
            number += 1
        return "\n".join(lines)

    def _render_table(self, table: Tag) -> str:
        rows: list[list[str]] = []
        header_flags: list[bool] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            rows.append([self._inline_children(cell).replace("|", "\\|").replace("\n", " ").strip() for cell in cells])
            header_flags.append(any((cell.name or "").lower() == "th" for cell in cells))
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        headers = rows[0] if header_flags[0] else [""] * width
        body = rows[1:] if header_flags[0] else rows
        result = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        result.extend("| " + " | ".join(row) + " |" for row in body)
        return "\n".join(result)

    def _render_macro(self, tag: Tag) -> str:
        name = str(tag.get("ac:name") or tag.get("data-macro-name") or "unknown").lower()
        local_id = str(tag.get("ac:local-id") or tag.get("local-id") or "")
        params = {
            str(param.get("ac:name") or ""): param.get_text(" ", strip=True)
            for param in tag.find_all("ac:parameter")
        }
        plain = tag.find("ac:plain-text-body")
        rich = tag.find("ac:rich-text-body")
        body = plain.get_text() if plain else (self._render_container(rich) if rich else "")
        if name == "code":
            return f"```{params.get('language', '')}\n{body.rstrip()}\n```"
        if name == "toc":
            return "[Confluence TOC]"
        if name == "status":
            label = params.get("title") or tag.get_text(" ", strip=True) or params.get("colour", "")
            return f"**Status:** {self._escape(str(label))}".rstrip()
        if name in {"info", "note", "warning", "panel", "expand"}:
            label = params.get("title") or name.title()
            text = body.strip()
            return "\n".join([f"> **{self._escape(label)}**", *[f"> {line}" for line in text.splitlines()]])
        self.warnings.append({
            "code": "unsupported_macro", "macro": name, "local_id": local_id,
        })
        text = self._clean_inline(tag.get_text(" ", strip=True))
        suffix = f": {text}" if text else ""
        return f"> [Confluence macro: {name}{suffix}]"

    def _render_task(self, tag: Tag) -> str:
        state = tag.find("ac:task-status")
        complete = bool(state and state.get_text(strip=True).lower() == "complete")
        body = tag.find("ac:task-body") or tag
        return f"- [{'x' if complete else ' '}] {self._clean_inline(body.get_text(' ', strip=True))}"

    def _inline_children(self, tag: Tag) -> str:
        return self._clean_inline("".join(self._inline(child) for child in tag.children))

    def _inline(self, node: Any) -> str:
        if isinstance(node, NavigableString):
            return self._escape(str(node))
        if not isinstance(node, Tag):
            return ""
        name = (node.name or "").lower()
        content = "".join(self._inline(child) for child in node.children)
        if name in {"strong", "b"}:
            return f"**{content.strip()}**"
        if name in {"em", "i"}:
            return f"*{content.strip()}*"
        if name == "code":
            code_text = node.get_text().replace("`", "\\`")
            return f"`{code_text}`"
        if name == "br":
            return "  \n"
        if name == "a":
            label = self._clean_inline(content) or str(node.get("href") or "link")
            href = self._absolute_url(str(node.get("href") or ""))
            return f"[{label}]({href})" if href else label
        if name == "img":
            alt = self._escape(str(node.get("alt") or "image"))
            src = self._absolute_url(str(node.get("src") or ""))
            return f"![{alt}]({src})" if src else f"![{alt}]"
        if name == "ri:attachment":
            filename = str(node.get("ri:filename") or node.get("filename") or "attachment")
            return f"[{self._escape(filename)}]({self._attachment_url(filename)})"
        if name == "ac:link":
            attachment = node.find("ri:attachment")
            if attachment:
                filename = str(attachment.get("ri:filename") or "attachment")
                return f"[{self._escape(filename)}]({self._attachment_url(filename)})"
            page = node.find("ri:page")
            label_tag = node.find("ac:plain-text-link-body") or node.find("ac:link-body")
            label = label_tag.get_text(" ", strip=True) if label_tag else ""
            if page:
                title = str(page.get("ri:content-title") or label or "Confluence page")
                self.warnings.append({"code": "unresolved_page_link", "title": title})
                return self._escape(label or title)
        return content

    def _absolute_url(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        origin = f"{urlparse(self.base_url).scheme}://{urlparse(self.base_url).netloc}"
        if value.startswith("/wiki/"):
            return origin + value
        return urljoin(self.page.source_url, value)

    def _attachment_url(self, filename: str) -> str:
        return f"{self.base_url}/download/attachments/{quote(self.page.page_id)}/{quote(filename)}"

    @staticmethod
    def _local_id_comment(tag: Tag) -> str:
        value = str(tag.get("local-id") or tag.get("ac:local-id") or "").strip()
        return f"<!-- confluence-local-id: {value} -->\n" if value else ""

    @staticmethod
    def _clean_inline(value: str) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", value).strip()

    @staticmethod
    def _escape(value: str) -> str:
        return re.sub(r"([\\`*_[\]#])", r"\\\1", value)


class ConfluenceExporter:
    """Export pages to a mirrored Markdown tree and auditable sidecars."""

    artifact_names = (
        "page.storage.xhtml", "index.md", "page.meta.json", "section-tree.json",
    )
    artifact_version = 5

    def __init__(self, *, client: ConfluenceClient, output_dir: Path) -> None:
        self.client = client
        self.output_dir = Path(output_dir)
        self.markdown_parser = MarkdownParser()

    def export_space(self, space_key: str) -> dict[str, Any]:
        space = self.client.get_space_by_key(space_key)
        space_id = str(space.get("id") or "")
        if not space_id:
            raise ConfluenceResponseError("Space response is missing id")
        pages = self.client.list_pages(space_id)
        hydrated = [page if page.storage_html else self.client.get_page(page.page_id) for page in pages]
        nodes = self._include_missing_ancestors(hydrated)
        return self._export(space_key=space_key, space_id=space_id, pages=nodes, full=True)

    def export_page(self, page_id: str) -> dict[str, Any]:
        pages = self.client.get_page_with_ancestors(page_id)
        target = pages[-1]
        space = self.client.get_space(target.space_id)
        space_key = str(space.get("key") or "")
        if not space_key:
            raise ConfluenceResponseError("Space response is missing key")
        return self._export(
            space_key=space_key, space_id=target.space_id,
            pages=pages, full=False, selected_ids={target.page_id},
        )

    def _export(
        self,
        *,
        space_key: str,
        space_id: str,
        pages: list[ConfluencePage],
        full: bool,
        selected_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        space_root = self.output_dir / self._safe_segment(space_key, max_length=60)
        manifest_path = space_root / "manifest.json"
        old_manifest = self._load_manifest(manifest_path)
        old_pages = dict(old_manifest.get("pages") or {})
        page_map = {page.page_id: page for page in pages}
        targets = [
            page for page in pages
            if page.node_type == "page" and (not selected_ids or page.page_id in selected_ids)
        ]
        paths, path_warnings = self._page_paths(
            page_map, max_relative_length=self._relative_path_budget(space_root),
        )
        new_pages = {} if full else dict(old_pages)
        errors: list[dict[str, str]] = []
        exported = 0
        skipped = 0

        for page in sorted(targets, key=lambda item: (paths[item.page_id].as_posix(), item.position)):
            relative = paths[page.page_id]
            destination = space_root / relative
            try:
                renderer = ConfluenceStorageRenderer(base_url=self.client.base_url, page=page)
                rendered = renderer.render()
                source_content_hash = hashlib.sha256(
                    page.storage_html.encode("utf-8")
                ).hexdigest()
                normalized_content_hash = hashlib.sha256(
                    rendered.markdown.encode("utf-8")
                ).hexdigest()
                warnings = [*path_warnings.get(page.page_id, []), *rendered.warnings]
                ancestor_path = self._ancestor_path(
                    page, page_map, space_id=space_id, space_key=space_key,
                )
                metadata = {
                    "schema_version": 2,
                    "exporter_version": self.artifact_version,
                    "renderer_version": ConfluenceStorageRenderer.renderer_version,
                    "source_type": "confluence_cloud",
                    "page_id": page.page_id,
                    "space_id": space_id,
                    "space_key": space_key,
                    "parent_id": page.parent_id,
                    "parent_type": page.parent_type,
                    "ancestor_path": ancestor_path,
                    "title": page.title,
                    "version": page.version,
                    "last_updated": page.last_updated,
                    "source_url": page.source_url,
                    "source_content_sha256": source_content_hash,
                    "normalized_content_sha256": normalized_content_hash,
                    # Backward-compatible identity for current Markdown-derived Evidence.
                    "content_sha256": normalized_content_hash,
                    "warnings": warnings,
                }
                document = self.markdown_parser.parse_text(
                    rendered.markdown, source=str(destination / "index.md"), metadata=metadata,
                )
                sections = build_document_sections(document)
                if sections and sections[0].quality == "low":
                    warnings.append({
                        "code": "section_tree_low_quality",
                        "reason": "no_navigable_sections",
                    })
                tree = {
                    "schema_version": 2,
                    "generator_version": self.artifact_version,
                    "section_id_version": 1,
                    "space_id": space_id,
                    "page_id": page.page_id,
                    "version": page.version,
                    "document_version_id": document.version_id,
                    "source_url": page.source_url,
                    "source_content_sha256": source_content_hash,
                    "normalized_content_sha256": normalized_content_hash,
                    "content_sha256": normalized_content_hash,
                    "quality": sections[0].quality if sections else "low",
                    "warnings": warnings,
                    "blocks": [self._serialize_block(block) for block in document.content_blocks],
                    "nodes": [section.model_dump(mode="json") for section in sections],
                }
                entry = {
                    "page_id": page.page_id,
                    "parent_id": page.parent_id,
                    "parent_type": page.parent_type,
                    "ancestor_path": ancestor_path,
                    "title": page.title,
                    "version": page.version,
                    "last_updated": page.last_updated,
                    "source_url": page.source_url,
                    "relative_path": relative.as_posix(),
                    "source_content_sha256": source_content_hash,
                    "normalized_content_sha256": normalized_content_hash,
                    "content_sha256": normalized_content_hash,
                    "status": "ok",
                    "warnings": warnings,
                }
                old = old_pages.get(page.page_id) or {}
                complete = all((destination / name).is_file() for name in self.artifact_names)
                if (
                    complete
                    and self._artifact_contract_current(destination)
                    and old.get("version") == page.version
                    and old.get("source_content_sha256") == source_content_hash
                    and old.get("normalized_content_sha256") == normalized_content_hash
                    and old.get("relative_path") == relative.as_posix()
                ):
                    skipped += 1
                else:
                    self._write_page(
                        destination, page.storage_html, rendered.markdown, metadata, tree,
                    )
                    exported += 1
                new_pages[page.page_id] = entry
            except Exception as exc:  # noqa: BLE001 - preserve the last good page on any conversion error
                logger.exception("Failed to export Confluence page %s", page.page_id)
                errors.append({"page_id": page.page_id, "title": page.title, "error": str(exc)})
                if page.page_id not in new_pages and page.page_id in old_pages:
                    new_pages[page.page_id] = old_pages[page.page_id]

        if full and not errors:
            active_ids = {page.page_id for page in pages if page.node_type == "page"}
            for stale_id, stale in old_pages.items():
                if stale_id not in active_ids:
                    self._remove_tracked_artifacts(space_root, stale)
            for page_id, entry in new_pages.items():
                old = old_pages.get(page_id) or {}
                if old.get("relative_path") and old.get("relative_path") != entry.get("relative_path"):
                    self._remove_tracked_artifacts(space_root, old)
        elif not full:
            for page_id in selected_ids or set():
                old = old_pages.get(page_id) or {}
                entry = new_pages.get(page_id) or {}
                if old.get("relative_path") and old.get("relative_path") != entry.get("relative_path"):
                    self._remove_tracked_artifacts(space_root, old)

        manifest = {
            "schema_version": 1,
            "source_type": "confluence_cloud",
            "space_id": space_id,
            "space_key": space_key,
            "full_sync": full,
            "status": "ok" if not errors else "partial",
            "exported": exported,
            "skipped": skipped,
            "failed": len(errors),
            "errors": errors,
            "pages": new_pages,
        }
        self._atomic_write_json(manifest_path, manifest)
        return manifest

    @staticmethod
    def _ancestor_path(
        page: ConfluencePage, page_map: dict[str, ConfluencePage], *,
        space_id: str, space_key: str,
    ) -> list[dict[str, str]]:
        """Return source identities for the space/folder/page ancestry, excluding self."""
        values: list[dict[str, str]] = [
            {"id": space_id, "title": space_key, "type": "space"},
        ]
        chain: list[dict[str, str]] = []
        seen = {page.page_id}
        parent_id = page.parent_id
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = page_map.get(parent_id)
            if parent is None:
                break
            chain.append({
                "id": parent.page_id, "title": parent.title,
                "type": parent.node_type,
            })
            parent_id = parent.parent_id
        values.extend(reversed(chain))
        return values

    def _include_missing_ancestors(self, pages: list[ConfluencePage]) -> list[ConfluencePage]:
        nodes = {page.page_id: page for page in pages}
        for page in list(pages):
            current = page
            seen = {current.page_id}
            while current.parent_id and current.parent_id not in nodes:
                if current.parent_id in seen:
                    break
                seen.add(current.parent_id)
                try:
                    parent = self.client.get_content_node(current.parent_id, current.parent_type)
                except (ConfluenceHTTPError, ConfluenceResponseError) as exc:
                    logger.warning(
                        "Could not resolve %s parent %s for %s: %s",
                        current.parent_type, current.parent_id, current.page_id, exc,
                    )
                    break
                nodes[parent.page_id] = parent
                current = parent
        return list(nodes.values())

    def _page_paths(
        self,
        pages: dict[str, ConfluencePage],
        *,
        max_relative_length: int | None = None,
    ) -> tuple[dict[str, Path], dict[str, list[dict[str, str]]]]:
        cache: dict[str, Path] = {}
        warnings: dict[str, list[dict[str, str]]] = {}

        def resolve(page_id: str, trail: tuple[str, ...] = ()) -> Path:
            if page_id in cache:
                return cache[page_id]
            page = pages[page_id]
            segment = self._safe_page_segment(page.title, page.page_id)
            if page_id in trail:
                warnings.setdefault(page_id, []).append({"code": "page_cycle", "page_id": page_id})
                path = Path("_cycles") / segment
            elif page.parent_id and page.parent_id in pages:
                path = resolve(page.parent_id, (*trail, page_id)) / segment
            elif page.parent_id:
                warnings.setdefault(page_id, []).append({
                    "code": "missing_parent", "parent_id": page.parent_id,
                })
                path = Path("_orphans") / segment
            else:
                path = Path(segment)
            cache[page_id] = path
            return path

        for identifier in pages:
            resolve(identifier)

        if max_relative_length and cache:
            max_depth = max(len(path.parts) for path in cache.values())
            separators = max(0, max_depth - 1)
            segment_limit = (max_relative_length - separators) // max_depth
            minimum = max(
                len("__" + self._safe_segment(page.page_id, max_length=30)) + 1
                for page in pages.values()
            )
            if segment_limit < minimum:
                raise ConfluenceResponseError(
                    "Export root is too deep for the Confluence hierarchy on Windows; "
                    "choose a shorter --output-dir"
                )
            compact_segments = {
                self._safe_page_segment(page.title, page.page_id):
                self._safe_page_segment(page.title, page.page_id, max_length=segment_limit)
                for page in pages.values()
            }
            for page_id, path in list(cache.items()):
                compact = Path(*(compact_segments.get(part, part[:segment_limit]) for part in path.parts))
                if compact != path:
                    warnings.setdefault(page_id, []).append({
                        "code": "path_compacted",
                        "original_length": str(len(str(path))),
                        "compacted_length": str(len(str(compact))),
                    })
                    cache[page_id] = compact
        return cache, warnings

    @staticmethod
    def _relative_path_budget(space_root: Path) -> int:
        # Keep enough room below the directory for the longest artifact name and
        # the atomic-write temporary suffix under the traditional Windows limit.
        max_directory_path = 220
        root_length = len(str(space_root.absolute()))
        budget = max_directory_path - root_length - 1
        if budget < 40:
            raise ConfluenceResponseError(
                "Confluence output directory is too deep; choose a shorter --output-dir"
            )
        return budget

    def _write_page(
        self, destination: Path, storage_xhtml: str, markdown: str,
        metadata: dict[str, Any], tree: dict[str, Any],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        self._atomic_write_text(destination / "page.storage.xhtml", storage_xhtml)
        self._atomic_write_text(destination / "index.md", markdown)
        self._atomic_write_json(destination / "page.meta.json", metadata)
        self._atomic_write_json(destination / "section-tree.json", tree)

    @staticmethod
    def _serialize_block(block: Any) -> dict[str, Any]:
        locator = dict(block.locator)
        return {
            "block_id": locator.pop("block_id"),
            "block_type": str(block.block_type),
            "level": block.level,
            "text": block.text,
            "line_start": locator.pop("line_start"),
            "line_end": locator.pop("line_end"),
            "char_start": locator.pop("char_start"),
            "char_end": locator.pop("char_end"),
            "confluence_local_id": locator.pop("confluence_local_id", None),
            "attributes": locator,
        }

    @staticmethod
    def _artifact_contract_current(destination: Path) -> bool:
        try:
            tree = json.loads((destination / "section-tree.json").read_text(encoding="utf-8"))
            metadata = json.loads((destination / "page.meta.json").read_text(encoding="utf-8"))
            source_bytes = (destination / "page.storage.xhtml").read_bytes()
            markdown_bytes = (destination / "index.md").read_bytes()
        except (OSError, json.JSONDecodeError):
            return False
        if not (
            tree.get("schema_version") == 2
            and tree.get("generator_version") == ConfluenceExporter.artifact_version
            and tree.get("section_id_version") == 1
            and isinstance(tree.get("blocks"), list)
            and isinstance(tree.get("nodes"), list)
        ):
            return False
        space_id = str(tree.get("space_id") or "")
        page_id = str(tree.get("page_id") or "")
        version = str(tree.get("version") or "")
        content_hash = str(tree.get("content_sha256") or "")
        try:
            expected_version_id = stable_document_version_id(
                source_scope="enterprise",
                knowledge_base_id=space_id,
                document_id=page_id,
                version=version,
                content_sha256=content_hash,
            )
        except ValueError:
            return False
        nodes = tree["nodes"]
        return (
            metadata.get("schema_version") == 2
            and metadata.get("exporter_version") == ConfluenceExporter.artifact_version
            and metadata.get("source_content_sha256") == hashlib.sha256(source_bytes).hexdigest()
            and metadata.get("normalized_content_sha256") == hashlib.sha256(markdown_bytes).hexdigest()
            and tree.get("source_content_sha256") == metadata.get("source_content_sha256")
            and tree.get("normalized_content_sha256") == metadata.get("normalized_content_sha256")
            and tree.get("document_version_id") == expected_version_id
            and bool(nodes)
            and all(
                isinstance(node, dict)
                and node.get("version_id") == expected_version_id
                and str(node.get("id") or "").startswith("sec_")
                for node in nodes
            )
            and nodes[0].get("parent_id") is None
        )

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _remove_tracked_artifacts(self, space_root: Path, entry: dict[str, Any]) -> None:
        relative = str(entry.get("relative_path") or "")
        if not relative:
            return
        destination = (space_root / Path(relative)).resolve()
        root = space_root.resolve()
        try:
            destination.relative_to(root)
        except ValueError:
            logger.error("Refusing to clean path outside export root: %s", destination)
            return
        for name in self.artifact_names:
            try:
                (destination / name).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not remove stale artifact %s: %s", destination / name, exc)
        current = destination
        while current != root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def _safe_segment(value: str, max_length: int = 90) -> str:
        if max_length < 1:
            raise ValueError("max_length must be positive")
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
        cleaned = re.sub(r"\s+", " ", cleaned) or "untitled"
        stem = cleaned.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}:
            cleaned = "_" + cleaned
        if len(cleaned) > max_length:
            if max_length >= 12:
                digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
                cleaned = f"{cleaned[:max_length - 10].rstrip()}__{digest}"
            else:
                cleaned = cleaned[:max_length].rstrip(" .") or "_"
        return cleaned

    @classmethod
    def _safe_page_segment(cls, title: str, page_id: str, max_length: int = 90) -> str:
        suffix = f"__{cls._safe_segment(str(page_id), max_length=30)}"
        if max_length <= len(suffix):
            raise ConfluenceResponseError("Path segment budget cannot retain the stable page ID")
        safe_title = cls._safe_segment(title, max_length=max_length - len(suffix))
        return f"{safe_title}{suffix}"

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    @classmethod
    def _atomic_write_json(cls, path: Path, value: dict[str, Any]) -> None:
        cls._atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_confluence_config(env_path: Path | None = None) -> dict[str, str]:
    values = dict(os.environ)
    if env_path and env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    missing = [
        key for key in ("CONFLUENCE_BASE", "CONFLUENCE_EMAIL", "CONFLUENCE_TOKEN")
        if not values.get(key)
    ]
    if missing:
        raise ConfluenceError(f"Missing Confluence configuration: {', '.join(missing)}")
    return {
        "base_url": values["CONFLUENCE_BASE"],
        "email": values["CONFLUENCE_EMAIL"],
        "token": values["CONFLUENCE_TOKEN"],
    }
