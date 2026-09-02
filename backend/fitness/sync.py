"""Orchestrates pulling data from the Google Health API into a visitor's
local JSON store (see fitness/ARCHITECTURE.md).
"""

import threading
from datetime import date, timedelta

import google_health_client
import store
from auth import get_valid_access_token

# How far back to pull the first time a given metric has never been synced.
DEFAULT_BACKFILL_DAYS = 30

# One lock per user_id, created on first use. Guards against a double-clicked
# "Sync now" interleaving two read-modify-write cycles on the same user's
# store file - the server is a ThreadingHTTPServer, so this is reachable
# today and gets more likely with several visitors syncing concurrently.
_sync_locks = {}
_sync_locks_guard = threading.Lock()


def lock_for(user_id):
    with _sync_locks_guard:
        return _sync_locks.setdefault(user_id, threading.Lock())


def sync_all(user_id, metrics=None):
    """Sync each metric from its last-synced date (or DEFAULT_BACKFILL_DAYS
    ago, if never synced) through today, for this user. Returns (results,
    errors): results is {metric: points_fetched} for metrics that
    succeeded, errors is {metric: error message} for metrics that didn't.

    One metric's request failing (e.g. a newly-added data type whose
    read_method turns out to be wrong for this account - see
    google_health_client.DATA_TYPES) must not abort the whole sync: an
    unhandled exception here used to skip store.save_store() entirely,
    silently discarding every other metric's successfully-fetched points
    from that run, not just the failing metric's. Each metric is now
    isolated in its own try/except, and last_synced is only advanced for
    metrics that actually succeeded, so a failed metric's date range is
    retried on the next sync instead of being skipped.
    """
    metrics = metrics or list(google_health_client.DATA_TYPES.keys())
    access_token = get_valid_access_token(user_id)
    data_store = store.load_store(user_id)
    today = date.today()

    results = {}
    errors = {}
    for metric in metrics:
        last_synced = data_store.get("last_synced", {}).get(metric)
        from_date = (
            date.fromisoformat(last_synced)
            if last_synced
            else today - timedelta(days=DEFAULT_BACKFILL_DAYS)
        )

        try:
            points = google_health_client.list_data_points(
                metric, from_date.isoformat(), today.isoformat(), access_token
            )
        except Exception as exc:  # noqa: BLE001 - isolated per metric, surfaced in `errors`
            errors[metric] = str(exc)
            continue

        store.add_data_points(data_store, metric, points)
        data_store.setdefault("last_synced", {})[metric] = today.isoformat()
        results[metric] = len(points)

    store.save_store(user_id, data_store)
    return results, errors
