"""Filesystem repository for topic metadata and cognition artifacts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from data_persistence._paths import topics_dir


class TopicArtifactRepository:
    """Load and save topic artifacts under one validated topics directory."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else topics_dir()

    def _topic_dir(self, topic_id: str) -> Path:
        """Resolve a topic ID to one safe directory directly under the root."""
        if (
            not isinstance(topic_id, str)
            or not topic_id
            or topic_id in {".", ".."}
            or any(char in topic_id for char in ("/", "\\", "\x00", ":"))
        ):
            raise ValueError("topic_id must be a non-empty single path component")

        topics_root = self.base_dir.resolve()
        candidate = topics_root / topic_id
        if candidate.is_symlink():
            raise ValueError("topic_id cannot refer to a symbolic link")
        resolved = candidate.resolve()
        if resolved.parent != topics_root:
            raise ValueError("topic_id must resolve directly under the topics directory")
        return resolved

    def load_existing(
        self,
        topic_id: str,
        supplied_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return supplied topic state or read existing metadata and soul text."""
        topic_dir = self._topic_dir(topic_id)
        if supplied_info:
            return supplied_info

        existing_info: dict[str, Any] = {}
        info_file = topic_dir / "topic_info.json"
        soul_file = topic_dir / "soul.md"
        if info_file.exists():
            try:
                with info_file.open("r", encoding="utf-8") as file:
                    loaded_info = json.load(file)
                if isinstance(loaded_info, dict):
                    existing_info = loaded_info
            except Exception:
                pass
        if soul_file.exists() and "soulContent" not in existing_info:
            try:
                with soul_file.open("r", encoding="utf-8") as file:
                    existing_info["soulContent"] = file.read()
            except Exception:
                pass
        return existing_info

    def save_summary(
        self,
        topic_id: str,
        *,
        title: str,
        description: str,
        soul_content: str,
        tags: list[str],
        existing_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist generated topic artifacts using the existing disk schema."""
        topic_dir = self._topic_dir(topic_id)
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "documents").mkdir(parents=True, exist_ok=True)

        with (topic_dir / "soul.md").open("w", encoding="utf-8") as file:
            file.write(soul_content)

        info_data = {
            "id": topic_id,
            "title": title,
            "description": description,
            "soulContent": soul_content,
            "tags": tags,
            "weightMode": existing_info.get("weightMode", "auto"),
            "consecutiveNoNewDocsCount": existing_info.get("consecutiveNoNewDocsCount", 0),
            "last_synced_at": datetime.now().isoformat(),
        }
        with (topic_dir / "topic_info.json").open("w", encoding="utf-8") as file:
            json.dump(info_data, file, ensure_ascii=False, indent=2)
        return info_data
