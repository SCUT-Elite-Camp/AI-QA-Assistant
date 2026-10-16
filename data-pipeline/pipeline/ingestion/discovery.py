"""Select file inputs and detect changes without processing documents."""
import os
import json
from pathlib import Path
from models.document import Document
from parsers.registry import supported_extensions
from pipeline.confluence.snapshot import deduplicate_confluence_paths


def scan_folder(folder_path: str) -> list[str]:
    """递归扫描文件夹，返回所有支持的文件绝对路径"""
    files: list[str] = []
    exts = supported_extensions()
    for root, _dirs, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in exts:
                files.append(os.path.abspath(os.path.join(root, fname)))
    return deduplicate_confluence_paths(files)

def get_new_or_modified_files(raw_files: list[str], documents_dir: Path) -> list[str]:
    """根据已经保存的文档 JSON 和文件修改时间，筛选出新增或修改的文件"""
    to_process = []
    for file_path in raw_files:
        abs_path = os.path.abspath(file_path)
        metadata = raw_source_metadata(abs_path)
        doc_id = Document.generate_source_doc_id(abs_path, metadata)
        json_path = documents_dir / f"{doc_id}.json"

        # 1. 如果对应的 JSON 文件不存在，说明是全新增文件
        if not json_path.exists():
            to_process.append(file_path)
            continue

        # 2. 如果 JSON 文件存在，比对修改时间 last_updated
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                doc_data = json.load(f)
            stored_last_updated = doc_data.get("last_updated")
            current_last_updated = metadata.get("last_updated") or Document.generate_last_updated(abs_path)
            stored_metadata = doc_data.get("metadata") or {}
            source_changed = any(
                str(metadata.get(key) or "") != str(stored_metadata.get(key) or "")
                for key in ("version", "source_content_sha256", "normalized_content_sha256", "file_sha256")
            )

            # 如果修改时间不一致，说明文件被更新了
            if (doc_data.get("active_version", True) is not True
                    or stored_last_updated != current_last_updated or source_changed
                    or stored_metadata.get("sync_status") in {"updating", "export_ready", "partial"}):
                to_process.append(file_path)
        except Exception:
            # 如果读取 JSON 失败，当作新文件重新处理以保证数据完整性
            to_process.append(file_path)

    return to_process


def raw_source_metadata(file_path: str) -> dict:
    path = Path(file_path)
    candidates = [Path(str(path) + ".meta.json")]
    if path.name == "index.md":
        candidates.insert(0, path.with_name("page.meta.json"))
    for candidate in candidates:
        if candidate.is_file():
            value = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"invalid source metadata: {candidate}")
            return value
    return {}
