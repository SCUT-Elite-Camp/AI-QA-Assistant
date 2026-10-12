from types import SimpleNamespace

import pytest

from shared_runtime.curl_transport import CurlSession


def test_curl_transport_keeps_credentials_off_process_arguments(monkeypatch):
    observed = {}

    def run(args, **kwargs):
        observed.update(args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}\n200')

    monkeypatch.setattr('shared_runtime.curl_transport.subprocess.run', run)
    session = CurlSession()
    session.auth = ('user@example.com', 'secret-token')
    response = session.get('https://example.atlassian.net/wiki/api/v2/spaces',
                           params={'keys': 'RAG'}, timeout=5, allow_redirects=False)
    assert response.status_code == 200 and response.json() == {'ok': True}
    assert 'secret-token' not in ' '.join(observed['args'])
    assert 'secret-token' in observed['input']
    assert observed['encoding'] == 'utf-8'
    assert '--max-redirs' in observed['args']


def test_curl_transport_rejects_non_https_and_redirects():
    session = CurlSession()
    session.auth = ('user@example.com', 'secret-token')
    with pytest.raises(ValueError, match='HTTPS'):
        session.get('http://example.atlassian.net/wiki/api/v2/spaces')
    with pytest.raises(ValueError, match='redirects'):
        session.get('https://example.atlassian.net/wiki/api/v2/spaces', allow_redirects=True)
