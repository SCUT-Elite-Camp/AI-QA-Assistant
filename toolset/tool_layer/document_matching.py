"""Literal multilingual document names, without granting source access."""
import re
import unicodedata
from difflib import SequenceMatcher

def compact_title(value: str) -> str:
    return ''.join(re.findall(r'[a-z0-9\u3400-\u9fff]+', unicodedata.normalize('NFKC', value).casefold()))

def named_document_ids(query: str, documents: list[dict]) -> list[str]:
    key = compact_title(query)
    exact = []
    for d in documents:
        title = compact_title(str(d.get('title') or ''))
        if title and title in key and (len(title) >= 8 or len(re.findall(r'[\u3400-\u9fff]', title)) >= 4 or re.match(r'^(?:查找文档|find the source document)', query, re.I)):
            exact.append((len(title), str(d['doc_id'])))
        else:
            # Prefix labels and filename separators are display conventions;
            # require every remaining literal component, including dates.
            clean = re.sub(r'^\[[^\]]+\]\s*', '', str(d.get('title') or '')).casefold()
            # Catalog ordinal labels are not part of a document's name. Keep
            # years and date punctuation, which distinguish real sources.
            clean = re.sub(r'^\d{1,3}\s+', '', clean)
            parts = re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', clean)
            parts = [p for p in parts if p not in {'pdf','pptx','docx','xlsx','md'}]
            if len(parts) >= 2 and all(compact_title(p) in key for p in parts):
                exact.append((sum(map(len,parts)), str(d['doc_id'])))
    if exact:
        longest = max(n for n, _ in exact)
        return [i for n, i in exact if n == longest]
    # Partial Chinese names remain literal; require four contiguous characters.
    scored = []
    runs = re.findall(r'[\u3400-\u9fff]{4,}', query)
    for d in documents:
        title = str(d.get('title') or '')
        score = max((SequenceMatcher(None, run, title, autojunk=False).find_longest_match().size for run in runs), default=0)
        if score >= 4:scored.append((score, str(d['doc_id'])))
    if scored:
        best = max(n for n, _ in scored)
        return [i for n, i in scored if n == best][:3]
    return []
