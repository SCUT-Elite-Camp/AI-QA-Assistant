"""Select all supported files in a folder for shared ingestion."""
from pathlib import Path
from pipeline.ingestion.discovery import scan_folder
from pipeline.ingestion.batch import run_batch


def process_folder(folder_path: str, chunk_size: int = 2000, overlap: int = 100,
                   milvus_host: str = "localhost", milvus_port: str = "19530"):
    folder = Path(folder_path).resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Folder does not exist: {folder}")
    return run_batch(scan_folder(str(folder)), chunk_size=chunk_size, overlap=overlap,
                     milvus_host=milvus_host, milvus_port=milvus_port, require_vectors=True)


if __name__ == "__main__":
    from pipeline.entrypoints.arguments import batch_parser
    parser = batch_parser("Ingest all supported files in a folder")
    parser.add_argument("folder_path")
    process_folder(**vars(parser.parse_args()))
