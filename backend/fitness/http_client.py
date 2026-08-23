"""Minimal HTTP client so the rest of the backend doesn't care whether
`requests` is actually present in the arcgispro-py3 environment (see
docs/backend-architecture.md) - falls back to the standard library's
urllib if `requests` isn't installed.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class HTTPStatusError(Exception):
    """Raised on a non-2xx response, with the response body included in the
    message. `requests`' HTTPError and urllib's HTTPError both discard the
    body by default (their str() is just "400 Client Error: Bad Request for
    url: ...") - for the Google Health API, the body is where the actually
    useful error (e.g. "invalid data type ID", a scope/permission message)
    lives, and every caller up the stack (google_health_client -> sync.py's
    per-metric error handling -> the /api/sync response's `errors`) only
    ever sees str(exc), so losing the body here meant losing it everywhere.
    """


def _raise_requests_error(response):
    try:
        detail = response.text
    except Exception:  # noqa: BLE001 - body read is best-effort, never hide the original status
        detail = "<no response body>"
    raise HTTPStatusError(f"{response.status_code} {response.reason} for url: {response.url} - {detail}")


def _raise_urllib_error(exc):
    try:
        detail = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - body read is best-effort, never hide the original status
        detail = "<no response body>"
    raise HTTPStatusError(f"{exc.code} {exc.reason} for url: {exc.geturl()} - {detail}") from exc


def post_form(url, data):
    """POST url-encoded form data, return the parsed JSON response body."""
    if _HAS_REQUESTS:
        response = requests.post(url, data=data)
        if not response.ok:
            _raise_requests_error(response)
        return response.json()

    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _raise_urllib_error(exc)


def post_json(url, body, headers=None):
    """POST a JSON body, return the parsed JSON response body."""
    merged_headers = {"Content-Type": "application/json", **(headers or {})}

    if _HAS_REQUESTS:
        response = requests.post(url, json=body, headers=merged_headers)
        if not response.ok:
            _raise_requests_error(response)
        return response.json()

    encoded = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, headers=merged_headers, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _raise_urllib_error(exc)


def get_json(url, params=None, headers=None):
    """GET url (with optional query params/headers), return parsed JSON."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    if _HAS_REQUESTS:
        response = requests.get(url, headers=headers or {})
        if not response.ok:
            _raise_requests_error(response)
        return response.json()

    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _raise_urllib_error(exc)
