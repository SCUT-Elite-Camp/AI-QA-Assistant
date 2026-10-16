import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from confluence_attachments import attachment_filename, download, export_attachments


def test_download_drops_tenant_credentials_on_media_redirect(monkeypatch, tmp_path):
    inputs = []

    def run(args, **kwargs):
        inputs.append(kwargs['input'])
        body = Path(args[args.index('--output') + 1])
        headers = Path(args[args.index('--dump-header') + 1])
        assert body.parent.parent == tmp_path  # Atomic replace stays on the destination drive.
        if len(inputs) == 1:
            headers.write_text('HTTP/1.1 302\nLocation: https://media.example/file\n', encoding='utf-8')
            body.write_bytes(b'')
            return SimpleNamespace(returncode=0, stdout='302')
        body.write_bytes(b'\x00\xffreal bytes')
        headers.write_text('HTTP/1.1 200\n', encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='200')

    monkeypatch.setattr('confluence_attachments.subprocess.run', run)
    client = SimpleNamespace(origin='https://tenant.atlassian.net', session=SimpleNamespace(auth=('exporter', 'secret')))
    destination = tmp_path / 'report.bin'
    size, digest = download(client, client.origin + '/wiki/download', destination)
    assert 'exporter:secret' in inputs[0]
    assert inputs[1] == ''
    assert destination.read_bytes() == b'\x00\xffreal bytes'
    assert size == 12 and len(digest) == 64


def test_attachment_list_checks_parent_before_download(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'status': 'ok', 'full_sync': True, 'pages': {'123': {}},
    }), encoding='utf-8')
    client = SimpleNamespace(_get_json=lambda *a, **k: {
        'results': [{'pageId': '999', 'status': 'current', 'id': 'att10'}],
    })
    with pytest.raises(ValueError, match='parent/status'):
        export_attachments(client, tmp_path)
    assert not (tmp_path / 'attachments-manifest.json').exists()


def test_download_refuses_a_cross_tenant_initial_url(tmp_path):
    client = SimpleNamespace(origin='https://tenant.atlassian.net')
    with pytest.raises(ValueError, match='configured tenant'):
        download(client, 'https://another.atlassian.net/download', tmp_path / 'data')
    assert not (tmp_path / 'data').exists()


def test_attachment_filename_cannot_escape_its_id_directory():
    name = attachment_filename('../folder\\report.pptx')
    assert '/' not in name and '\\' not in name
    assert Path(name).suffix == '.pptx'
