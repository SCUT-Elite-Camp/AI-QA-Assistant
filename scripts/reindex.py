"""Rebuild configured Evidence/Section indexes during a maintenance window.

Use safe_reindex.py for backups and rollback. Importing this module has no side effects.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True, choices=["REBUILD"])
    parser.add_argument("--host", default=os.getenv("MILVUS_HOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("MILVUS_PORT", "19530"))
    parser.add_argument("--evidence-collection", default=os.getenv("MILVUS_COLLECTION", "doc_chunks"))
    parser.add_argument("--section-collection", default=os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3"))
    args = parser.parse_args(argv)
    if args.evidence_collection.casefold() == args.section_collection.casefold():
        parser.error("Evidence and Section collections must differ")

    for directory in (PROJECT_ROOT, PROJECT_ROOT / "data-pipeline",
                      PROJECT_ROOT / "data-persistence", PROJECT_ROOT / "toolset"):
        sys.path.insert(0, str(directory))
    os.environ["MILVUS_COLLECTION"] = args.evidence_collection
    os.environ["SECTION_MILVUS_COLLECTION"] = args.section_collection

    from pipeline.auto_process import RAWS_DIR, _scan_folder, auto_process_raws
    from pymilvus import connections, utility

    if not _scan_folder(str(RAWS_DIR)):
        parser.error("No supported source files; refusing an empty rebuild")
    connections.connect(host=args.host, port=args.port)
    for name in (args.evidence_collection, args.section_collection):
        if utility.has_collection(name):
            utility.drop_collection(name)
    auto_process_raws(milvus_host=args.host, milvus_port=args.port, force=True, strict=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
