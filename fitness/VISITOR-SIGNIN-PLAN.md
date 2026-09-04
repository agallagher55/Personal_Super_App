# Fitness: per-visitor Google sign-in (implementation plan)

Turns `/fitness` from a single-user, owner-only dashboard into one where
any allowed visitor signs in with their own Google account and sees only
their own Google Health data.

**Status: shipped.** Reviewed against the tree on 2026-09-04: every phase
below is implemented, the tests in §12 are green, and `roadmap.html` marks
the item Done. It landed in `a534108`, with follow-ups in `3aa8665`,
`b4dedb3` and `a1b9ff9`.

The document stays in place, in its original forward-looking voice, because
it is the only written record of *why* the design is shaped this way, and
twelve files link here for it: `backend/server.py`, `backend/fitness/`'s
`auth.py` / `api.py` / `store.py` / `cli.py`, `routes.md`, `DEPLOYMENT.md`,
`fitness/README.md`, `fitness/ARCHITECTURE.md`, `fitness/API-CONTRACT.md`,
`fitness/google_health.md`, and `roadmap.html`.

Read it as design rationale, not as work to do. §15 records where the
shipped code diverged from the text; where the two disagree, the code wins.
For what `/fitness` does *now*, [`ARCHITECTURE.md`](ARCHITECTURE.md) and
[`API-CONTRACT.md`](API-CONTRACT.md) are the current references.

---

## 1. What exists today, and why each piece blocks this

| Today | Blocks per-visitor sign-in because |
|---|---|
| `backend/fitness/config.json` holds the OAuth **client** config *and* one person's access/refresh tokens | Tokens have to become per user; the client config stays shared |
| `auth.authorize()` opens a browser and binds its own listener on port 8000 | Only usable from a terminal on the same machine as the operator, and it fights the main server for the port |
| `auth.get_valid_access_token()` takes no arguments | Every caller assumes exactly one identity exists |
| `store.DATA_PATH` is a module constant pointing at `data/fitness/health_data.json` | One file for everyone; also `load_store_cached()`'s cache is a single module global |
| `sync.sync_all()` and every `api.py` handler take no user | No place to thread an identity through |
| `backend/server.py` has no cookie handling, no session, no auth of any kind | There is nothing to identify a browser with |
| The frontend never asks "who am I" | No sign-in / sign-out affordance, no 401 handling |

Two facts discovered while reading the code that shape the plan:

1. **`backend/fitness/config.json` does not exist on Render.** `render.yaml`
   mounts the persistent disk over `data/` only, and the file is
   git-ignored, so the deployed service has never had OAuth credentials.
   Whatever this plan does, credentials must be readable from environment
   variables for the deployed app to work at all. Per-user tokens must live
   under `data/` so they survive a deploy.
2. **Google refresh tokens issued by an app in "Testing" publishing status
   expire after 7 days.** The roadmap notes the 100-user Test users cap but
   not this. It means re-consent is a routine event, not an edge case, so
   "refresh failed, send them back through consent" has to be a designed
   path rather than a 500. See §9.

---

## 2. Target design in one picture

```
Browser
  |
  |  GET /fitness            (no session cookie)
  v
server.py  --302-->  /fitness/login
                       |
                       |  click "Continue with Google"
                       v
                     GET /fitness/auth/start
                       - mint state, set signed short-lived state cookie
                       - 302 to accounts.google.com consent screen
                                    |
                                    v
                     GET /fitness/auth/callback?code=..&state=..
                       - verify state against the cookie
                       - exchange code for tokens (server to server)
                       - read `sub` / `email` from the returned id_token
                       - allowlist check
                       - write data/fitness/users/<uid>/{user,tokens}.json
                       - set signed session cookie
                       - 302 to /fitness
                                    |
                                    v
                     GET /fitness/api/metrics   (session cookie)
                       - resolve uid from cookie, else 401
                       - store.load_store_cached(uid)
```

Storage after the change:

```
backend/fitness/config.json        OAuth client id/secret/redirect/scopes only
                                   (env vars override every field)
data/fitness/session_secret        HMAC key, generated on first use
data/fitness/allowed_users.json    optional email allowlist (env var wins)
data/fitness/users/<uid>/user.json      google_sub, email, name, timestamps
data/fitness/users/<uid>/tokens.json    access/refresh token, expiry, scopes
data/fitness/users/<uid>/health_data.json   was data/fitness/health_data.json
```

`<uid>` is `sha256(google_sub).hexdigest()[:16]`. It is derived server side
from a value Google gave us, never from anything a request supplies, so it
cannot be steered into a path traversal. Store the raw `sub` inside
`user.json` for debugging.

---

## 3. New and changed files

### New backend modules (`backend/fitness/`)

| File | Contents |
|---|---|
| `jsonfile.py` | `read_json(path, default)` and `write_json_atomic(path, data)`. The atomic-write body is lifted verbatim from today's `store.save_store()` (temp file, `flush`, `fsync`, `os.replace`). `store.py` and `users.py` both use it. |
| `session.py` | Signed-cookie encode/decode, secret resolution, cookie header building. No I/O beyond reading/creating the secret file. |
| `users.py` | Per-user directory layout, read/write of `user.json` and `tokens.json`, `user_id_for_sub()`, `list_users()`, `clear_tokens()`, allowlist check. |

### Changed backend

| File | Change |
|---|---|
| `config.py` | Client config only. Add env-var overrides. Stop being the token store. |
| `auth.py` | Split into reusable web-flow pieces; every token function takes `user_id`. New `ReauthRequired` exception. |
| `store.py` | Every function takes `user_id`; cache becomes per user. |
| `sync.py` | `sync_all(user_id, metrics=None)`; per-user lock. |
| `api.py` | Every handler takes `user_id`; new `me()` handler. |
| `cli.py` | `sync` gains `--user` / `--all`; new `migrate`; `auth` removed. |
| `backend/server.py` | Cookie helpers, the auth gate, five new routes. |

### Changed frontend

| File | Change |
|---|---|
| `html/fitness/login.html` (new) | Sign-in page. |
| `static/fitness/js/login.js` (new) | Renders `?error=` messages, wires the button. |
| `static/fitness/js/api.js` | Central 401 handling, `getMe()`. |
| `static/fitness/js/components/page-header.js` | Signed-in email chip + Sign out. |
| `static/fitness/js/dashboard.js` | First-run empty state, auto first sync. |
| `static/fitness/css/styles.css` | Login page + account chip styles. |
| `static/js/home.js` | "Sign in to see your fitness data" on the fitness card when the API returns 401. |

### Changed config and docs

`.gitignore`, `render.yaml`, `routes.md`, `DEPLOYMENT.md`,
`fitness/ARCHITECTURE.md`, `fitness/API-CONTRACT.md`, `fitness/README.md`,
`fitness/google_health.md`, `roadmap.html`.

---

## 4. Phase 0: config, secrets, gitignore

**`.gitignore`** currently has `data/fitness/health_data.json*`, which does
not cover any of the new paths. Replace the fitness entries with:

```
backend/fitness/config.json
data/fitness/
```

Ignoring the whole directory is simplest and correct: nothing under
`data/fitness/` should ever be committed.

**`config.py`** becomes client-config only, with env vars taking precedence
so the deployed service works without a `config.json` on disk:

```python
"""Load the shared Google OAuth *client* configuration.

Per-visitor tokens are NOT here any more - they live per user under
data/fitness/users/<user_id>/tokens.json (see users.py). This file only
carries the app-level client id/secret/redirect/scopes, which are the same
for every visitor.

Every field can be supplied by an environment variable instead of
config.json. On Render only the env vars work: render.yaml mounts the
persistent disk over data/ only, so backend/fitness/config.json (which is
git-ignored) is never present in a deploy.
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

ENV_OVERRIDES = {
    "client_id": "FITNESS_GOOGLE_CLIENT_ID",
    "client_secret": "FITNESS_GOOGLE_CLIENT_SECRET",
    "redirect_uri": "FITNESS_OAUTH_REDIRECT_URI",
}

DEFAULT_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
]


def load_client_config():
    config = {}

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

    for key, env_name in ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = value

    scopes_env = os.environ.get("FITNESS_OAUTH_SCOPES")
    if scopes_env:
        config["scopes"] = scopes_env.split()
    config.setdefault("scopes", DEFAULT_SCOPES)

    missing = [k for k in ("client_id", "client_secret", "redirect_uri") if not config.get(k)]
    if missing:
        raise RuntimeError(
            "Google OAuth client config incomplete (missing: %s). Set the "
            "FITNESS_GOOGLE_* environment variables, or copy "
            "config.json.example to config.json - see fitness/google_health.md."
            % ", ".join(missing)
        )

    # A redirect_uri copy-pasted as a one-item list out of Google's
    # downloaded credentials JSON silently urlencodes into garbage - see
    # the troubleshooting section of fitness/google_health.md.
    if isinstance(config["redirect_uri"], list):
        config["redirect_uri"] = config["redirect_uri"][0]

    return config
```

Delete `save_config()`. Nothing writes client config any more.

**`config.json.example`** gains the three new scopes and the new redirect
path:

```json
{
  "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "YOUR_CLIENT_SECRET",
  "redirect_uri": "http://localhost:8000/fitness/auth/callback",
  "scopes": [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
  ]
}
```

Note the redirect URI moved from `/oauth/callback` to
`/fitness/auth/callback`. Both the local and the Render URL must be added
to the OAuth client's Authorized redirect URIs in Google Cloud Console
(§10).

---

## 5. Phase 1: `session.py`

Stateless signed cookies, not server-side sessions. Reasons: the app has no
session store and adding one to a flat-JSON app is disproportionate;
Render's free plan restarts the process regularly, which would drop
in-memory sessions; and a single instance means there is nothing to share
state across.

```python
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
import time
from pathlib import Path

SESSION_COOKIE = "fitness_session"
STATE_COOKIE = "fitness_oauth_state"

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
STATE_MAX_AGE_SECONDS = 10 * 60

SECRET_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "session_secret"

_secret_cache = None
```

Functions to implement:

- `get_secret()`: returns bytes. `FITNESS_SESSION_SECRET` env var if set,
  otherwise read `SECRET_PATH`, otherwise generate
  `secrets.token_urlsafe(48)`, write it with `os.open(..., 0o600)`, and
  return it. Cache in the module global. Changing the secret invalidates
  every session, which is the intended "log everyone out" lever, so say so
  in a comment.
- `sign(payload_dict) -> str` and `verify(cookie_value) -> dict | None`.
  `verify` returns `None` on a malformed value, a bad signature
  (`hmac.compare_digest`, never `==`), or an `exp` in the past. It must
  never raise on attacker-controlled input, so wrap the decode in
  `try/except (ValueError, TypeError, json.JSONDecodeError)`.
- `b64url_encode(raw_bytes)` / `b64url_decode(text)`: strip and re-add `=`
  padding. Google's id_token segments arrive unpadded too, so `auth.py`
  reuses `b64url_decode`.
- `new_session_cookie(user_id, secure)` and
  `new_state_cookie(state, next_path, secure)`: return a full `Set-Cookie`
  header **value**.
- `clearing_cookie(name, secure, path="/")`: same, with `Max-Age=0`.
- `read_cookie(header_value, name)`: parse the request's `Cookie` header
  with `http.cookies.SimpleCookie` and return the named value or `None`.

Cookie attributes, all required:

| Attribute | Value | Why |
|---|---|---|
| `HttpOnly` | always | No page script needs to read it; keeps an XSS from lifting it |
| `SameSite` | `Lax` | `Strict` would **not** send the cookie on the top-level redirect back from Google, breaking both the state check and the post-callback landing |
| `Secure` | when the request arrived over HTTPS | Render terminates TLS, so detect with `X-Forwarded-Proto: https`, falling back to off for local `http://localhost` |
| `Path` | `/` for the session, `/fitness/auth` for the state cookie | The state cookie is only ever read by the callback |
| `Max-Age` | 30 days / 10 minutes | Session length, and a short consent window |

`SameSite=Lax` also means a cross-site POST never carries the session
cookie, which is what protects `POST /fitness/api/sync` and
`POST /fitness/auth/logout` from CSRF. Add an `Origin` header check on both
POSTs as a second layer: reject when `Origin` is present and its host does
not match the request's `Host`.

---

## 6. Phase 2: `users.py`

```python
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
```

API:

```python
def user_id_for_sub(google_sub):
    return hashlib.sha256(google_sub.encode("utf-8")).hexdigest()[:16]


def user_dir(user_id):
    return USERS_ROOT / user_id


def load_user(user_id):        # -> dict or None
def save_user(user_id, record) # atomic
def load_tokens(user_id):      # -> dict or None
def save_tokens(user_id, tokens)
def clear_tokens(user_id):     # unlink tokens.json, ignore FileNotFoundError
def list_users():              # -> [user record], sorted by email
def upsert_from_claims(claims, tokens):  # -> user_id
```

`upsert_from_claims()` is what the callback calls. It derives the id,
merges the profile (keeping `created` if the directory already exists,
always refreshing `email`/`name`/`last_login`), and writes both files. It
must preserve an existing `refresh_token` when the new token response omits
one, exactly as today's `auth.authorize()` does:

```python
        tokens["refresh_token"] = tokens.get("refresh_token") or (existing or {}).get("refresh_token")
```

### Allowlist

```python
def is_allowed(email):
    """Whether this Google account may sign in.

    Google's own Test users list already gates who can reach consent while
    the OAuth client is unverified, but that list is managed outside this
    repo and stops applying the moment the client is verified. This is the
    app's own gate, and it fails closed: with nothing configured, only
    FITNESS_OWNER_EMAIL can sign in.
    """
```

Resolution order:

1. `FITNESS_ALLOWED_EMAILS`, comma separated.
2. `data/fitness/allowed_users.json`, a JSON list of email strings.
3. `FITNESS_OWNER_EMAIL` alone.

Compare case-insensitively on the whole address after `.strip().lower()`.
Do not normalize Gmail dots or `+` suffixes; an exact match on what Google
reports is the predictable rule. If none of the three is configured, return
`False` for everyone and have the callback redirect to
`/fitness/login?error=not_configured` so the failure is legible rather than
silent.

---

## 7. Phase 3: `auth.py`

Keep `http_client.post_form` and the token endpoint as they are. Restructure
around the web flow.

```python
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_REFRESH_MARGIN_SECONDS = 60


class ReauthRequired(Exception):
    """The stored refresh token is gone, revoked, or expired.

    Google expires refresh tokens after 7 days while the OAuth client's
    publishing status is still "Testing" (see fitness/google_health.md), so
    this is an ordinary, expected outcome, not a bug. Callers turn it into
    a 401 that sends the visitor back through /fitness/auth/start rather
    than a 500.
    """
```

Functions:

```python
def build_authorization_url(state):
    """Google consent URL. access_type=offline + prompt=consent so a
    refresh token comes back every time, including on re-consent after the
    7-day testing-mode expiry."""
```

Unchanged parameters from today, plus `include_granted_scopes` is not
needed. Keep `prompt=consent`.

```python
def exchange_code_for_tokens(code):
    """Authorization code -> token response dict, including id_token."""


def parse_id_token_claims(id_token, client_id):
    """Claims out of the id_token's middle segment.

    The signature is deliberately NOT verified. This token came back on a
    direct server-to-server TLS call to Google's own token endpoint in
    exchange_code_for_tokens(), so its provenance is already established
    and verifying a JWS by hand with no crypto dependency would add risk,
    not remove it. Never call this on a token that arrived from a browser.
    """
```

It should still sanity-check the claims, which is cheap:

- `aud == client_id`
- `iss in ("accounts.google.com", "https://accounts.google.com")`
- `exp` is in the future
- `email_verified` is truthy and `sub` is non-empty

Raise `ValueError` otherwise; the callback turns that into
`?error=auth_failed`.

```python
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
    data = {
        "client_id": ...,
        "client_secret": ...,
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

    ...
    users.save_tokens(user_id, tokens)
    return tokens["access_token"]
```

`authorize()` and `_CallbackHandler` and `_wait_for_callback()` are
**deleted**. The browser flow replaces them, and the old loopback listener
bound port 8000, the same port the main server wants.

Keep `webbrowser` out of the module entirely; nothing imports it any more.

---

## 8. Phase 4: `store.py`, `sync.py`, `api.py`

### `store.py`

```python
def data_path(user_id):
    return users.user_dir(user_id) / "health_data.json"
```

`load_store(user_id)`, `load_store_cached(user_id)`, `save_store(user_id,
store)`, and the corrupt-file quarantine all take `user_id` and use
`data_path(user_id)`. `add_data_points()` and `_point_key()` are unchanged
(they operate on an already-loaded dict).

The cache global becomes a dict:

```python
# user_id -> ((mtime_ns, size), parsed store). Guarded by _cache_lock.
_cache = {}
```

Everything else about `load_store_cached()`'s contract is unchanged,
including the docstring's warning that callers must treat the result as
read-only and that `sync.py` deliberately uses the uncached
`load_store()`. Add one line: entries are per user, so one visitor's sync
never invalidates another's cache.

Nothing evicts entries. With family-and-friends scale that is fine; say so
in a comment rather than adding an LRU.

### `sync.py`

```python
def sync_all(user_id, metrics=None):
    access_token = get_valid_access_token(user_id)
    data_store = store.load_store(user_id)
    ...
    store.save_store(user_id, data_store)
    return results, errors
```

Add a per-user lock so a double-clicked "Sync now" cannot interleave two
read-modify-write cycles on the same file. The server is a
`ThreadingHTTPServer`, so this is reachable today and gets more likely with
several visitors:

```python
_sync_locks = {}
_sync_locks_guard = threading.Lock()


def lock_for(user_id):
    with _sync_locks_guard:
        return _sync_locks.setdefault(user_id, threading.Lock())
```

`api.trigger_sync()` acquires it non-blocking and returns 409 if it is
already held, rather than queueing a second full Google pull behind the
first.

### `api.py`

Every handler grows a leading `user_id` parameter:

```python
def health(user_id)
def metrics_summary(user_id, query)
def metric_detail(user_id, metric, query)
def metric_samples(user_id, metric, query)
def trigger_sync(user_id)
```

`health()`'s `data_store_last_modified` now stats that user's file.

New handler for the header chip:

```python
def me(user_id):
    """Who the current session belongs to. Returns 200 with
    {"signed_in": false} rather than 401 when there is no session, so the
    frontend can render a signed-out header without treating it as an
    error."""
    if user_id is None:
        return 200, {"signed_in": False}
    record = users.load_user(user_id) or {}
    return 200, {
        "signed_in": True,
        "email": record.get("email", ""),
        "name": record.get("name", ""),
        "has_tokens": users.load_tokens(user_id) is not None,
    }
```

`trigger_sync()` gains two new outcomes:

```python
    try:
        lock = sync.lock_for(user_id)
        if not lock.acquire(blocking=False):
            return 409, {"error": "a sync is already running for this account"}
        try:
            results, errors = sync.sync_all(user_id)
        finally:
            lock.release()
    except auth.ReauthRequired as exc:
        return 401, {"error": str(exc), "reauth_url": "/fitness/auth/start"}
    except Exception as exc:
        return 502, {"error": f"sync failed: {exc}"}
```

Note `api.py` will now import `auth` and `users`, which it does not today.
Both are flat imports resolved from the `sys.path` entry `server.py`
already inserts, so no packaging change is needed.

### Migration of the owner's existing data

`data/fitness/health_data.json` has no owner recorded in it, and
`config.json`'s tokens carry no `sub`, so the user id cannot be computed
from what is on disk. Rather than guess, make the owner sign in through the
new flow first, then move the file:

```
python cli.py migrate
```

which:

1. Errors if nobody has signed in yet ("sign in at /fitness/login first").
   With several visitors signed in, `--user <email>` picks the target;
   without it, 2+ visitors is an error.
2. Errors if the destination `health_data.json` already exists, rather than
   overwriting it.
3. Moves `data/fitness/health_data.json` into that visitor's directory. A
   missing source file is not an error, it just prints "nothing to migrate"
   and carries on to step 4, so the command is safe to run on a fresh
   install.
4. Strips `access_token` / `refresh_token` / `token_expires_at` /
   `token_type` from `backend/fitness/config.json` if present, so a live
   refresh token is not left lying in a file nothing reads any more.
5. Prints exactly what it moved and what it stripped.

---

## 9. Phase 5: `backend/server.py`

### Cookie and identity helpers on `TaskHandler`

```python
    def is_secure_request(self):
        """Whether the browser reached us over HTTPS. Render terminates TLS
        at its proxy and forwards plain HTTP, so the header is the only
        signal; local development over http://localhost has neither."""
        forwarded = self.headers.get('X-Forwarded-Proto', '')
        return forwarded.split(',')[0].strip().lower() == 'https'

    def current_user_id(self):
        """user_id from a valid session cookie, or None."""

    def require_user(self):
        """current_user_id(), or None after already having sent a 401."""

    def send_redirect(self, location, cookies=()):
        """302 with optional Set-Cookie headers."""
```

`send_json()` gains an optional `cookies=()` parameter so the callback and
logout can set headers alongside a body. Everything else about it,
including the existing `no-store` headers, stays.

### Route table

| Method | Path | Signed out | Signed in |
|---|---|---|---|
| GET | `/fitness/login` | serve `html/fitness/login.html` | 302 `/fitness` |
| GET | `/fitness/auth/start` | 302 to Google, sets state cookie | same |
| GET | `/fitness/auth/callback` | completes sign-in | same |
| POST | `/fitness/auth/logout` | 302 `/fitness/login` | clears cookie, 302 `/fitness/login` |
| GET | `/fitness/api/me` | 200 `{"signed_in": false}` | 200 with email |
| GET | `/fitness` | 302 `/fitness/login` | serve dashboard |
| GET | `/fitness/<page>` | 302 `/fitness/login?next=/fitness/<page>` | serve page |
| GET | `/fitness/api/*` (all others) | 401 JSON | serve |
| POST | `/fitness/api/sync` | 401 JSON | run sync |

**Ordering matters and is the easiest thing to get wrong.** `do_GET`'s
existing chain ends with `if path.startswith('/fitness/')` treating the
remainder as a page name and 404ing anything not in `FITNESS_PAGES`. Every
new `/fitness/login` and `/fitness/auth/*` branch must be placed **above**
that branch, and above `path.startswith('/fitness/api/')` is fine too since
the prefixes are disjoint. Add `'/fitness/auth/start'`, `'/fitness/auth/callback'`
and `'/fitness/login'` as exact-match branches, not prefixes.

### `GET /fitness/auth/start`

```python
        state = secrets.token_urlsafe(24)
        next_path = parse_qs(parsed.query).get('next', [''])[0]
        if not next_path.startswith('/fitness') or next_path.startswith('//'):
            next_path = '/fitness'
        cookie = session.new_state_cookie(state, next_path, self.is_secure_request())
        self.send_redirect(auth.build_authorization_url(state), cookies=[cookie])
```

The `next` check is an open-redirect guard: `//evil.com` parses as a
protocol-relative absolute URL in a browser, and `startswith('/fitness')`
alone would let `/fitness@evil.com` through in some parsers, so require the
prefix **and** reject a leading `//`. Only `/fitness*` paths are accepted.

### `GET /fitness/auth/callback`

In order, redirecting to `/fitness/login?error=<code>` on any failure and
always clearing the state cookie:

1. `error` in the query (the visitor clicked Cancel): `?error=denied`.
2. Read and verify the state cookie; missing or invalid: `?error=state`.
3. `hmac.compare_digest` the cookie's `state` against the query's;
   mismatch: `?error=state`.
4. `auth.exchange_code_for_tokens(code)`; on `HTTPStatusError`:
   `?error=auth_failed`.
5. `auth.parse_id_token_claims(...)`; on `ValueError`: `?error=auth_failed`.
6. `users.is_allowed(claims["email"])`; if not: `?error=not_allowed`
   (or `?error=not_configured` when no allowlist exists at all).
7. `users.upsert_from_claims(claims, tokens)`.
8. Set the session cookie, clear the state cookie, 302 to the state
   cookie's `next` (already validated when it was minted).

Never log the code, the tokens, or the id_token. The existing code prints
nothing sensitive; keep it that way.

### Gate placement

Put the gate in exactly one place per method rather than sprinkling checks:

```python
        if path.startswith('/fitness/api/') and path != '/fitness/api/me':
            user_id = self.require_user()
            if user_id is None:
                return
            return self.handle_fitness_api_get(user_id, path, parsed)
```

and for the HTML pages, one `current_user_id()` check covering both
`/fitness` and `/fitness/<page>` before the existing serving logic.

`/fitness/api/me` is deliberately outside the gate.

---

## 10. Phase 6: frontend

### `html/fitness/login.html`

Same head block as `html/fitness/index.html` (fonts, both stylesheets, the
inline theme bootstrap, `site-nav` + `nav.js`). Body is one card:

- Heading "Personal Health"
- One paragraph: sign in with the Google account your Fitbit/Google Health
  data lives under
- `<a class="btn-primary" id="signin" href="/fitness/auth/start">Continue with Google</a>`
- `<p id="login-error" class="status status-error" role="status"></p>`
- `<script type="module" src="/static/fitness/js/login.js"></script>`

### `static/fitness/js/login.js`

Maps `?error=` to a sentence, and forwards `?next=` onto the start link:

| code | message |
|---|---|
| `denied` | "Sign-in was cancelled." |
| `state` | "That sign-in link expired. Try again." |
| `auth_failed` | "Google could not complete the sign-in. Try again." |
| `not_allowed` | "That Google account is not on this app's allowlist." |
| `not_configured` | "Sign-in is not configured yet: no allowed accounts are set." |
| `session_expired` | "Your session expired. Sign in again." |

Set `textContent`, never `innerHTML`, since the value comes from the URL.

### `static/fitness/js/api.js`

One change in `getJSON()` and `triggerSync()`: on `res.status === 401`,
redirect instead of throwing a message no one will read.

```js
function handleUnauthorized(body) {
  const target = (body && body.reauth_url) || "/fitness/login?error=session_expired";
  window.location.assign(target);
  // Never resolves: the navigation is already committed, and resolving
  // would let the caller render an error flash over a page that is leaving.
  return new Promise(() => {});
}
```

Add:

```js
export function getMe() {
  return getJSON("/fitness/api/me");
}

export async function signOut() {
  await fetch("/fitness/auth/logout", { method: "POST" });
  window.location.assign("/fitness/login");
}
```

### `static/fitness/js/components/page-header.js`

`renderPageHeader()` already runs on every fitness page, so it is the one
place to add the account chip. Append to the rendered markup:

```html
<span class="account-chip">
  <span id="account-email" class="account-email"></span>
  <button type="button" id="sign-out">Sign out</button>
</span>
```

then, without blocking the render, `getMe()` and fill in the email, wiring
the button to `signOut()`. A failed `getMe()` leaves the chip empty rather
than showing an error; the page's own 401 handling will already be moving
the browser.

### `static/fitness/js/dashboard.js`

A visitor who has just signed in has an empty store, so every card renders
"no data" with no explanation. After the first load, if every metric array
is empty and `getHealth()` reports `data_store_last_modified === null`,
show "No data yet, pulling it from Google now" and call `triggerSync()`
once automatically, then reload.

Do this from the dashboard rather than from the OAuth callback: the sync is
synchronous and can take many seconds, and holding the callback redirect
open for it would look like a hung sign-in.

Guard it with a flag so it fires at most once per page load, and only when
the store is genuinely untouched (`data_store_last_modified === null`), not
merely empty for the selected range.

### `static/js/home.js`

`loadFitness()` already falls back on a non-ok response, so this only
improves the wording:

```js
        if (res.status === 401) {
          setCard('home-fitness-metric', 'home-fitness-sub', '--', 'Sign in to see your fitness data');
          return null;
        }
```

### `static/fitness/css/styles.css`

Add `.account-chip`, `.account-email`, and a `.login-card` / `.btn-primary`
pair. Reuse the existing `.card`, `.status`, and `.status-error` classes
and the existing CSS custom properties so both themes work with no new
color values.

---

## 11. Phase 7: CLI, deployment, docs

### `cli.py`

```
python cli.py sync [--user <email or user_id>] [--all]
python cli.py users
python cli.py migrate [--user <email>]
```

- `sync` with neither flag and exactly one user: syncs that user. With
  `--all`: loops `users.list_users()`, isolating each in its own
  try/except so one visitor's expired refresh token does not abort the
  rest, and printing a per-user summary. This is the shape a nightly cron
  wants.
- `users` lists email, user_id, last login, whether tokens are present.
- `auth` is removed. Its help text is replaced by a line pointing at
  `/fitness/login`.

Update the module docstring: it currently documents `cli.py auth` and warns
about the port-8000 conflict, both of which stop being true.

### `render.yaml`

```yaml
    envVars:
      - key: PYTHON_VERSION
        value: "3.11"
      - key: FITNESS_GOOGLE_CLIENT_ID
        sync: false
      - key: FITNESS_GOOGLE_CLIENT_SECRET
        sync: false
      - key: FITNESS_OAUTH_REDIRECT_URI
        sync: false
      - key: FITNESS_SESSION_SECRET
        sync: false
      - key: FITNESS_OWNER_EMAIL
        sync: false
      - key: FITNESS_ALLOWED_EMAILS
        sync: false
```

`sync: false` tells Render to prompt for the value in the dashboard and
never store it in the blueprint. The disk mount is unchanged:
`data/fitness/users/` lands on it automatically.

### Google Cloud Console (manual, outside the repo)

Document in `fitness/google_health.md`:

1. Authorized redirect URIs, add both:
   - `http://localhost:8000/fitness/auth/callback`
   - `https://personal-super-app.onrender.com/fitness/auth/callback`
   The old `http://localhost:8000/oauth/callback` can be removed.
2. Scopes: add `openid`, `email`, `profile` to the consent screen alongside
   the three health scopes. Existing users re-consent automatically because
   `prompt=consent` is already set.
3. Test users: add each expected visitor's Google address. Unverified
   clients are capped at 100.
4. **The 7-day refresh-token expiry.** While the client's publishing status
   is "Testing", every refresh token Google issues expires after 7 days, so
   each visitor is sent back through consent about weekly. The app handles
   this (see `ReauthRequired`), but it is the single biggest thing that will
   make this feel unfinished, so it belongs in the doc. Moving the client to
   "In production" removes it but requires Google's verification process for
   the health scopes, which are sensitive.

### Docs to update

| File | Update |
|---|---|
| `routes.md` | Five new routes in the GET/POST tables; note that `/fitness*` now requires a session |
| `fitness/API-CONTRACT.md` | New "Authentication" section; `GET /fitness/api/me`; the 401 and 409 responses; delete "Auth on the query API itself" from "Not implemented" |
| `fitness/ARCHITECTURE.md` | §1 diagram gains the session/login boxes; §3 storage rewritten for the per-user layout; §4 both flows now start from a user id; §6 drops "No request-level auth" and gains "tokens are per user, still plaintext on disk" |
| `fitness/README.md` | Setup steps: env vars or config.json, then sign in at `/fitness/login`, then `cli.py migrate`; the "what changed" table gains config/data-store rows |
| `fitness/google_health.md` | §4 redirect URIs, §5 scopes, §7 config paths, §8 checklist, plus the new publishing-status/7-day note |
| `DEPLOYMENT.md` | A "Fitness sign-in environment variables" section, and the fact that `backend/fitness/config.json` is not on the persistent disk so env vars are mandatory in a deploy |
| `roadmap.html` | Flip "Fitness / visitor Google login" from "Not built", move the phase out of "Up next" |

---

## 12. Tests

The repo has no test suite, so this is additive rather than a change to an
existing harness. Keep it to stdlib `unittest` and to the pure functions
where a bug is a security bug:

`backend/fitness/tests/test_session.py`

- sign then verify round-trips the payload
- a flipped character in the signature fails
- a flipped character in the payload fails
- an `exp` in the past fails
- garbage input returns `None` rather than raising
- `b64url_decode` handles a value with no `=` padding

`backend/fitness/tests/test_users.py`

- `user_id_for_sub` is deterministic, 16 hex chars
- `is_allowed` is case-insensitive and trims whitespace
- `is_allowed` returns `False` with nothing configured
- `upsert_from_claims` keeps an existing `refresh_token` when the new
  response omits one, and keeps the original `created`

`backend/fitness/tests/test_auth_claims.py`

- `parse_id_token_claims` rejects a wrong `aud`, a wrong `iss`, an expired
  `exp`, `email_verified: false`, and a non-3-segment token

Run with `python -m unittest discover -s backend/fitness/tests`. Use
`tempfile.TemporaryDirectory` and monkeypatch the module-level roots rather
than touching real `data/`.

Shipped as written: 20 tests across the three files, green from the repo
root with exactly that command.

---

## 13. Suggested commit sequence

Not how it landed: the work went in as the single commit `a534108`. Kept
because the dependency it describes is still the useful part if any of this
is ever revisited. Each step is independently reviewable and leaves the
tree working:

1. `jsonfile.py` + `.gitignore` + `config.py` env overrides (no behavior
   change yet beyond credentials being loadable from the environment)
2. `session.py` + its tests
3. `users.py` + its tests
4. `auth.py` web flow, `ReauthRequired`, delete the CLI flow
5. `store.py` / `sync.py` / `api.py` per-user threading, plus
   `cli.py migrate`
6. `server.py` routes and the auth gate
7. Frontend: login page, `api.js`, header chip, dashboard first-run,
   home card
8. `render.yaml` + all docs

Steps 4 through 6 are the ones that cannot land separately without breaking
`/fitness`, so if they are split across commits, keep them in a single PR.

---

## 14. Decisions taken, and what to flip if you disagree

| Decision | Alternative |
|---|---|
| Everything becomes per user, including the owner, who is just user #1 with a one-off migration | Keep a single-user fallback path. Rejected: two code paths forever, and the fallback is the one that silently leaks data if the gate is ever misconfigured |
| Stateless signed cookies | A server-side session store. Rejected: nothing to store it in, and Render's free plan restarts drop it |
| Allowlist fails closed to `FITNESS_OWNER_EMAIL` | Trust Google's Test users list alone. Rejected: that list is invisible from the repo and stops applying the moment the client is verified |
| `sub` hashed to a 16-hex `user_id` for paths | Use the raw numeric `sub`. Hashing sanitizes the path segment by construction and keeps Google's identifier out of directory names |
| Tokens stay plaintext on the persistent disk | Encrypt at rest. That is `finance/ARCHITECTURE.md`'s bar for bank credentials; matching this repo's existing posture for health data is the consistent call, and encryption needs a key that would live next to the data anyway |
| `cli.py auth` removed | Keep it. It cannot coexist with the main server on port 8000, and the browser flow strictly supersedes it |
| Dashboard triggers the first sync, not the callback | Sync inside the callback. Rejected: a synchronous multi-second Google pull inside a redirect looks like a hung sign-in |

Open when this was written, and how each was settled:

1. **Should signed-out visitors see anything at `/fitness`?** The plan
   redirects them straight to `/fitness/login`. A public landing page
   describing the app is possible, but it is more markup for no clear gain
   at family-and-friends scale.
   **Settled as planned.** `/fitness` and `/fitness/<page>` 302 to
   `/fitness/login`; there is no public landing page.
2. **Session length.** 30 days is assumed. Shorter is more careful with
   health data on a shared machine; longer is not really available anyway,
   since the 7-day refresh-token expiry forces a Google round trip more
   often than the session itself expires.
   **Settled as planned.** `session.SESSION_MAX_AGE_SECONDS` is 30 days.
   Rotating `FITNESS_SESSION_SECRET` is the lever for ending every session
   early.
3. **Does the homepage card stay?** It currently shows the owner's step
   count to anyone who loads `/`. After this change it shows the signed-in
   visitor's own steps, or a sign-in prompt, which is correct, but it does
   mean `/` makes an authenticated call on every load.
   **Settled: it stays.** `static/js/home.js` renders "Sign in to see your
   fitness data" on a 401, so `/` does make one authenticated call per load.

---

## 15. Review notes: shipped code vs. this plan

Checked against the tree on 2026-09-04. Everything in §§4 to 12 is
implemented and the three test files pass. The differences below are the
ones worth knowing about.

### Where the code diverges

| This plan says | The code does | Assessment |
|---|---|---|
| §8: `migrate` "errors unless exactly one user directory exists" | Takes `--user <email>` to pick among several, and treats a missing `data/fitness/health_data.json` as "nothing to migrate" rather than an error | Plan was wrong and self-contradictory: §11 already documented the `--user` flag. §8 has been corrected above to match §11 and the code |
| §8: `migrate` "`os.replace()`s" the old file | `Path.rename()` | Equivalent here, since step 2 has already established the destination does not exist |
| §9: gate with `path.startswith('/fitness/api/') and path != '/fitness/api/me'` | `/fitness/api/me` is its own exact-match branch placed *above* the prefix branch in `do_GET` | Same effect, and it leaves §9's "ordering matters" rule doing all the work instead of splitting the exemption across an ordering rule and a condition |
| §13: an eight-commit sequence | One commit, `a534108` | The plan's own caveat, that steps 4 to 6 cannot land separately without breaking `/fitness`, turned out to cover more of the sequence than expected |
| §10: the account chip "appended to the rendered markup" | Moved to the header's top-right in `3aa8665`, then back into the date-range/sync controls row in `a1b9ff9` | Layout iteration only, no behavior change |

Two things the code added that the plan did not spell out, both worth
keeping: `session.verify()` also rejects a payload that decodes to
something other than a dict, and `server.py`'s `check_same_origin()` is
the `Origin` check §5 asks for, factored into one helper used by both
POST routes.

### Known gap found in this review

`session.get_secret()` is not safe against concurrent first use. On a
deploy with no `FITNESS_SESSION_SECRET` set and no
`data/fitness/session_secret` on disk yet, every thread that gets past the
`SECRET_PATH.exists()` check races into
`os.open(..., O_CREAT | O_EXCL)`: one wins and the rest raise
`FileExistsError`, which nothing catches, so those requests 500. Reproduced
with 8 concurrent cold callers, 5 of which raised. The same race has a
narrower window where a thread sees the file in the instant between
`os.open()` and the `write()`, reads it empty, and caches `b""` as the
secret, which would silently invalidate every cookie it then signs.

`server.py` reaches this on the first `/fitness/auth/start`, so the
practical blast radius is one failed sign-in that works on retry. The fix
is small: catch `FileExistsError` and fall through to reading the winner's
file, and write through the same temp-file-then-`os.replace()` dance
`jsonfile.write_json_atomic()` already uses. Setting
`FITNESS_SESSION_SECRET`, which `DEPLOYMENT.md` already recommends, avoids
the path entirely.

### Still open, tracked in `roadmap.html`

Neither is a defect in this plan; both are the follow-on work it implies.

- **OAuth client verification in Google Cloud Console.** Until then the
  7-day refresh-token expiry in §1 and the 100-user Test users cap both
  stand, which is the single biggest thing making sign-in feel unfinished
  past family-and-friends scale.
- **Scheduled sync for every visitor.** §11 built `cli.py sync --all` for
  exactly this, but nothing runs it on a cron yet, so a visitor's data only
  refreshes on first sign-in or a manual "Sync now".
