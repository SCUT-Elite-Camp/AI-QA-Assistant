"""Actual encrypted image input preparation, without inference or persistence."""

import base64
import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from cryptography.exceptions import InvalidTag

from data_persistence.file_crypto import encrypt_file
from pipeline.files.fast_context import fast_file_context

pytestmark = pytest.mark.no_storage


def setup_file(tmp_path):
    source, encrypted = tmp_path / 'source.png', tmp_path / 'source.enc'
    Image.new('RGB', (2, 2), color='white').save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    key = b'x' * 32
    encrypt_file(source, encrypted, key, f'owner:{sha}'.encode())
    record = {'id': 'att_image', 'filename': 'image.png', 'status': 'ready', 'mime_type': 'image/png',
              'size_bytes': source.stat().st_size, 'blob_path': str(encrypted), 'dedupe_domain': 'owner',
              'sha256': sha, 'evidence_version': 3}
    store = SimpleNamespace(get_attachment=lambda _: record, list_evidence=lambda _: [
        {'evidence_id': 'ocr', 'source_type': 'ocr', 'content': 'Printed text'},
        {'evidence_id': 'old-vision', 'source_type': 'vision_analysis', 'content': 'Old model output'},
    ])
    settings = SimpleNamespace(encryption_key=key, max_image_bytes=100000, max_image_pixels=1000)
    body = SimpleNamespace(attachment_ids=['att_image'], query='Question', top_k=5)
    return body, store, settings, record


def test_reads_ocr_and_original_image_without_vision_inference(tmp_path):
    body, store, settings, record = setup_file(tmp_path)
    result = fast_file_context(body, store, settings)
    assert [item['content'] for item in result['items']] == ['Original image: image.png', 'Printed text']
    raw = result['items'][0]
    assert raw['content_kind'] == 'file' and raw['content_hash'] == record['sha256']
    assert raw['source_version'] == 3
    encoded = result['images'][0]['image_url'].split(',', 1)[1]
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (2, 2)


def test_image_pixel_budget_is_enforced_before_packing(tmp_path):
    body, store, settings, _ = setup_file(tmp_path)
    settings.max_image_pixels = 1
    with pytest.raises(RuntimeError, match='fast_image_budget_exceeded'):
        fast_file_context(body, store, settings)


def test_image_metadata_cannot_rebind_encrypted_original(tmp_path):
    body, store, settings, record = setup_file(tmp_path)
    record['sha256'] = 'different'
    with pytest.raises(InvalidTag):
        fast_file_context(body, store, settings)
