"""Select explicit file paths for shared ingestion."""
from pipeline.ingestion.batch import run_batch
from pipeline.confluence.snapshot import deduplicate_confluence_paths


def process_specific_files(file_paths: list[str], chunk_size: int = 2000, overlap: int = 100,
                           milvus_host: str = "localhost", milvus_port: str = "19530"):
    return run_batch(deduplicate_confluence_paths(file_paths), chunk_size=chunk_size,
                     overlap=overlap, milvus_host=milvus_host, milvus_port=milvus_port)


if __name__ == "__main__":
    from pipeline.entrypoints.arguments import batch_parser
    parser = batch_parser("Ingest explicit file paths")
    parser.add_argument("file_paths", nargs="+")
    process_specific_files(**vars(parser.parse_args()))
