"""Shared JSON read/write helpers used by store.py and users.py.

write_json_atomic() is the same temp-file + fsync + os.replace() dance
store.py's save_store() always did, lifted out so users.py (per-user
profile/token files) doesn't have to duplicate it.
"""

import json
import os


def read_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and swap it into place with os.replace() (atomic
    # on both POSIX and Windows) rather than writing `path` directly -
    # otherwise a process kill, crash, or full disk partway through
    # json.dump() leaves a truncated, unparseable file in place of the last
    # known-good contents.
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
