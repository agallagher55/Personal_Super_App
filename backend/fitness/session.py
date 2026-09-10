"""Signed cookie helpers for /fitness sign-in.

A cookie value is `<payload>.<signature>` where `payload` is base64url
JSON and `signature` is base64url HMAC-SHA256 of the *encoded* payload
string (signing the encoded form, not the dict, sidesteps any JSON
canonicalization question). Nothing is encrypted: the payload holds only a
user id and timestamps, both of which the holder already knows. The
signature is what stops a visitor from editing the user id.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

SESSION_COOKIE = "fitness_session"
STATE_COOKIE = "fitness_oauth_state"

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
STATE_MAX_AGE_SECONDS = 10 * 60

SECRET_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "session_secret"

_secret_cache = None
_secret_lock = threading.Lock()


def get_secret():
    """HMAC key used to sign every cookie this module issues.

    Resolution order: FITNESS_SESSION_SECRET env var, then SECRET_PATH on
    disk, then a freshly generated one written to SECRET_PATH. Changing the
    secret invalidates every existing session - that's the intended "log
    everyone out" lever if it's ever needed, not a bug to guard against.
    """
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    env_secret = os.environ.get("FITNESS_SESSION_SECRET")
    if env_secret:
        _secret_cache = env_secret.encode("utf-8")
        return _secret_cache

    # Serialize the read-or-generate below. server.py is a
    # ThreadingHTTPServer, so on a cold start (no FITNESS_SESSION_SECRET
    # set and no secret file yet) several requests reach this at once;
    # without the lock they each generate a different secret and race to
    # write it, and every loser used to die on an uncaught FileExistsError.
    with _secret_lock:
        if _secret_cache is None:
            _secret_cache = _read_or_create_secret()

    return _secret_cache


def _read_secret_file():
    """Contents of SECRET_PATH, or None if it is absent or empty."""
    try:
        return SECRET_PATH.read_bytes() or None
    except FileNotFoundError:
        return None


def _read_or_create_secret():
    existing = _read_secret_file()
    if existing:
        return existing

    secret = secrets.token_urlsafe(48).encode("utf-8")
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write the secret to a private temp file and then hard-link it into
    # place. os.link() refuses an existing destination, which makes
    # "publish this secret, or lose to whoever got there first" a single
    # atomic step. Creating SECRET_PATH directly with O_EXCL and writing
    # after would publish an empty file for the instant in between, and a
    # concurrent reader that caught it would cache b"" and sign cookies
    # that nothing can verify.
    tmp_path = SECRET_PATH.with_name(f"{SECRET_PATH.name}.{os.getpid()}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
            f.flush()
            os.fsync(f.fileno())

        try:
            os.link(tmp_path, SECRET_PATH)
        except FileExistsError:
            # Another process published first. Its secret is the one
            # already signing live cookies, so adopt that over ours.
            return _read_secret_file() or secret
        except OSError:
            # No hard-link support (some Windows filesystems). Fall back to
            # an exclusive create, which reopens the empty-file window
            # above but is better than not persisting the secret at all.
            return _create_secret_exclusive(secret)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass

    return secret


def _create_secret_exclusive(secret):
    try:
        fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_secret_file() or secret

    with os.fdopen(fd, "wb") as f:
        f.write(secret)
        f.flush()
        os.fsync(f.fileno())

    return secret


def b64url_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def b64url_decode(text):
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def sign(payload_dict):
    encoded = b64url_encode(json.dumps(payload_dict).encode("utf-8"))
    signature = hmac.new(get_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{b64url_encode(signature)}"


def verify(cookie_value):
    """Decodes and verifies a cookie produced by sign(). Returns the payload
    dict, or None on any malformed value, bad signature, or expired `exp` -
    never raises on attacker-controlled input."""
    try:
        encoded, signature_part = cookie_value.split(".", 1)
        expected = hmac.new(get_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        actual = b64url_decode(signature_part)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(b64url_decode(encoded))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if "exp" in payload and time.time() > payload["exp"]:
        return None
    return payload


def _cookie_header(name, value, max_age, secure, path):
    parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def new_session_cookie(user_id, secure):
    payload = {"user_id": user_id, "iat": time.time(), "exp": time.time() + SESSION_MAX_AGE_SECONDS}
    return _cookie_header(SESSION_COOKIE, sign(payload), SESSION_MAX_AGE_SECONDS, secure, "/")


def new_state_cookie(state, next_path, secure):
    payload = {"state": state, "next": next_path, "exp": time.time() + STATE_MAX_AGE_SECONDS}
    return _cookie_header(STATE_COOKIE, sign(payload), STATE_MAX_AGE_SECONDS, secure, "/fitness/auth")


def clearing_cookie(name, secure, path="/"):
    return _cookie_header(name, "", 0, secure, path)


def read_cookie(header_value, name):
    if not header_value:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header_value)
    except Exception:  # noqa: BLE001 - a malformed Cookie header must never 500 the request
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None
