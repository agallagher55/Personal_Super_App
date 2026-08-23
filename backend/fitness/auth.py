"""Google OAuth 2.0 authorization code flow for the Google Health API.

See google_health.md for the one-time Google Cloud/OAuth client setup this
depends on. Run `python cli.py auth` (from backend/) to authorize once;
other modules should call get_valid_access_token() to get a token,
transparently refreshed when needed.
"""

import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import http_client
from config import load_config, save_config

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Refresh this many seconds before actual expiry, to avoid racing a
# request against a token that expires mid-flight.
_REFRESH_MARGIN_SECONDS = 60


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles exactly one GET request: Google's OAuth redirect callback."""

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_state = params.get("state", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if self.server.auth_error:
            body = (
                f"<html><body>Authorization failed: {self.server.auth_error}. "
                "You can close this window.</body></html>"
            )
        else:
            body = (
                "<html><body>Authorization complete. You can close this "
                "window and return to the terminal.</body></html>"
            )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # silence default request logging to stderr


def _build_authorization_url(config, state):
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(config["scopes"]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _wait_for_callback(redirect_uri, expected_state):
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80

    server = HTTPServer((host, port), _CallbackHandler)
    server.auth_code = None
    server.auth_state = None
    server.auth_error = None
    server.handle_request()  # blocks until it serves exactly one request
    server.server_close()

    if server.auth_error:
        raise RuntimeError(f"Google returned an authorization error: {server.auth_error}")
    if server.auth_state != expected_state:
        raise RuntimeError("OAuth state mismatch - possible CSRF, aborting.")
    if not server.auth_code:
        raise RuntimeError("No authorization code received.")
    return server.auth_code


def _exchange_code_for_tokens(config, code):
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config["redirect_uri"],
    }
    return http_client.post_form(TOKEN_ENDPOINT, data)


def _refresh_access_token(config):
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": config["refresh_token"],
        "grant_type": "refresh_token",
    }
    tokens = http_client.post_form(TOKEN_ENDPOINT, data)
    config["access_token"] = tokens["access_token"]
    config["token_type"] = tokens.get("token_type", "Bearer")
    config["token_expires_at"] = time.time() + tokens.get("expires_in", 3600)
    save_config(config)
    return config["access_token"]


def authorize():
    """Run the full OAuth flow once: open the consent screen in a browser,
    capture the redirect locally, exchange the code for tokens, and save
    them to config.json.
    """
    config = load_config()
    state = secrets.token_urlsafe(16)
    url = _build_authorization_url(config, state)

    print("Opening browser to authorize with Google...")
    print(f"If it doesn't open automatically, visit:\n{url}\n")
    webbrowser.open(url)

    code = _wait_for_callback(config["redirect_uri"], state)
    tokens = _exchange_code_for_tokens(config, code)

    config["access_token"] = tokens["access_token"]
    # Google only returns a refresh_token on the first consent (or when
    # prompt=consent forces re-consent, as we do above) - keep the old one
    # otherwise so re-running auth doesn't silently drop it.
    config["refresh_token"] = tokens.get("refresh_token", config.get("refresh_token"))
    config["token_type"] = tokens.get("token_type", "Bearer")
    config["token_expires_at"] = time.time() + tokens.get("expires_in", 3600)
    save_config(config)

    print("Authorization complete. Tokens saved to backend/config.json.")


def get_valid_access_token():
    """Return a valid access token, refreshing it first if it's expired or
    about to expire. Raises RuntimeError if `authorize()` hasn't been run.
    """
    config = load_config()
    if "refresh_token" not in config:
        raise RuntimeError("Not authorized yet - run `python cli.py auth` first.")

    if time.time() > config.get("token_expires_at", 0) - _REFRESH_MARGIN_SECONDS:
        return _refresh_access_token(config)
    return config["access_token"]
