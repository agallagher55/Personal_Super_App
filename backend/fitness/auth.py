"""Google OAuth 2.0 authorization code flow for the Google Health API,
driven by a browser sign-in through backend/server.py rather than a CLI
step (see fitness/VISITOR-SIGNIN-PLAN.md). Every token function takes a
user_id: tokens are per visitor, stored under
data/fitness/users/<user_id>/tokens.json via users.py.
"""

import json
import time
from urllib.parse import urlencode

import http_client
import users
from config import load_client_config
from session import b64url_decode

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Refresh this many seconds before actual expiry, to avoid racing a
# request against a token that expires mid-flight.
_REFRESH_MARGIN_SECONDS = 60


class ReauthRequired(Exception):
    """The stored refresh token is gone, revoked, or expired.

    Google expires refresh tokens after 7 days while the OAuth client's
    publishing status is still "Testing" (see fitness/google_health.md), so
    this is an ordinary, expected outcome, not a bug. Callers turn it into
    a 401 that sends the visitor back through /fitness/auth/start rather
    than a 500.
    """


def build_authorization_url(state):
    """Google consent URL. access_type=offline + prompt=consent so a
    refresh token comes back every time, including on re-consent after the
    7-day testing-mode expiry."""
    config = load_client_config()
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


def exchange_code_for_tokens(code):
    """Authorization code -> token response dict, including id_token."""
    config = load_client_config()
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config["redirect_uri"],
    }
    return http_client.post_form(TOKEN_ENDPOINT, data)


def parse_id_token_claims(id_token, client_id):
    """Claims out of the id_token's middle segment.

    The signature is deliberately NOT verified. This token came back on a
    direct server-to-server TLS call to Google's own token endpoint in
    exchange_code_for_tokens(), so its provenance is already established
    and verifying a JWS by hand with no crypto dependency would add risk,
    not remove it. Never call this on a token that arrived from a browser.
    """
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        raise ValueError("id_token is not a 3-segment JWT")

    try:
        claims = json.loads(b64url_decode(parts[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("id_token payload is not valid JSON") from exc

    if claims.get("aud") != client_id:
        raise ValueError("id_token aud does not match our client_id")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("id_token iss is not Google")
    if not claims.get("exp") or time.time() > claims["exp"]:
        raise ValueError("id_token is expired")
    if not claims.get("email_verified"):
        raise ValueError("id_token email is not verified")
    if not claims.get("sub"):
        raise ValueError("id_token has no sub")

    return claims


def get_valid_access_token(user_id):
    """Valid access token for this user, refreshed if within the margin.

    Raises ReauthRequired when there are no stored tokens, or when the
    refresh itself is rejected.
    """
    tokens = users.load_tokens(user_id)
    if not tokens or not tokens.get("refresh_token"):
        raise ReauthRequired("no stored Google credentials for this user")

    if time.time() <= tokens.get("token_expires_at", 0) - _REFRESH_MARGIN_SECONDS:
        return tokens["access_token"]

    return _refresh_access_token(user_id, tokens)


def _refresh_access_token(user_id, tokens):
    config = load_client_config()
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
    }
    try:
        refreshed = http_client.post_form(TOKEN_ENDPOINT, data)
    except http_client.HTTPStatusError as exc:
        # invalid_grant means revoked or expired: the stored token will
        # never work again, so drop it rather than retrying it forever on
        # every request.
        users.clear_tokens(user_id)
        raise ReauthRequired("Google rejected the stored refresh token") from exc

    tokens = dict(tokens)
    tokens["access_token"] = refreshed["access_token"]
    tokens["token_type"] = refreshed.get("token_type", "Bearer")
    tokens["token_expires_at"] = time.time() + refreshed.get("expires_in", 3600)
    users.save_tokens(user_id, tokens)
    return tokens["access_token"]
