"""Source-native read authorization; a local grant never widens source ACLs.

The deployment supplies verified local-user -> Atlassian account bindings.
This module does not guess identities from email, cache positive decisions, or
silently fall back to snapshot permissions when an upstream check fails.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values


class SourceAccessError(RuntimeError):
    def __init__(self, code: str, status_code: int = 503) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class SourceAccessProvider:
    """Filter an already locally authorized catalogue using current source ACLs."""

    def __init__(
        self,
        documents_dir: str | Path | None = None,
        *,
        mode: str | None = None,
        account_bindings: dict[str, Any] | None = None,
        base_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
        transport: Any = None,
        document_loader: Callable[[str], dict | None] | None = None,
        document_ids_loader: Callable[[], list[str]] | None = None,
    ) -> None:
        from agent.config.settings import settings

        self.documents_dir = Path(documents_dir or settings.RESEARCH_DOCUMENTS_DIR).resolve()
        self.mode = mode or os.getenv("SOURCE_ACCESS_MODE", "native")
        if self.mode not in {"native", "approved_snapshot"}:
            raise SourceAccessError("source_access_mode_invalid")
        # The exporter credential file is a local secret, never an output or an
        # automatic grant to application users. Explicit env values take priority.
        credentials: dict[str, Any] = {}
        configured_file = os.getenv("CONFLUENCE_AUTH_ENV_FILE")
        if configured_file:
            credential_path = Path(configured_file)
            if not credential_path.is_file():
                raise SourceAccessError("source_credentials_unavailable")
            credentials = dict(dotenv_values(credential_path))
        try:
            self.account_bindings = account_bindings if account_bindings is not None else json.loads(
                os.getenv("CONFLUENCE_ACCOUNT_BINDINGS") or credentials.get("CONFLUENCE_ACCOUNT_BINDINGS") or "{}"
            )
            if not isinstance(self.account_bindings, dict):
                raise ValueError("bindings must be an object")
        except (ValueError, TypeError) as exc:
            raise SourceAccessError("source_identity_configuration_invalid") from exc
        self.base_url = base_url or os.getenv("CONFLUENCE_BASE") or credentials.get("CONFLUENCE_BASE") or ""
        self.email = email or os.getenv("CONFLUENCE_EMAIL") or credentials.get("CONFLUENCE_EMAIL") or ""
        self.token = token or os.getenv("CONFLUENCE_TOKEN") or credentials.get("CONFLUENCE_TOKEN") or ""
        self.transport = transport or requests.Session()
        self.document_loader = document_loader
        self.document_ids_loader = document_ids_loader

    def list_document_ids(self) -> list[str]:
        if self.document_ids_loader is not None:
            return self.document_ids_loader()
        from toolset.tool_layer.document_tools import DocumentRepository

        return [str(item["doc_id"]) for item in DocumentRepository(self.documents_dir).list() if item.get("doc_id")]

    def _load(self, doc_id: str) -> dict | None:
        if self.document_loader is not None:
            return self.document_loader(doc_id)
        from toolset.tool_layer.document_tools import DocumentRepository

        try:
            return DocumentRepository(self.documents_dir).load(doc_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SourceAccessError("source_catalog_unavailable") from exc

    @staticmethod
    def _active(document: dict) -> bool:
        metadata = document.get("metadata") or {}
        if not isinstance(metadata, dict):
            return False
        for value in (document.get("active"), metadata.get("active"), document.get("is_active"), metadata.get("is_active")):
            if value is False or value == "false":
                return False
        status = document.get("sync_status") or metadata.get("sync_status")
        return status not in {"not_visible", "quarantined", "deleted", "deleted_confirmed", "updating", "partial"}

    def filter_allowed(self, user_id: str, doc_ids: list[str]) -> list[str]:
        if not user_id:
            raise SourceAccessError("source_identity_required", 401)
        candidates = list(dict.fromkeys(doc_ids))
        def check(doc_id: str) -> bool:
            document = self._load(doc_id)
            if document is None or str(document.get("doc_id")) != doc_id or not self._active(document):
                return False
            if self.mode == "approved_snapshot":
                return True
            metadata = document.get("metadata") or {}
            source_url = str(document.get("source_url") or metadata.get("source_url") or document.get("address") or "")
            parsed = urlparse(source_url)
            source_type = str(metadata.get("source_type") or document.get("source_type") or "").lower()
            is_confluence = "confluence" in source_type or bool(parsed.hostname and parsed.hostname.endswith(".atlassian.net"))
            if not is_confluence:
                # Locally managed documents still require the upstream local ACL;
                # personal-library and attachment services enforce their own scope.
                return True
            return self._check_confluence(user_id, document, parsed)
        # Independent reads within this one boundary may run concurrently. No
        # positive result survives the boundary or substitutes for a later read.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(candidates)))) as pool:
            decisions = list(pool.map(check, candidates))
        return [doc_id for doc_id, granted in zip(candidates, decisions) if granted]

    def _check_confluence(self, user_id: str, document: dict, parsed: Any) -> bool:
        binding = self.account_bindings.get(user_id)
        if not binding:
            return False
        configured = urlparse(str(self.base_url))
        try:
            configured_port = configured.port or 443
            source_port = parsed.port or 443
        except ValueError as exc:
            raise SourceAccessError("source_origin_invalid") from exc
        if configured.scheme != "https" or not configured.hostname or configured.username or configured.password:
            raise SourceAccessError("source_credentials_unavailable")
        if (parsed.scheme != "https" or parsed.hostname != configured.hostname
                or source_port != configured_port or parsed.username or parsed.password):
            return False
        if not self.email or not self.token:
            raise SourceAccessError("source_credentials_unavailable")
        # Optional per-site binding prevents accidental reuse across tenants.
        if isinstance(binding, dict):
            if binding.get("site") != configured.hostname:
                return False
            account_id = binding.get("account_id")
        else:
            account_id = binding
        if not isinstance(account_id, str) or not account_id.strip():
            return False
        metadata = document.get("metadata") or {}
        page_id = metadata.get("page_id") or metadata.get("confluence_page_id") or document.get("page_id")
        if not page_id:
            match = re.search(r"/(?:pages|attachments)/(\d+)(?:/|$)", parsed.path)
            page_id = match.group(1) if match else None
        if not page_id or not str(page_id).isdigit():
            return False
        origin = f"https://{configured.netloc}"
        endpoint = f"{origin}/wiki/rest/api/content/{page_id}/permission/check"
        try:
            for attempt in range(2):
                try:
                    response = self.transport.post(
                        endpoint,
                        auth=(self.email, self.token),
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        json={"subject": {"type": "user", "identifier": account_id}, "operation": "read"},
                        timeout=(5, 15),
                        allow_redirects=False,
                    )
                except (requests.ConnectionError, requests.Timeout):
                    if attempt:
                        raise
                    time.sleep(0.25)
                    continue
                if response.status_code in {502, 503, 504} and not attempt:
                    time.sleep(0.25)
                    continue
                break
            if response.status_code == 404:
                return False
            if response.status_code != 200:
                # 401/403 may mean the connector cannot inspect another user,
                # not that that user has no access. Never treat it as success.
                raise SourceAccessError("source_permission_check_unavailable")
            payload = response.json()
            if not isinstance(payload, dict) or type(payload.get("hasPermission")) is not bool:
                raise SourceAccessError("source_permission_response_invalid")
            return payload["hasPermission"]
        except SourceAccessError:
            raise
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise SourceAccessError("source_permission_check_unavailable") from exc
