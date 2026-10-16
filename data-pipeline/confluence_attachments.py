"""Download current page attachments alongside a complete Confluence page export.

Page artifacts and attachment artifacts remain separate. Credentials are sent
only to the configured tenant; media redirects never inherit tenant credentials.
This command downloads sources but does not claim they have been indexed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from confluence_export import ConfluenceClient, load_confluence_config


def attachment_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')
    suffix = Path(name).suffix[:16]
    stem = Path(name).stem[:80].rstrip(' .') or 'attachment'
    return stem + suffix


def download(client: ConfluenceClient, source_url: str, destination: Path) -> tuple[int, str]:
    """Use Windows curl TLS, checking every redirect and stripping cross-site auth."""
    tenant = urlparse(client.origin)
    initial = urlparse(source_url)
    if initial.scheme != 'https' or initial.netloc != tenant.netloc:
        raise ValueError('attachment download must start at the configured tenant')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary body on the same drive for atomic publication on Windows.
    with tempfile.TemporaryDirectory(prefix='aiqa-download-', dir=destination.parent) as temporary:
        body = Path(temporary) / 'body'
        headers = Path(temporary) / 'headers'
        url = source_url
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('invalid attachment redirect')
            # No credentials, cookies or authorization headers cross the tenant origin.
            config = ''
            if parsed.netloc == tenant.netloc:
                email, token = client.session.auth
                value = f'{email}:{token}'.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '').replace('\n', '')
                config = f'user = "{value}"\n'
            result = subprocess.run(
                ['curl.exe', '-q', '--silent', '--show-error', '--proto', '=https',
                 '--max-redirs', '0', '--max-time', '90', '--config', '-',
                 '--url', url, '--output', str(body), '--dump-header', str(headers),
                 '--write-out', '%{http_code}'],
                input=config, capture_output=True, text=True, encoding='utf-8',
                timeout=95, check=False,
            )
            if result.returncode:
                raise RuntimeError(f'attachment download transport failed (curl {result.returncode})')
            code = int(result.stdout.strip())
            if code in {301, 302, 303, 307, 308}:
                locations = re.findall(r'^location:\s*(.+)$', headers.read_text(encoding='utf-8'), re.I | re.M)
                if not locations:
                    raise RuntimeError('attachment redirect has no location')
                url = urljoin(url, locations[-1].strip())
                continue
            if code != 200:
                raise RuntimeError(f'attachment download HTTP {code}')
            digest = hashlib.sha256(body.read_bytes()).hexdigest()
            size = body.stat().st_size
            os.replace(body, destination)
            return size, digest
        raise RuntimeError('attachment redirect limit exceeded')


def export_attachments(client: ConfluenceClient, space_root: Path, workers: int = 6) -> dict:
    manifest = json.loads((space_root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'ok' or not manifest.get('full_sync'):
        raise ValueError('attachments require a successful complete page export')
    pages = manifest['pages']
    fetched_at = datetime.now(timezone.utc).isoformat()

    def list_page(page_id: str) -> list[dict]:
        path = f'/api/v2/pages/{page_id}/attachments'
        params = {'limit': 100}
        seen = set()
        items = []
        while path:
            if path in seen:
                raise ValueError('attachment pagination cycle')
            seen.add(path)
            payload = client._get_json(path, params=params)
            if not isinstance(payload.get('results'), list):
                raise ValueError('invalid attachment catalogue')
            for item in payload['results']:
                if str(item.get('pageId')) != page_id or item.get('status') != 'current':
                    raise ValueError('attachment parent/status mismatch')
                attachment_id = str(item.get('id') or '')
                if not re.fullmatch(r'(?:att)?\d+', attachment_id):
                    raise ValueError('invalid attachment identity')
                items.append(item)
            path = payload.get('_links', {}).get('next')
            params = None
        return items

    with ThreadPoolExecutor(max_workers=workers) as pool:
        grouped = list(pool.map(list_page, sorted(pages)))
    items = [item for group in grouped for item in group]
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('duplicate attachment identity')
    print(json.dumps({'pages_scanned': len(pages), 'current_attachments': len(items)}), flush=True)

    def fetch(item: dict) -> dict:
        page_id = str(item['pageId'])
        attachment_id = str(item['id'])
        path = space_root / 'attachments' / attachment_id / attachment_filename(item['title'])
        source_url = client._url(item.get('downloadLink') or item['_links']['download'])
        size, digest = download(client, source_url, path)
        if size != int(item['fileSize']):
            raise ValueError(f'attachment size mismatch: {attachment_id}')
        version = item.get('version') or {}
        metadata = {
            'source_type': 'confluence_attachment', 'attachment_id': attachment_id,
            'parent_page_id': page_id, 'page_id': page_id,
            'parent_page_version': pages[page_id]['version'],
            'space_id': manifest['space_id'], 'space_key': manifest['space_key'],
            'title': item['title'], 'filename': item['title'], 'version': int(version['number']),
            'last_updated': version.get('createdAt') or item.get('createdAt'),
            'fetched_at': fetched_at, 'source_latest_checked_at': fetched_at,
            'source_latest_version': int(version['number']), 'source_url': source_url,
            'source_content_sha256': digest, 'file_sha256': digest,
            'file_size': size, 'media_type': item['mediaType'],
            'sync_status': 'export_ready', 'indexed_at': None,
        }
        Path(str(path) + '.meta.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        return {**metadata, 'relative_path': path.relative_to(space_root).as_posix()}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(fetch, items))
    result = {
        'schema_version': 1, 'full_sync': True, 'status': 'ok',
        'space_key': manifest['space_key'], 'space_id': manifest['space_id'],
        'fetched_at': fetched_at, 'pages_scanned': len(pages), 'exported': len(rows),
        'attachments': {row['attachment_id']: row for row in rows},
    }
    (space_root / 'attachments-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space-root', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    client = ConfluenceClient(**load_confluence_config(args.env_file))
    result = export_attachments(client, args.space_root)
    print(json.dumps({'status': result['status'], 'attachments_downloaded': result['exported']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
