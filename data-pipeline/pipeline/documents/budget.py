"""Offline token budgets using the configured embedding tokenizer, never model inference."""
import os
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _tokenizer(path):
    if Path(path).is_file():
        from tokenizers import Tokenizer
        encoder = Tokenizer.from_file(path)
        encoder.no_truncation()
        encoder.no_padding()
        return encoder
    return None


def tokenizer():
    default = Path(__file__).resolve().parents[3] / 'data-persistence/models/bge-small-en-v1.5/tokenizer.json'
    model_dir = Path(os.getenv('LOCAL_EMBEDDING_MODEL_PATH', str(default.parent)))
    return _tokenizer(os.getenv('CHUNK_TOKENIZER_PATH', str(model_dir / 'tokenizer.json')))


def count_tokens(text):
    encoder = tokenizer()
    # Without local weights/tokenizer, conservative character accounting keeps
    # parsing offline. It is explicitly identified in chunk metadata.
    return len(encoder.encode(text, add_special_tokens=False).ids) if encoder else len(text)


def token_limit():
    return max(64, min(400, int(os.getenv('CHUNK_MAX_TOKENS', '320'))))


def split_budget(text, limit=None):
    """Lossless slices, preferring complete sentences and whitespace."""
    limit = limit or token_limit()
    parts = []
    while text and count_tokens(text) > limit:
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count_tokens(text[:mid]) <= limit:
                lo = mid
            else:
                hi = mid - 1
        candidates = [m.end() for m in re.finditer(r'[.!?。！？;；](?:\s+|$)|\n\n', text[:lo])]
        boundary = candidates[-1] if candidates and candidates[-1] >= lo // 2 else lo
        if boundary == lo:
            space = text.rfind(' ', lo // 2, lo)
            if space > 0:
                boundary = space + 1
        parts.append(text[:boundary])
        text = text[boundary:]
    if text:
        parts.append(text)
    return parts
