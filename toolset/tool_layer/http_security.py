"""Internal scoped credentials must never follow an HTTP redirect."""
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, 'internal_redirect_forbidden', headers, fp)


def urlopen_no_redirect(request, *, timeout):
    return build_opener(_RejectRedirect()).open(request, timeout=timeout)
