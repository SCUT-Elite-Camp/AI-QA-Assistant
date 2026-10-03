"""Bounded Wiki folder planning with stable paths and manual-placement preservation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .domain import WikiFolder, WikiIdentity, WikiPlacement, stable_id
from .extraction import JsonCompletionClient


TAXONOMY_PROMPT_VERSION = "wiki-taxonomy-planning-v2"

_TAXONOMY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "placements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "identity_id": {"type": "string"},
                    "path": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "items": {"type": "string"},
                    },
                },
                "required": ["identity_id", "path"],
            },
        }
    },
    "required": ["placements"],
}


class TaxonomyPlanner:
    def __init__(self, client: JsonCompletionClient, *, max_batch_items: int = 40) -> None:
        if max_batch_items < 1:
            raise ValueError("taxonomy batch size must be positive")
        self.client = client
        self.max_batch_items = max_batch_items

    def plan(
        self,
        identities: Iterable[WikiIdentity],
        *,
        existing_folders: Iterable[WikiFolder] = (),
        existing_placements: Iterable[WikiPlacement] = (),
    ) -> tuple[list[WikiFolder], list[WikiPlacement]]:
        values = list(identities)
        if not values:
            return list(existing_folders), list(existing_placements)
        scope = values[0].scope
        if any(item.scope != scope for item in values):
            raise ValueError("taxonomy planning cannot cross Wiki scopes")
        folders = {item.id: item for item in existing_folders}
        placements = {item.identity_id: item for item in existing_placements}
        if any(item.scope != scope for item in folders.values()):
            raise ValueError("existing taxonomy folder belongs to another scope")
        unknown = set(placements) - {item.id for item in values}
        if unknown:
            raise ValueError("taxonomy placement references unknown identity")

        pending = [item for item in values if item.id not in placements]
        for start in range(0, len(pending), self.max_batch_items):
            batch = pending[start:start + self.max_batch_items]
            raw = self.client.complete(
                system=(
                    "Place each knowledge identity into one reusable Wiki folder path of one or two levels. "
                    "Prefer existing folders, broad stable topics, and consistent sibling granularity. "
                    "Do not create folders for dates, statuses, individual source documents, or transient tasks. "
                    "Return every supplied identity exactly once."
                ),
                user={
                    "identities": [{
                        "identity_id": item.id,
                        "kind": item.kind.value,
                        "name": item.canonical_name,
                        "category": item.category.value if item.category else None,
                        "description": item.description,
                    } for item in batch],
                    "existing_folders": [
                        {"folder_id": item.id, "title": item.title, "parent_id": item.parent_id}
                        for item in folders.values()
                    ],
                },
                schema_name="wiki_taxonomy_planning",
                schema=_TAXONOMY_SCHEMA,
                max_tokens=2200,
            )
            planned = _validate_plan(raw, {item.id for item in batch})
            for identity_id, path in planned.items():
                parent_id: str | None = None
                accumulated: list[str] = []
                for depth, title in enumerate(path):
                    accumulated.append(title)
                    folder_id = stable_id(
                        "wf",
                        scope.source_scope,
                        scope.owner_id,
                        scope.knowledge_base_id,
                        *accumulated,
                    )
                    folders.setdefault(folder_id, WikiFolder(
                        id=folder_id,
                        scope=scope,
                        title=title,
                        parent_id=parent_id,
                        depth=depth,
                    ))
                    parent_id = folder_id
                placements[identity_id] = WikiPlacement(
                    identity_id=identity_id,
                    folder_id=parent_id or "",
                )
        ordered_placements = [placements[item.id] for item in values]
        folders = _prune_empty_folders(folders, ordered_placements)
        return sorted(folders.values(), key=lambda item: (item.depth, item.title.casefold(), item.id)), ordered_placements


def _validate_plan(raw: dict[str, Any], expected: set[str]) -> dict[str, list[str]]:
    values = raw.get("placements") if isinstance(raw, dict) and set(raw) == {"placements"} else None
    if not isinstance(values, list):
        raise ValueError("taxonomy response has an invalid shape")
    result: dict[str, list[str]] = {}
    for value in values:
        if not isinstance(value, dict) or set(value) != {"identity_id", "path"}:
            raise ValueError("taxonomy placement has an invalid shape")
        identity_id = str(value["identity_id"])
        path = value["path"]
        if identity_id not in expected or identity_id in result:
            raise ValueError("taxonomy response has unknown or duplicate identities")
        if not isinstance(path, list) or not 1 <= len(path) <= 2:
            raise ValueError("taxonomy path must contain one or two levels")
        clean = [" ".join(str(title).split()) for title in path]
        if any(not title or len(title) > 80 for title in clean):
            raise ValueError("taxonomy folder title is invalid")
        result[identity_id] = clean
    if set(result) != expected:
        raise ValueError("taxonomy response omitted identities")
    return result


def _prune_empty_folders(
    folders: dict[str, WikiFolder], placements: list[WikiPlacement],
) -> dict[str, WikiFolder]:
    retained = {item.folder_id for item in placements}
    pending = list(retained)
    while pending:
        folder = folders.get(pending.pop())
        if folder is not None and folder.parent_id and folder.parent_id not in retained:
            retained.add(folder.parent_id)
            pending.append(folder.parent_id)
    return {folder_id: folder for folder_id, folder in folders.items() if folder_id in retained}
