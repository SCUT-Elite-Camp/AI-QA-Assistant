from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from eval.wiki.meeting_record_cohort import freeze_meeting_record_cohort


def _snapshot(tmp_path, page_id: str, parent_id: str, *, space_id: str = "space"):
    page = tmp_path / f"{space_id}-{page_id}"
    page.mkdir()
    metadata_path = page / "page.meta.json"
    metadata_path.write_text(
        json.dumps({"page_id": page_id, "parent_id": parent_id, "title": f"Meeting {page_id}"}),
        encoding="utf-8",
    )
    return SimpleNamespace(
        space_id=space_id, page_id=page_id, version=1,
        identity=(space_id, page_id, 1), metadata_path=metadata_path,
        source_content_sha256=f"{int(page_id):064x}",
        content_sha256=f"{int(page_id) + 1:064x}",
    )


def test_meeting_cohort_uses_parent_closure_not_title(tmp_path) -> None:
    snapshots = [
        _snapshot(tmp_path, "11", "99"),
        _snapshot(tmp_path, "12", "11"),
        _snapshot(tmp_path, "13", "88"),
        _snapshot(tmp_path, "14", "99", space_id="other"),
    ]
    result = freeze_meeting_record_cohort(
        snapshots, space_id="space", parent_page_id="99", expected_pages=2,
    )

    assert [row["identity"][1] for row in result["pages"]] == ["11", "12"]
    assert all(row["category"] == "meeting_record" for row in result["pages"])
    assert result["scope"] == "MEETING_RECORD_ONLY_EXPLORATORY_PILOT"
    with pytest.raises(ValueError, match="expected 3 meeting pages"):
        freeze_meeting_record_cohort(
            snapshots, space_id="space", parent_page_id="99", expected_pages=3,
        )


def test_meeting_cohort_rejects_parent_cycle_and_duplicate_versions(tmp_path) -> None:
    cyclic = [_snapshot(tmp_path, "21", "22"), _snapshot(tmp_path, "22", "21")]
    with pytest.raises(ValueError, match="parent cycle"):
        freeze_meeting_record_cohort(cyclic, space_id="space", parent_page_id="99")

    first = _snapshot(tmp_path, "31", "99")
    second = SimpleNamespace(**{**vars(first), "version": 2, "identity": ("space", "31", 2)})
    with pytest.raises(ValueError, match="multiple versions"):
        freeze_meeting_record_cohort([first, second], space_id="space", parent_page_id="99")
