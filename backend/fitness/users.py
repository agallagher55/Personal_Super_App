"""Per-visitor records for /fitness sign-in.

Layout, all under the Render persistent disk mount (see DEPLOYMENT.md):

    data/fitness/users/<user_id>/user.json      profile, stable
    data/fitness/users/<user_id>/tokens.json    OAuth tokens, rewritten often
    data/fitness/users/<user_id>/health_data.json  see store.py

`user_id` is sha256(google_sub)[:16]. It is derived from Google's own
stable account identifier, server side, never from request input, so it is
always a safe path segment.

Profile and tokens are separate files so cli.py's `sync --all` can
enumerate visitors without reading anybody's tokens, and so the
frequently-rewritten token file cannot corrupt the profile.
"""

import hashlib
import json
import os
import time
from pathlib import Path

from jsonfile import read_json, write_json_atomic

USERS_ROOT = Path(__file__).parent.parent.parent / "data" / "fitness" / "users"
ALLOWED_USERS_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "allowed_users.json"


def user_id_for_sub(google_sub):
    return hashlib.sha256(google_sub.encode("utf-8")).hexdigest()[:16]


def user_dir(user_id):
    return USERS_ROOT / user_id


def load_user(user_id):
    return read_json(user_dir(user_id) / "user.json", None)


def save_user(user_id, record):
    write_json_atomic(user_dir(user_id) / "user.json", record)


def load_tokens(user_id):
    return read_json(user_dir(user_id) / "tokens.json", None)


def save_tokens(user_id, tokens):
    write_json_atomic(user_dir(user_id) / "tokens.json", tokens)


def clear_tokens(user_id):
    try:
        os.unlink(user_dir(user_id) / "tokens.json")
    except FileNotFoundError:
        pass


def list_users():
    if not USERS_ROOT.exists():
        return []
    records = []
    for entry in USERS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        record = load_user(entry.name)
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda r: r.get("email", ""))


def upsert_from_claims(claims, tokens):
    """Creates or refreshes a visitor's profile + tokens from a verified
    id_token's claims and a fresh token response. Returns the user_id.

    Preserves an existing refresh_token when the new token response omits
    one (Google only returns a refresh_token on first consent, or when
    prompt=consent forces re-consent - see auth.py), and preserves the
    profile's original `created` timestamp across repeat sign-ins.
    """
    user_id = user_id_for_sub(claims["sub"])
    existing_user = load_user(user_id)
    existing_tokens = load_tokens(user_id)
    now = time.time()

    record = {
        "google_sub": claims["sub"],
        "email": claims.get("email", ""),
        "name": claims.get("name", ""),
        "created": (existing_user or {}).get("created", now),
        "last_login": now,
    }
    save_user(user_id, record)

    tokens = dict(tokens)
    tokens["refresh_token"] = tokens.get("refresh_token") or (existing_tokens or {}).get("refresh_token")
    save_tokens(user_id, tokens)

    return user_id


def is_allowed(email):
    """Whether this Google account may sign in.

    Google's own Test users list already gates who can reach consent while
    the OAuth client is unverified, but that list is managed outside this
    repo and stops applying the moment the client is verified. This is the
    app's own gate, and it fails closed: with nothing configured, only
    FITNESS_OWNER_EMAIL can sign in.
    """
    if not email:
        return False
    email = email.strip().lower()

    env_list = os.environ.get("FITNESS_ALLOWED_EMAILS")
    if env_list:
        allowed = {e.strip().lower() for e in env_list.split(",") if e.strip()}
        return email in allowed

    allowed_file = read_json(ALLOWED_USERS_PATH, None)
    if allowed_file is not None:
        allowed = {str(e).strip().lower() for e in allowed_file}
        return email in allowed

    owner_email = os.environ.get("FITNESS_OWNER_EMAIL")
    if owner_email:
        return email == owner_email.strip().lower()

    return False
