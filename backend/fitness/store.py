"""Read/write helpers for a visitor's local JSON health-data store
(data/fitness/users/<user_id>/health_data.json - see
fitness/ARCHITECTURE.md and fitness/VISITOR-SIGNIN-PLAN.md).

Stores the raw data points returned by the Google Health API, grouped by
our metric name, plus a last-synced date per metric. Storing the raw
points (rather than remapping into a custom shape) avoids losing or
misrepresenting fields we haven't fully verified the schema of - see the
caveats in google_health_client.py. Any friendlier shaping for the
frontend (fitness/API-CONTRACT.md) happens in api.py at serve time, not
here.
"""

import hashlib
import json
import os
import sys
import threading
import time

import users
from jsonfile import write_json_atomic

# (mtime_ns, size), parsed store) per user_id -> the store parsed from
# data_path(user_id) at that state. Guarded by _cache_lock; see
# load_store_cached(). Entries are per user, so one visitor's sync never
# invalidates another's cache. Nothing evicts entries - at
# family-and-friends scale that's fine.
_cache = {}
_cache_lock = threading.Lock()


def data_path(user_id):
    return users.user_dir(user_id) / "health_data.json"


def load_store(user_id):
    path = data_path(user_id)
    if not path.exists():
        return {"metrics": {}, "last_synced": {}}
    # Read fully and close the handle (exiting the `with` block) before any
    # possible os.replace() below - on Windows, unlike POSIX, a file can't be
    # renamed while this process still holds it open, which would otherwise
    # turn a JSONDecodeError into an unrelated PermissionError/WinError 32.
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        # A partial/non-atomic save_store() write (process killed, crashed,
        # or disk-full mid-write) can leave this file truncated - parsing it
        # then fails deep into the file rather than cleanly at byte 0.
        # Crashing every sync forever on a file sync itself produced is
        # worse than losing this run: rename the unreadable file aside (for
        # manual inspection/recovery) and start fresh, same as a first-ever
        # sync.
        corrupt_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            os.replace(path, corrupt_path)
        except OSError as rename_exc:
            # Some other process (antivirus, OneDrive/cloud sync, an editor)
            # briefly holding the file can still make the rename itself
            # fail. Don't let that turn into a crash either - fall through
            # to the fresh store below; save_store() will overwrite the
            # still-corrupt file on the next successful sync regardless.
            print(
                f"warning: {path} was not valid JSON ({exc}); could not "
                f"move it aside either ({rename_exc}) - starting from an "
                "empty store",
                file=sys.stderr,
            )
            return {"metrics": {}, "last_synced": {}}
        print(
            f"warning: {path} was not valid JSON ({exc}); "
            f"moved it to {corrupt_path} and starting from an empty store",
            file=sys.stderr,
        )
        return {"metrics": {}, "last_synced": {}}


def load_store_cached(user_id):
    """Same data as load_store(user_id), but skips the read+JSON-parse of
    data_path(user_id) entirely when the file hasn't changed since the last
    call - only an os.stat() (cheap) runs on a cache hit. `backend/fitness/api.py`'s
    read-only endpoints (dashboard summary, metric detail, samples) call
    this instead of load_store(): every one of them used to re-parse the
    whole file from scratch on every single request, and that file only
    grows over time (heart_rate samples in particular accumulate forever -
    see api.py's _POINT_DATE_EXTRACTORS comment), which is what made even
    just viewing the dashboard slow.

    Callers MUST treat the returned dict as read-only - it's the same
    object handed to every caller until the file changes, not a fresh copy
    per call. `sync.py` mutates its store in place over the course of
    several Google API calls before saving, so it deliberately uses the
    always-fresh, never-shared load_store() above instead - sharing this
    cache with it would let a concurrent read see a sync that's only
    half-applied.
    """
    path = data_path(user_id)
    if not path.exists():
        return {"metrics": {}, "last_synced": {}}
    stat = path.stat()
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        cached = _cache.get(user_id)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
    data = load_store(user_id)
    with _cache_lock:
        _cache[user_id] = (cache_key, data)
    return data


def save_store(user_id, store):
    # See jsonfile.write_json_atomic() for why this goes through a temp
    # file + os.replace() rather than writing data_path(user_id) directly -
    # otherwise a process kill, crash, or full disk partway through the
    # write leaves a truncated, unparseable file in place of the last
    # known-good store (see load_store()'s JSONDecodeError handling above).
    write_json_atomic(data_path(user_id), store)


def add_data_points(store, metric, data_points):
    """Merge new raw data points into the store under `metric`, keyed by the
    Google Health API's own point identifier so re-running sync over an
    overlapping date range doesn't create duplicates.

    Upserts rather than skip-if-seen: a repeat key doesn't always mean
    identical content. `steps`' dailyRollUp points are keyed by calendar day
    (see _point_key), and "today"'s rollup total legitimately increases as
    more steps happen - syncing again with the same day-key must overwrite
    the earlier, now-stale total, not discard the update. (A `name`-keyed
    point, a real past sleep/exercise session, won't actually change
    content between syncs, so overwriting it with itself is a no-op.)
    """
    existing = store.setdefault("metrics", {}).setdefault(metric, [])
    by_key = {_point_key(p): p for p in existing}
    for point in data_points:
        by_key[_point_key(point)] = point
    store["metrics"][metric] = list(by_key.values())


def _point_key(point):
    # `name` is the resource path Google assigns list-read points; points
    # without one (e.g. from a reconcile-style read) fall back to `time`.
    # Daily-rollup points (see google_health_client._list_via_daily_rollup)
    # have neither - they're keyed by their civilStartTime instead, which
    # uniquely identifies the rolled-up day.
    if point.get("name"):
        return point["name"]
    if point.get("time"):
        return point["time"]
    if point.get("civilStartTime"):
        return json.dumps(point["civilStartTime"], sort_keys=True)
    # heart_rate points have none of the above - every field (sampleTime,
    # beatsPerMinute) lives nested under "heartRate" instead. Falling back to
    # json.dumps(None) here used to produce the same "null" key for every
    # heart_rate point, so add_data_points() treated every sample after the
    # first in a sync as a duplicate and silently discarded it - a real
    # sync only ever kept 1 heart_rate point total, no matter how many
    # samples the API actually returned. Hash the whole point instead: two
    # points with identical content dedupe (correct - they're the same
    # sample), and any content difference (a different sampleTime, a
    # different bpm) produces a different key.
    return hashlib.sha256(json.dumps(point, sort_keys=True).encode("utf-8")).hexdigest()
