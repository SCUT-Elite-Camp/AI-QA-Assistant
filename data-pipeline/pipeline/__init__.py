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
from .knowledge_graph import (
    CompiledKnowledgeGraph,
    KnowledgeAssertion,
    KnowledgeExtractionProvider,
    compile_knowledge_graph,
)
from .knowledge_extractor import LocalOpenAIKnowledgeExtractionProvider
from .knowledge_graph_job import build_and_activate_knowledge_graph

__all__ = [
    "chunk_text",
    "embed_texts",
    "CompiledKnowledgeGraph",
    "KnowledgeAssertion",
    "KnowledgeExtractionProvider",
    "compile_knowledge_graph",
    "LocalOpenAIKnowledgeExtractionProvider",
    "build_and_activate_knowledge_graph",
]
