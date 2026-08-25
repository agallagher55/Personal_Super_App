"""Load/save data/fitness/config.json - OAuth client credentials and tokens.

config.json holds real credentials once populated and is git-ignored (see
.gitignore) - it must never be committed. Copy config.json.example to
data/fitness/config.json and fill in client_id/client_secret from
google_health.md before running `python cli.py auth`.

Lives under data/fitness/ (not backend/fitness/, where the code sits)
because that's the directory render.yaml mounts as a persistent disk -
outside it, a Render free-tier instance loses the file (and with it the
refresh token) on every redeploy or idle spin-down, silently breaking
POST /fitness/api/sync while GET endpoints keep serving the
already-persisted health_data.json.
"""

import json
from pathlib import Path

# backend/fitness/config.py -> backend/fitness -> backend -> repo root, then
# data/fitness/config.json - same DATA_PATH derivation as store.py.
CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} not found. Copy backend/fitness/config.json.example to "
            f"{CONFIG_PATH} and fill in client_id/client_secret - see google_health.md."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
