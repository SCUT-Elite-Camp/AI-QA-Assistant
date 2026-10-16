"""Canonical source-independent document preparation."""
from models.document import Chunk, Document
from pipeline.documents.chunker import chunk_from_blocks, chunk_text
from pipeline.documents.structure import build_document_sections
from pipeline.documents.budget import count_tokens, split_budget, token_limit, tokenizer


def prepare_ingestion_chunks(
    document: Document, *, chunk_size: int = 2000, overlap: int = 100,
) -> list[Chunk]:
    if document.content_blocks:
        chunks = chunk_from_blocks(
            document.content_blocks, document.doc_id, chunk_size=chunk_size,
            overlap=overlap, document_title=document.title,
        )
    else:
        chunks = chunk_text(document.content, document.doc_id, chunk_size=chunk_size, overlap=overlap)
    bounded = []
    for chunk in chunks:
        parts = [chunk.text] if chunk.chunk_type == 'table' else split_budget(chunk.text)
        for part in parts:
            index = len(bounded)
            item = chunk.model_copy(deep=True)
            item.index, item.chunk_id = index, f'{document.doc_id}_chunk_{index}'
            if len(parts) > 1:
                from pipeline.documents.chunker import _index_text_from_markdown
                item.text = item.markdown_text = part
                item.index_text = _index_text_from_markdown(part)
                item.overlap_prefix_length = 0
            # The source text stays unmodified; headings are retrieval context.
            context = ' > '.join([document.title, *item.section_path])
            if context.strip():
                item.index_text = split_budget(context, 32)[0] + '\n' + item.index_text
            item.metadata.update({'chunking_version': 'semantic-v2', 'parent_section_path': list(item.section_path),
                                  'token_count': count_tokens(item.text),
                                  'tokenizer': 'embedding_tokenizer' if tokenizer() else 'conservative_characters',
                                  'retrieval_context': context})
            bounded.append(item)
    for index, item in enumerate(bounded):
        if index and bounded[index-1].section_path == item.section_path:
            item.metadata['previous_chunk_id'] = bounded[index-1].chunk_id
        if index+1 < len(bounded) and bounded[index+1].section_path == item.section_path:
            item.metadata['next_chunk_id'] = bounded[index+1].chunk_id
    return bounded


def prepare_document(document: Document, *, chunk_size: int = 2000, overlap: int = 100) -> Document:
    """The same document processing for every source; destinations own isolation."""
    document.chunks = prepare_ingestion_chunks(document, chunk_size=chunk_size, overlap=overlap)
    document.sections = build_document_sections(document)
    return document
