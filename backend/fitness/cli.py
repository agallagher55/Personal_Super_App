"""Command-line entry point for one-off fitness backend operations.

Usage (run from backend/fitness/):
    python cli.py auth     Run the Google OAuth flow once and save tokens
                            to config.json (see ../../fitness/google_health.md).
    python cli.py sync     Pull new data from the Google Health API into
                            data/fitness/health_data.json.

Day-to-day serving happens through the main app (`python backend/server.py`
from the repo root, or `python3 backend/server.py` per render.yaml) - this
CLI only covers the one-time auth flow and manual/scheduled syncs. Note the
default redirect_uri in config.json (http://localhost:8000/oauth/callback)
binds port 8000 for the auth flow's one-off callback listener - don't run
`cli.py auth` while the main app server is also bound to that port.
"""

import sys

from auth import authorize
from sync import sync_all


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "auth":
        authorize()
    elif command == "sync":
        results, errors = sync_all()
        for metric, count in results.items():
            print(f"{metric}: {count} data point(s)")
        for metric, message in errors.items():
            print(f"{metric}: FAILED - {message}")
    else:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
