"""Stable locator helpers shared by Chat and Local Deep Research."""

from __future__ import annotations

import re
from typing import Any


_CHUNK_SUFFIX = re.compile(r"(?:^|::|_)chunk(?::|_|-)(\d+)$", re.IGNORECASE)


def canonical_chunk_id(
    doc_id: str,
    chunk_id: Any = None,
    chunk_index: Any = None,
) -> str:
    """Return the Agent contract form ``{doc_id}_chunk_{index}``.

    Tool Layer historically emitted ``{doc_id}::chunk_{index}``, while the
    frozen documents and evaluation manifests use one underscore.  Line
    locators are a different locator type and are deliberately preserved.
    Unknown non-empty locators are also preserved instead of being guessed.
    """

    document_id = str(doc_id).strip()
    raw = str(chunk_id or "").strip()
    if raw.startswith("line:"):
        return raw

    match = _CHUNK_SUFFIX.search(raw)
    if match and document_id:
        return f"{document_id}_chunk_{int(match.group(1))}"

    if not raw and document_id and chunk_index is not None:
        try:
            return f"{document_id}_chunk_{int(chunk_index)}"
        except (TypeError, ValueError):
            pass
    return raw


__all__ = ["canonical_chunk_id"]
