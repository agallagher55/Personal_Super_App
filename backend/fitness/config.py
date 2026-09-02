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
