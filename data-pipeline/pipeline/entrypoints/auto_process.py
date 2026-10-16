"""Select changed raw files and confirmed Confluence retractions for shared ingestion."""
import os
from pathlib import Path
from models.document import Document
from data_persistence._paths import data_dir
from data_persistence.documents import resolve_documents_dir
from pipeline.ingestion.batch import run_batch
from pipeline.ingestion.discovery import scan_folder, get_new_or_modified_files, raw_source_metadata
from pipeline.confluence.lifecycle import pending_confluence_retractions, withdrawn_confluence_documents


def auto_process_raws(
    milvus_host: str = "localhost", milvus_port: str = "19530",
    chunk_size: int = 2000, overlap: int = 100, force: bool = False, strict: bool = False,
    *, raws_dir: Path | None = None, documents_dir: Path | None = None,
) -> None:
    raws = Path(raws_dir) if raws_dir is not None else data_dir() / "raws"
    documents = Path(documents_dir) if documents_dir is not None else resolve_documents_dir()
    raws.mkdir(parents=True, exist_ok=True)
    documents.mkdir(parents=True, exist_ok=True)
    retractions = pending_confluence_retractions(documents, raws / "confluence")
    withdrawn_ids = {item.document_id for item in withdrawn_confluence_documents(documents, raws / "confluence")}
    files = [path for path in scan_folder(str(raws))
             if Document.generate_source_doc_id(os.path.abspath(path), raw_source_metadata(path)) not in withdrawn_ids]
    if not files and not retractions:
        if strict:
            raise RuntimeError("No active sources available for strict reindex")
        return
    selected = files if force else get_new_or_modified_files(files, documents)
    run_batch(selected, chunk_size=chunk_size, overlap=overlap, milvus_host=milvus_host,
              milvus_port=milvus_port, strict=strict, documents_dir=documents, retractions=retractions)


if __name__ == "__main__":
    from pipeline.entrypoints.arguments import batch_parser
    parser = batch_parser("Incrementally ingest changed raw files")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    auto_process_raws(**vars(args))
