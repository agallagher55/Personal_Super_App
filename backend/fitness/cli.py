"""Command-line entry point for one-off fitness backend operations.

Usage (run from backend/fitness/):
    python cli.py sync [--user <email or user_id>] [--all]
                            Pull new data from the Google Health API into
                            a visitor's data/fitness/users/<user_id>/health_data.json.
                            With neither flag, syncs the sole existing
                            visitor. With --all, loops every visitor,
                            isolating each in its own try/except.
    python cli.py users    List every signed-in visitor: email, user_id,
                            last login, whether tokens are present.
    python cli.py migrate [--user <email>]
                            One-time move of the pre-sign-in owner data
                            (data/fitness/health_data.json,
                            backend/fitness/config.json's tokens) into the
                            new per-user layout. See fitness/README.md.

Day-to-day serving happens through the main app (`python backend/server.py`
from the repo root, or `python3 backend/server.py` per render.yaml) - this
CLI only covers manual/scheduled syncs and the one-time migration. Sign-in
itself is now a browser flow at /fitness/login - there is no `cli.py auth`
any more (see fitness/VISITOR-SIGNIN-PLAN.md).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import users
from sync import sync_all

OLD_HEALTH_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "health_data.json"
OLD_CONFIG_PATH = Path(__file__).parent / "config.json"

_TOKEN_FIELDS = ("access_token", "refresh_token", "token_expires_at", "token_type")


def _resolve_user(identifier):
    """A CLI-supplied --user value can be an email or a raw user_id."""
    for record in users.list_users():
        if record.get("email", "").lower() == identifier.lower():
            return users.user_id_for_sub(record["google_sub"])
    if users.load_user(identifier) is not None:
        return identifier
    return None


def cmd_sync(args):
    all_users = "--all" in args
    user_arg = None
    if "--user" in args:
        user_arg = args[args.index("--user") + 1]

    if all_users:
        for record in users.list_users():
            user_id = users.user_id_for_sub(record["google_sub"])
            print(f"== {record.get('email', user_id)} ==")
            try:
                results, errors = sync_all(user_id)
            except Exception as exc:  # noqa: BLE001 - isolate one visitor's failure from the rest
                print(f"  FAILED: {exc}")
                continue
            for metric, count in results.items():
                print(f"  {metric}: {count} data point(s)")
            for metric, message in errors.items():
                print(f"  {metric}: FAILED - {message}")
        return

    if user_arg:
        user_id = _resolve_user(user_arg)
        if user_id is None:
            print(f"No signed-in visitor matches: {user_arg}")
            sys.exit(1)
    else:
        all_records = users.list_users()
        if len(all_records) != 1:
            print(
                f"{len(all_records)} visitors are signed in - pass --user <email> "
                "or --all. See `python cli.py users`."
            )
            sys.exit(1)
        user_id = users.user_id_for_sub(all_records[0]["google_sub"])

    results, errors = sync_all(user_id)
    for metric, count in results.items():
        print(f"{metric}: {count} data point(s)")
    for metric, message in errors.items():
        print(f"{metric}: FAILED - {message}")


def cmd_users(args):
    records = users.list_users()
    if not records:
        print("No visitors signed in yet.")
        return
    for record in records:
        user_id = users.user_id_for_sub(record["google_sub"])
        has_tokens = users.load_tokens(user_id) is not None
        last_login = record.get("last_login")
        last_login_str = (
            datetime.fromtimestamp(last_login, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if last_login
            else "never"
        )
        print(
            f"{record.get('email', '(no email)')}  user_id={user_id}  "
            f"last_login={last_login_str}  tokens={'yes' if has_tokens else 'no'}"
        )


def cmd_migrate(args):
    user_arg = None
    if "--user" in args:
        user_arg = args[args.index("--user") + 1]

    all_records = users.list_users()
    if not all_records:
        print("No visitors have signed in yet - sign in at /fitness/login first, then re-run migrate.")
        sys.exit(1)

    if user_arg:
        target = next((r for r in all_records if r.get("email", "").lower() == user_arg.lower()), None)
        if target is None:
            print(f"No signed-in visitor matches: {user_arg}")
            sys.exit(1)
    elif len(all_records) == 1:
        target = all_records[0]
    else:
        print(f"{len(all_records)} visitors are signed in - pass --user <email>.")
        sys.exit(1)

    user_id = users.user_id_for_sub(target["google_sub"])
    dest_path = users.user_dir(user_id) / "health_data.json"

    if not OLD_HEALTH_DATA_PATH.exists():
        print(f"Nothing to migrate: {OLD_HEALTH_DATA_PATH} does not exist.")
    elif dest_path.exists():
        print(f"Refusing to overwrite existing {dest_path} - remove it first if you really want to replace it.")
        sys.exit(1)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        OLD_HEALTH_DATA_PATH.rename(dest_path)
        print(f"Moved {OLD_HEALTH_DATA_PATH} -> {dest_path}")

    if OLD_CONFIG_PATH.exists():
        import json

        with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        stripped = [field for field in _TOKEN_FIELDS if config.pop(field, None) is not None]
        if stripped:
            with open(OLD_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Stripped {', '.join(stripped)} from {OLD_CONFIG_PATH}")
        else:
            print(f"No leftover token fields found in {OLD_CONFIG_PATH}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]
    if command == "sync":
        cmd_sync(args)
    elif command == "users":
        cmd_users(args)
    elif command == "migrate":
        cmd_migrate(args)
    else:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
