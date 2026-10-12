"""Dry-run by default wrapper for rollback-capable Milvus reindexing."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_COLLECTIONS = ("doc_chunks", "document_sections_bgem3")
SUPPORTED_SOURCE_SUFFIXES = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".html", ".htm", ".md"}


def _data_root(project_root: Path) -> Path:
    return Path(os.getenv("AI_QA_DATA_DIR", str(project_root / "data-persistence" / "data"))).resolve()


def _bm25_path(project_root: Path) -> Path:
    return Path(os.getenv("BM25_INDEX_PATH", str(_data_root(project_root) / "bm25_index.pkl"))).resolve()


def _source_files(project_root: Path) -> list[Path]:
    raw_directory = _data_root(project_root) / "raws"
    if not raw_directory.exists():
        return []
    return sorted(
        (
            path
            for path in raw_directory.rglob("*")
            if path.is_file() and path.suffix.casefold() in SUPPORTED_SOURCE_SUFFIXES
        ),
        key=lambda path: path.as_posix().casefold(),
    )


def _local_targets(project_root: Path) -> dict[str, Path]:
    data = _data_root(project_root)
    return {
        "documents": data / "documents",
        "bm25_index.pkl": _bm25_path(project_root),
    }


def _assert_safe_local_target(project_root: Path, target: Path) -> None:
    """Refuse destructive cleanup if a target resolves outside the data directory."""
    data_root = _data_root(project_root)
    if target == _bm25_path(project_root):
        if target.is_symlink():
            raise RuntimeError("refusing to modify a symlinked BM25 index")
        return
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(data_root)
    except ValueError as error:
        raise RuntimeError(
            f"refusing to modify local path outside {data_root}: {resolved_target}"
        ) from error


def _backup_local_files(project_root: Path, backup_directory: Path) -> dict[str, bool]:
    backup_directory.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, bool] = {}
    for name, source in _local_targets(project_root).items():
        _assert_safe_local_target(project_root, source)
        exists = source.exists()
        manifest[name] = exists
        if not exists:
            continue
        destination = backup_directory / name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    (backup_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _restore_local_files(
    project_root: Path,
    backup_directory: Path,
    manifest: dict[str, bool],
) -> None:
    for name, destination in _local_targets(project_root).items():
        backup = backup_directory / name
        if destination.exists():
            _assert_safe_local_target(project_root, destination)
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if not manifest[name]:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_dir():
            shutil.copytree(backup, destination)
        else:
            shutil.copy2(backup, destination)


def safe_reindex(
    *,
    project_root: Path | str = PROJECT_ROOT,
    execute: bool = False,
    confirmation: str = "",
    host: str | None = None,
    port: str | None = None,
    utility_api=None,
    subprocess_runner=None,
    timestamp: str | None = None,
    collections: tuple[str, str] | None = None,
) -> dict:
    """Plan or execute a reindex with local backups and collection rollback."""
    root = Path(project_root).resolve()
    host = host or os.getenv("MILVUS_HOST", "localhost")
    port = port or os.getenv("MILVUS_PORT", "19530")
    targets = collections or (
        os.getenv("MILVUS_COLLECTION", TARGET_COLLECTIONS[0]),
        os.getenv("SECTION_MILVUS_COLLECTION", TARGET_COLLECTIONS[1]),
    )
    if len(targets) != 2 or any(not name for name in targets) or targets[0].casefold() == targets[1].casefold():
        raise ValueError("Evidence and Section collections must be nonempty and distinct")
    sources = _source_files(root)
    local_backups = {
        name: path.exists() for name, path in _local_targets(root).items()
    }
    command = [sys.executable, str(root / "scripts" / "reindex.py"),
        "--confirm", "REBUILD", "--host", host, "--port", str(port),
        "--evidence-collection", targets[0], "--section-collection", targets[1]]
    preflight = {
        "status": "dry-run",
        "raw_files": len(sources),
        "data_directory": str(_data_root(root)),
        "bm25_index_path": str(_bm25_path(root)),
        "milvus_host": host,
        "milvus_port": str(port),
        "collections": list(targets),
        "local_backups": local_backups,
        "command": command,
    }
    if not execute:
        return preflight
    if confirmation != "REBUILD":
        return {
            **preflight,
            "status": "error",
            "error": "execution requires --confirm REBUILD",
        }
    if not sources:
        return {
            **preflight,
            "status": "error",
            "error": "no supported source files found; refusing destructive rebuild",
        }

    if utility_api is None:
        from pymilvus import connections, utility

        try:
            connections.connect(host=host, port=port)
        except Exception as error:
            return {
                **preflight,
                "status": "error",
                "error": f"Milvus connection failed: {error}",
            }
        utility_api = utility

    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_directory = root / ".reindex-backups" / stamp
    backup_names = {
        name: f"{name}__backup_{stamp}"
        for name in targets
        if utility_api.has_collection(name)
    }
    conflicts = [name for name in backup_names.values() if utility_api.has_collection(name)]
    if conflicts:
        return {
            **preflight,
            "status": "error",
            "error": f"backup collections already exist: {', '.join(conflicts)}",
        }

    manifest: dict[str, bool] = {}
    renamed: list[tuple[str, str]] = []
    runner_started = False
    rollback_errors: list[str] = []
    try:
        manifest = _backup_local_files(root, backup_directory)
        for original, backup in backup_names.items():
            renamed.append((original, backup))
            utility_api.rename_collection(original, backup)

        runner = subprocess_runner or subprocess.run
        runner_started = True
        result = runner(command, cwd=str(root))
        if int(getattr(result, "returncode", 1)) != 0:
            raise RuntimeError(f"reindex exited {result.returncode}")
    except Exception as error:
        for original, backup in reversed(renamed):
            try:
                if utility_api.has_collection(backup):
                    if utility_api.has_collection(original):
                        utility_api.drop_collection(original)
                    utility_api.rename_collection(backup, original)
            except Exception as rollback_error:
                rollback_errors.append(f"{original}: {rollback_error}")
        if runner_started:
            for target in targets:
                if target not in backup_names and utility_api.has_collection(target):
                    try:
                        utility_api.drop_collection(target)
                    except Exception as rollback_error:
                        rollback_errors.append(f"{target}: {rollback_error}")
        if manifest:
            try:
                _restore_local_files(root, backup_directory, manifest)
            except Exception as rollback_error:
                rollback_errors.append(f"local files: {rollback_error}")
        return {
            **preflight,
            "status": "error",
            "error": str(error),
            "backup_directory": str(backup_directory),
            "rolled_back": not rollback_errors,
            "rollback_errors": rollback_errors,
        }

    return {
        **preflight,
        "status": "ok",
        "backup_directory": str(backup_directory),
        "backup_collections": backup_names,
        "cleanup_after_verification": {
            "drop_backup_collections": list(backup_names.values()),
            "remove_backup_directory": str(backup_directory),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--host", default=os.getenv("MILVUS_HOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("MILVUS_PORT", "19530"))
    args = parser.parse_args(argv)

    report = safe_reindex(
        execute=args.execute,
        confirmation=args.confirm,
        host=args.host,
        port=args.port,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry-run", "ok"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
