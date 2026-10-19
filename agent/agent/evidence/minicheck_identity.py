"""Bind the selected local MiniCheck checkpoint to the installed weight manifest."""
import hashlib
import json
from pathlib import Path


def verified_minicheck_weights(model_dir: str | Path) -> tuple[dict, bool]:
    root = Path(model_dir).resolve()
    record = json.loads((root / 'verified.json').read_text(encoding='utf-8-sig'))
    if record.get('repo') != 'lytang/MiniCheck-DeBERTa-v3-Large':
        raise ValueError('unexpected_minicheck_model')
    filename = record.get('weight_file')
    if filename not in {'model.safetensors', 'pytorch_model.bin'}:
        raise ValueError('unsupported_minicheck_weight_file')
    weight = (root / filename).resolve()
    if not weight.is_relative_to(root):
        raise ValueError('invalid_minicheck_weight_path')
    with weight.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != record.get('sha256'):
            raise ValueError('minicheck_weight_hash_mismatch')
    # Pin the actual Transformers loader to the hashed file, even if both formats exist.
    return record, filename == 'model.safetensors'
