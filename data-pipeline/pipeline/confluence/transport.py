"""Optional Windows-native HTTPS transport for Confluence Cloud reads.

Some local Windows networks complete TLS with Schannel (curl.exe) but stall
with Python's OpenSSL transport. Credentials are passed to curl on stdin,
never in a process argument or URL. Callers still validate the destination
origin and disable redirects at their own boundary.
"""

from __future__ import annotations

import json as json_module
import subprocess
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import requests


class CurlResponse:
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        self.headers: dict[str, str] = {}

    def json(self):
        return json_module.loads(self.body)


class CurlSession:
    def __init__(self) -> None:
        self.auth: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}

    @staticmethod
    def _config_value(value: str) -> str:
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '').replace('\r', '') + '"'

    def _request(self, method: str, url: str, *, params=None, auth=None,
                 headers=None, json=None, timeout=30, allow_redirects=False):
        if allow_redirects:
            raise ValueError('Confluence curl transport does not follow redirects')
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
            raise ValueError('Confluence curl transport requires an HTTPS origin')
        if params:
            query = urlencode([*parse_qsl(parts.query), *params.items()])
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
        credentials = auth or self.auth
        if not credentials or len(credentials) != 2:
            raise ValueError('Confluence curl transport requires credentials')
        config = 'user = ' + self._config_value(f'{credentials[0]}:{credentials[1]}') + '\n'
        for name, value in {**self.headers, **(headers or {})}.items():
            config += 'header = ' + self._config_value(f'{name}: {value}') + '\n'
        duration = max(timeout) if isinstance(timeout, tuple) else timeout
        args = ['curl.exe', '-q', '--silent', '--show-error', '--proto', '=https',
                '--max-redirs', '0', '--max-time', str(duration), '--config', '-',
                '--request', method, '--url', url, '--write-out', '\n%{http_code}']
        if json is not None:
            args.extend(['--data-binary', json_module.dumps(json, ensure_ascii=False)])
        try:
            result = subprocess.run(args, input=config, text=True, encoding='utf-8', capture_output=True,
                                    timeout=float(duration) + 2, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise requests.ConnectionError('Confluence curl transport unavailable') from exc
        if result.returncode != 0:
            raise requests.ConnectionError('Confluence curl request failed')
        try:
            body, code = result.stdout.rsplit('\n', 1)
            return CurlResponse(int(code), body)
        except (ValueError, TypeError) as exc:
            raise requests.ConnectionError('Confluence curl response invalid') from exc

    def get(self, url: str, **kwargs):
        return self._request('GET', url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._request('POST', url, **kwargs)
