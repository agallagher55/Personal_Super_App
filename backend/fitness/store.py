"""Read/write helpers for the local JSON health-data store
(data/fitness/health_data.json - see fitness/ARCHITECTURE.md).

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
from pathlib import Path

# backend/fitness/store.py -> backend/fitness -> backend -> repo root, then
# data/fitness/health_data.json, alongside the rest of this app's data/ files
# (sections.json, tasks.json, tags.json) and covered by the same persistent
# disk mount in render.yaml.
DATA_PATH = Path(__file__).parent.parent.parent / "data" / "fitness" / "health_data.json"


def load_store():
    if not DATA_PATH.exists():
        return {"metrics": {}, "last_synced": {}}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_store(store):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


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
