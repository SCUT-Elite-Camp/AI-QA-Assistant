"""Use the same ranker for a mixed-source evidence pool without changing lineage."""
from .reranker import candidate_count, enabled, rerank


def rank_evidence(query, evidence, top_k=5):
    if not enabled():
        return evidence
    groups = {}
    for item in evidence:
        groups.setdefault(item.source_type, []).append(item)
    candidates = []
    # Keep each scoped source represented in the candidate pool, regardless of
    # incomparable lexical/vector score calibration between source backends.
    for index in range(max((len(g) for g in groups.values()), default=0)):
        for group in groups.values():
            if index < len(group):
                item = group[index]
                candidates.append({'doc_id': f'{item.source_type}:{item.doc_id}',
                    'version_id': item.version_id, 'chunk_text': item.content,
                    'title': item.title, 'score': item.score, 'evidence': item})
    ranked = rerank(query, candidates[:candidate_count(top_k)], top_k)
    return [row['evidence'] for row in ranked]
