"""Attach bounded original neighbors, keeping their own identities and hashes."""
import os


def identity(row):
    return (row.get('doc_id') or row.get('attachment_id'),
            row.get('version_id'), row.get('chunk_id') or row.get('evidence_id'))


def attach_context(rows, lookup):
    if os.getenv('RETRIEVAL_CONTEXT_ENABLED', 'true').lower() not in {'true', 'yes', '1'}:
        return rows
    seen = {identity(row) for row in rows}
    remaining = 4000
    result = []
    for row in rows:
        contexts = []
        locator = row.get('locator') or {}
        for key in ('previous_chunk_id', 'next_chunk_id'):
            neighbor_id = locator.get(key)
            if not neighbor_id:
                continue
            neighbor = lookup(row, neighbor_id)
            if not neighbor or identity(neighbor) in seen:
                continue
            if identity(neighbor)[:2] != identity(row)[:2]:
                continue
            if neighbor.get('read_status') != 'original_excerpt_loaded':
                continue
            if (neighbor.get('locator') or {}).get('section_path') != locator.get('section_path'):
                continue
            text = str(neighbor.get('chunk_text') or neighbor.get('content') or '')
            if not text.strip() or len(text) > min(2000, remaining):
                continue
            neighbor = {**neighbor, 'score': row.get('score', 0), 'context_of': identity(row)[2]}
            contexts.append(neighbor)
            seen.add(identity(neighbor))
            remaining -= len(text)
        result.append({**row, 'context_chunks': contexts} if contexts else row)
    return result
