"""Load/save backend/config.json - OAuth client credentials and tokens.

config.json holds real credentials once populated and is git-ignored (see
.gitignore) - it must never be committed. Copy config.json.example to
config.json and fill in client_id/client_secret from google_health.md
before running `python cli.py auth`.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} not found. Copy config.json.example to config.json "
            "and fill in client_id/client_secret - see google_health.md."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
