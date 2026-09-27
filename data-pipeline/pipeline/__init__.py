"""Public pipeline helpers, imported lazily to keep lightweight tools isolated."""

from typing import Any

__all__ = ["chunk_text", "embed_texts"]


def chunk_text(*args: Any, **kwargs: Any):
    from pipeline.chunker import chunk_text as implementation

    return implementation(*args, **kwargs)


def embed_texts(*args: Any, **kwargs: Any):
    from pipeline.embedder import embed_texts as implementation

    return implementation(*args, **kwargs)


# process_folder remains available from pipeline.process.
