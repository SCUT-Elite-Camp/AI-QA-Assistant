import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
# The agent component also has a ``scripts`` package.  Make the repository
# root authoritative for these maintenance-command tests even when pytest has
# already collected Agent/Pipeline tests in the same interpreter.
while str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))
sys.modules.pop("scripts", None)

from scripts.safe_reindex import safe_reindex  # noqa: E402


TARGETS = ("doc_chunks", "document_sections_bgem3")


class FakeUtility:
    def __init__(self, existing=()):
        self.collections = set(existing)
        self.events = []

    def has_collection(self, name):
        return name in self.collections

    def rename_collection(self, old_name, new_name):
        self.events.append(("rename", old_name, new_name))
        self.collections.remove(old_name)
        self.collections.add(new_name)

    def drop_collection(self, name):
        self.events.append(("drop", name))
        self.collections.remove(name)


def test_reindex_backups_are_gitignored():
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".reindex-backups/" in ignore_rules


def make_project(tmp_path):
    raw = tmp_path / "data-persistence" / "data" / "raws"
    documents = tmp_path / "data-persistence" / "data" / "documents"
    raw.mkdir(parents=True)
    documents.mkdir(parents=True)
    (raw / "source.pdf").write_bytes(b"pdf")
    (documents / "doc.json").write_text("old document", encoding="utf-8")
    (tmp_path / "data-persistence" / "data" / "bm25_index.pkl").write_bytes(b"old bm25")
    (tmp_path / "data-persistence" / "data" / "card_links.db").write_bytes(b"old cards")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "reindex.py").write_text("print('legacy')", encoding="utf-8")
    return tmp_path


def test_safe_reindex_defaults_to_dry_run_without_touching_milvus(tmp_path):
    utility = FakeUtility(TARGETS)

    report = safe_reindex(project_root=make_project(tmp_path), utility_api=utility)

    assert report["status"] == "dry-run"
    assert report["raw_files"] == 1
    assert report["collections"] == list(TARGETS)
    assert report["local_backups"] == {
        "documents": True,
        "bm25_index.pkl": True,
    }
    assert utility.events == []


def test_safe_reindex_requires_exact_confirmation(tmp_path):
    utility = FakeUtility(TARGETS)

    report = safe_reindex(
        project_root=make_project(tmp_path),
        execute=True,
        confirmation="yes",
        utility_api=utility,
    )

    assert report["status"] == "error"
    assert "REBUILD" in report["error"]
    assert utility.events == []


def test_safe_reindex_backs_up_and_keeps_old_collections_on_success(tmp_path):
    project = make_project(tmp_path)
    utility = FakeUtility(TARGETS)
    calls = []

    def run(command, cwd):
        calls.append((command, cwd))
        utility.collections.update(TARGETS)
        return SimpleNamespace(returncode=0)

    report = safe_reindex(
        project_root=project,
        execute=True,
        confirmation="REBUILD",
        utility_api=utility,
        subprocess_runner=run,
        timestamp="20260921T120000Z",
    )

    assert report["status"] == "ok"
    backup = Path(report["backup_directory"])
    assert (backup / "documents" / "doc.json").read_text(encoding="utf-8") == "old document"
    assert (backup / "bm25_index.pkl").read_bytes() == b"old bm25"
    assert all(f"{name}__backup_20260921T120000Z" in utility.collections for name in TARGETS)
    assert report["cleanup_after_verification"] == {
        "drop_backup_collections": [
            f"{name}__backup_20260921T120000Z" for name in TARGETS
        ],
        "remove_backup_directory": str(backup),
    }
    assert calls[0][0][1].endswith("scripts\\reindex.py") or calls[0][0][1].endswith("scripts/reindex.py")


def test_safe_reindex_rolls_back_collections_and_local_files_on_failure(tmp_path):
    project = make_project(tmp_path)
    utility = FakeUtility(TARGETS)

    def fail(command, cwd):
        utility.collections.update(TARGETS)
        data = project / "data-persistence" / "data"
        (data / "documents" / "doc.json").write_text("new document", encoding="utf-8")
        (data / "bm25_index.pkl").write_bytes(b"new bm25")
        return SimpleNamespace(returncode=7)

    report = safe_reindex(
        project_root=project,
        execute=True,
        confirmation="REBUILD",
        utility_api=utility,
        subprocess_runner=fail,
        timestamp="20260921T120000Z",
    )

    assert report["status"] == "error"
    assert report["rolled_back"] is True
    assert utility.collections == set(TARGETS)
    data = project / "data-persistence" / "data"
    assert (data / "documents" / "doc.json").read_text(encoding="utf-8") == "old document"
    assert (data / "bm25_index.pkl").read_bytes() == b"old bm25"
    assert (data / "card_links.db").read_bytes() == b"old cards"


def test_safe_reindex_rolls_back_when_rename_applies_then_raises(tmp_path):
    project = make_project(tmp_path)

    class AmbiguousRenameUtility(FakeUtility):
        def rename_collection(self, old_name, new_name):
            super().rename_collection(old_name, new_name)
            if old_name == "document_sections_bgem3":
                raise RuntimeError("connection lost after rename")

    utility = AmbiguousRenameUtility(TARGETS)

    report = safe_reindex(
        project_root=project,
        execute=True,
        confirmation="REBUILD",
        utility_api=utility,
        subprocess_runner=lambda command, cwd: SimpleNamespace(returncode=0),
        timestamp="20260921T120000Z",
    )

    assert report["status"] == "error"
    assert report["rolled_back"] is True
    assert utility.collections == set(TARGETS)


def test_reindex_honors_isolated_runtime_and_child_connection(tmp_path, monkeypatch):
    project = make_project(tmp_path / "project")
    runtime = make_project(tmp_path / "runtime") / "data-persistence" / "data"
    bm25 = tmp_path / "separate-index.pkl"
    bm25.write_bytes(b"isolated index")
    monkeypatch.setenv("AI_QA_DATA_DIR", str(runtime))
    monkeypatch.setenv("BM25_INDEX_PATH", str(bm25))
    monkeypatch.setenv("MILVUS_HOST", "127.0.0.1")
    monkeypatch.setenv("MILVUS_PORT", "19539")
    monkeypatch.setenv("MILVUS_COLLECTION", "isolated_evidence")
    monkeypatch.setenv("SECTION_MILVUS_COLLECTION", "isolated_sections")
    utility = FakeUtility(["isolated_evidence", "isolated_sections"])
    report = safe_reindex(project_root=project, utility_api=utility)
    assert report["data_directory"] == str(runtime.resolve())
    assert report["bm25_index_path"] == str(bm25.resolve())
    assert report["collections"] == ["isolated_evidence", "isolated_sections"]
    assert "19539" in report["command"] and "isolated_evidence" in report["command"]
    assert utility.events == []


def test_rename_failure_before_mutation_keeps_original_collection(tmp_path):
    class RefusedRename(FakeUtility):
        def rename_collection(self, old_name, new_name):
            raise RuntimeError("rename refused")

    utility = RefusedRename(TARGETS)
    report = safe_reindex(
        project_root=make_project(tmp_path), execute=True, confirmation="REBUILD",
        utility_api=utility, timestamp="refused",
    )
    assert report["status"] == "error" and report["rolled_back"] is True
    assert utility.collections == set(TARGETS)
    assert utility.events == []


def test_failure_removes_created_targets_that_had_no_prior_collection(tmp_path):
    utility = FakeUtility()

    def fail(command, cwd):
        utility.collections.update(TARGETS)
        return SimpleNamespace(returncode=7)

    report = safe_reindex(
        project_root=make_project(tmp_path), execute=True, confirmation="REBUILD",
        utility_api=utility, subprocess_runner=fail, timestamp="new-targets",
    )
    assert report["status"] == "error" and report["rolled_back"] is True
    assert utility.collections == set()
