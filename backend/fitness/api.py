"""Query API for the ported Personal Health app, mounted under /fitness/api
(see fitness/API-CONTRACT.md and backend/server.py's routing).

Reshapes raw points from the local data store (data/fitness/health_data.json,
via store.py) into the response shapes the frontend expects - never calls
the Google Health API directly, except sync(), which delegates to
sync.sync_all(). Plain functions rather than an HTTP handler class, since
backend/server.py's TaskHandler owns the actual request/response plumbing
and dispatches into these - see that module's /fitness/api/* routes.

Ported from the standalone personal_health app's backend/server.py; the
reshaping logic itself is unchanged, only the HTTP glue was extracted out.
"""

from datetime import date, datetime, timedelta

import store
import sync

KNOWN_METRICS = ("steps", "heart_rate", "sleep", "activity", "spo2", "hrv", "breathing_rate", "temperature", "weight")

# Default lookback window, in days (inclusive of `to`), when a request omits
# `from` - per API-CONTRACT.md ("last 7 days" for the dashboard summary,
# "last 30 days" for a single-metric detail view).
DEFAULT_SUMMARY_RANGE_DAYS = 7
DEFAULT_DETAIL_RANGE_DAYS = 30


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

def _parse_range(query, default_days):
    today = date.today()
    to_str = query.get("to", [None])[0]
    from_str = query.get("from", [None])[0]
    to_d = date.fromisoformat(to_str) if to_str else today
    from_d = date.fromisoformat(from_str) if from_str else to_d - timedelta(days=default_days - 1)
    return from_d, to_d


def _in_range(date_str, from_d, to_d):
    if not date_str:
        return False
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return False
    return from_d <= d <= to_d


# ---------------------------------------------------------------------------
# Raw-point field extraction
#
# Reshaping notes: field paths below are confirmed against a real synced
# data/fitness/health_data.json (live account, 2026-08-18) for all four
# metrics - see fitness/ARCHITECTURE.md. Each metric's payload nests
# its fields under a key named after the Google data type (`heartRate`,
# `sleep`, `exercise`), except `steps`' dailyRollUp points, which are flat.
# ---------------------------------------------------------------------------

def _to_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return float(value) if "." in value else int(value)
        return value
    except (TypeError, ValueError):
        return None


def _civil_value_to_date(value):
    """Best-effort YYYY-MM-DD extraction from one of the time-ish shapes the
    API uses: a plain ISO string, or a dailyRollUp-style
    {"date": {"year", "month", "day"}}.
    """
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, dict):
        d = value.get("date")
        if isinstance(d, dict) and {"year", "month", "day"} <= d.keys():
            return f'{d["year"]:04d}-{d["month"]:02d}-{d["day"]:02d}'
    return None


def _local_date_from_utc(iso_str, offset_str):
    """Converts a UTC "Z"-suffixed instant plus its sibling "<seconds>s"
    utcOffset field (e.g. interval.startTime + interval.startUtcOffset) into
    the local calendar date, per API-CONTRACT.md's "always local calendar
    dates" convention. Naive [:10] truncation of the UTC string is wrong
    whenever the instant falls near local midnight. Falls back to naive
    truncation if either value isn't in the expected shape.
    """
    if not isinstance(iso_str, str):
        return None
    try:
        instant = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_str[:10] if len(iso_str) >= 10 else None
    offset_seconds = 0
    if isinstance(offset_str, str) and offset_str.endswith("s"):
        offset_seconds = _to_number(offset_str[:-1]) or 0
    return (instant + timedelta(seconds=offset_seconds)).date().isoformat()


def _parse_duration_seconds(value):
    """Parses a duration string like "1813.200s" (as seen on
    exercise.activeDuration) into seconds, or None."""
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    return _to_number(value[:-1])


# ---------------------------------------------------------------------------
# Per-metric reshaping: raw store points -> API-CONTRACT.md shapes
# ---------------------------------------------------------------------------

def _reshape_steps(points):
    """dailyRollUp points are flat: civilStartTime/civilEndTime are
    {"date": {year, month, day}, "time": {}} and the count lives at
    steps.countSum."""
    totals = {}
    for p in points:
        d = _civil_value_to_date(p.get("civilStartTime")) or _civil_value_to_date(p.get("civilEndTime"))
        count = _to_number((p.get("steps") or {}).get("countSum"))
        if d is None or count is None:
            continue
        totals[d] = totals.get(d, 0) + count
    return [{"date": d, "value": v} for d, v in sorted(totals.items())]


def _reshape_heart_rate(points):
    """Approximates a daily "resting" value as the minimum bpm sample seen
    that day, since heart_rate is read as intraday samples, not a
    dedicated resting-heart-rate data type. Fields live under
    heartRate.sampleTime.civilTime.date (preferred, already local) or
    heartRate.sampleTime.physicalTime + .utcOffset (converted to local -
    see _local_date_from_utc), and heartRate.beatsPerMinute."""
    by_date = {}
    for p in points:
        heart_rate = p.get("heartRate")
        if not isinstance(heart_rate, dict):
            continue
        sample_time = heart_rate.get("sampleTime")
        if not isinstance(sample_time, dict):
            continue
        d = _civil_value_to_date(sample_time.get("civilTime")) or _local_date_from_utc(
            sample_time.get("physicalTime"), sample_time.get("utcOffset")
        )
        bpm = _to_number(heart_rate.get("beatsPerMinute"))
        if d is None or bpm is None:
            continue
        by_date.setdefault(d, []).append(bpm)
    return [{"date": d, "resting": min(values)} for d, values in sorted(by_date.items())]


def _reshape_sleep(points):
    """One record per sleep session, keyed by the local date the session
    ended on (sleep is fetched by civil_end_time). Fields live under
    sleep.interval (paired with sleep.interval.endUtcOffset/startUtcOffset -
    see _local_date_from_utc), sleep.summary (minutesAsleep), and
    sleep.summary.stagesSummary (a list of {type, minutes, count} - types
    seen live: AWAKE, LIGHT, DEEP, REM). Stage durations default to 0 for
    any stage type absent from stagesSummary."""
    records = []
    for p in points:
        sleep = p.get("sleep")
        if not isinstance(sleep, dict):
            continue
        interval = sleep.get("interval")
        if not isinstance(interval, dict):
            continue
        d = _local_date_from_utc(interval.get("endTime"), interval.get("endUtcOffset")) or _local_date_from_utc(
            interval.get("startTime"), interval.get("startUtcOffset")
        )
        if d is None:
            continue
        summary = sleep.get("summary") or {}
        duration = _to_number(summary.get("minutesAsleep")) or 0
        stages = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
        for stage in summary.get("stagesSummary") or []:
            if not isinstance(stage, dict):
                continue
            key = str(stage.get("type", "")).lower()
            if key in stages:
                stages[key] += _to_number(stage.get("minutes")) or 0
        records.append({"date": d, "duration_minutes": duration, "stages": stages})
    return sorted(records, key=lambda r: r["date"])


def _zone_minutes(zone_durations, key):
    seconds = _parse_duration_seconds((zone_durations or {}).get(key))
    return round(seconds / 60, 1) if seconds is not None else 0


def _format_instant(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _fill_missing_endpoint(start_time, end_time, duration_seconds):
    """A manually-logged exercise (no device telemetry) can carry only one
    side of interval.startTime/endTime. Derives the missing side from
    whichever instant is present plus activeDuration, so
    GET /fitness/api/metrics/heart_rate/samples still gets a real window to
    query - the device's HR sensor keeps recording independent of how the
    workout itself was logged. Leaves both None if duration is unknown or
    both endpoints are already missing (nothing to derive from)."""
    if duration_seconds is None:
        return start_time, end_time
    if start_time and not end_time:
        start_dt = _parse_datetime(start_time)
        if start_dt is not None:
            end_time = _format_instant(start_dt + timedelta(seconds=duration_seconds))
    elif end_time and not start_time:
        end_dt = _parse_datetime(end_time)
        if end_dt is not None:
            start_time = _format_instant(end_dt - timedelta(seconds=duration_seconds))
    return start_time, end_time


def _reshape_activity(points):
    """Fields live under exercise.interval (paired with
    exercise.interval.startUtcOffset/endUtcOffset - see
    _local_date_from_utc), exercise.exerciseType, and
    exercise.metricsSummary (caloriesKcal, plus - added for per-activity
    detail - distanceMillimeters, steps, averagePaceSecondsPerMeter,
    averageHeartRateBeatsPerMinute, activeZoneMinutes, and
    heartRateZoneDurations, a dict of "<seconds>s"-string durations per
    zone). Duration comes from exercise.activeDuration, a "<seconds>s"
    string. interval.startTime/endTime (raw UTC instants) are passed
    through as start_time/end_time so the frontend can query
    GET /fitness/api/metrics/heart_rate/samples for this exact window."""
    by_date = {}
    for p in points:
        exercise = p.get("exercise")
        if not isinstance(exercise, dict):
            continue
        interval = exercise.get("interval")
        if not isinstance(interval, dict):
            continue
        d = _local_date_from_utc(interval.get("startTime"), interval.get("startUtcOffset")) or _local_date_from_utc(
            interval.get("endTime"), interval.get("endUtcOffset")
        )
        if d is None:
            continue
        metrics_summary = exercise.get("metricsSummary") or {}
        duration_seconds = _parse_duration_seconds(exercise.get("activeDuration"))
        distance_mm = _to_number(metrics_summary.get("distanceMillimeters"))
        pace_sec_per_m = _to_number(metrics_summary.get("averagePaceSecondsPerMeter"))
        zone_durations = metrics_summary.get("heartRateZoneDurations")
        start_time, end_time = _fill_missing_endpoint(
            interval.get("startTime"), interval.get("endTime"), duration_seconds
        )
        record = {
            "type": exercise.get("exerciseType") or exercise.get("displayName"),
            "duration_minutes": round(duration_seconds / 60, 1) if duration_seconds is not None else None,
            "calories": _to_number(metrics_summary.get("caloriesKcal")),
            "start_time": start_time,
            "end_time": end_time,
            "distance_meters": round(distance_mm / 1000, 1) if distance_mm is not None else None,
            "steps": _to_number(metrics_summary.get("steps")),
            "average_pace_min_per_km": round(pace_sec_per_m * 1000 / 60, 2) if pace_sec_per_m is not None else None,
            "average_heart_rate": _to_number(metrics_summary.get("averageHeartRateBeatsPerMinute")),
            "active_zone_minutes": _to_number(metrics_summary.get("activeZoneMinutes")),
            "heart_rate_zones_minutes": {
                "light": _zone_minutes(zone_durations, "lightTime"),
                "moderate": _zone_minutes(zone_durations, "moderateTime"),
                "vigorous": _zone_minutes(zone_durations, "vigorousTime"),
                "peak": _zone_minutes(zone_durations, "peakTime"),
            },
        }
        by_date.setdefault(d, []).append(record)
    return [{"date": d, "exercises": ex} for d, ex in sorted(by_date.items())]


def _reshape_sample_series(points, nested_key, value_keys):
    """Shared extraction for sample-based metrics whose payload nests under
    `nested_key` with a `sampleTime` (civilTime preferred, else physicalTime
    + utcOffset) and a scalar reading under one of `value_keys` - the shape
    confirmed live for heart_rate. Returns {date: [values seen that day]}
    for the caller to aggregate.
    """
    by_date = {}
    for p in points:
        payload = p.get(nested_key)
        if not isinstance(payload, dict):
            continue
        sample_time = payload.get("sampleTime")
        if not isinstance(sample_time, dict):
            continue
        d = _civil_value_to_date(sample_time.get("civilTime")) or _local_date_from_utc(
            sample_time.get("physicalTime"), sample_time.get("utcOffset")
        )
        value = None
        for key in value_keys:
            if key in payload:
                value = _to_number(payload[key])
                break
        if d is None or value is None:
            continue
        by_date.setdefault(d, []).append(value)
    return by_date


def _reshape_spo2(points):
    by_date = _reshape_sample_series(points, "oxygenSaturation", ["percentage", "value"])
    return [{"date": d, "value": round(sum(v) / len(v), 1)} for d, v in sorted(by_date.items())]


def _reshape_hrv(points):
    by_date = _reshape_sample_series(
        points,
        "heartRateVariability",
        ["rootMeanSquareOfSuccessiveDifferencesMilliseconds", "rmssdMillis", "rmssd", "value"],
    )
    return [{"date": d, "value": round(sum(v) / len(v), 1)} for d, v in sorted(by_date.items())]


def _reshape_temperature(points):
    """The night's absolute reading (nightlyTemperatureCelsius) and the
    personal baseline it's compared against (baselineTemperatureCelsius) are
    stored separately; "variation from baseline" is their difference,
    computed here rather than read off any single field."""
    by_date = {}
    for p in points:
        payload = p.get("dailySleepTemperatureDerivations")
        if not isinstance(payload, dict):
            continue
        nightly = _to_number(payload.get("nightlyTemperatureCelsius"))
        baseline = _to_number(payload.get("baselineTemperatureCelsius"))
        d = _civil_value_to_date(payload)
        if d is None or nightly is None or baseline is None:
            continue
        by_date.setdefault(d, []).append(nightly - baseline)
    return [{"date": d, "value": round(sum(v) / len(v), 2)} for d, v in sorted(by_date.items())]


def _reshape_weight(points):
    by_date = _reshape_sample_series(points, "weight", ["weightGrams", "grams", "value"])

    def to_kg(v):
        # Guards against the value already being in kg rather than grams,
        # in case that guess is wrong - a plausible adult weight in grams
        # is in the tens of thousands; in kg it's well under 300.
        return round(v / 1000, 1) if v > 300 else v

    return [{"date": d, "value": to_kg(v[-1])} for d, v in sorted(by_date.items())]


def _reshape_breathing_rate(points):
    by_date = {}
    for p in points:
        payload = p.get("dailyRespiratoryRate")
        value = None
        d = None
        if isinstance(payload, dict):
            for key in ("breathsPerMinute", "value", "rate"):
                if key in payload:
                    value = _to_number(payload[key])
                    break
            d = _civil_value_to_date(payload)
            if d is None:
                sample_time = payload.get("sampleTime")
                if isinstance(sample_time, dict):
                    d = _civil_value_to_date(sample_time.get("civilTime")) or _local_date_from_utc(
                        sample_time.get("physicalTime"), sample_time.get("utcOffset")
                    )
        if d is None:
            d = _civil_value_to_date(p.get("civilStartTime")) or _civil_value_to_date(p.get("civilEndTime"))
        if d is None or value is None:
            continue
        by_date.setdefault(d, []).append(value)
    return [{"date": d, "value": round(sum(v) / len(v), 1)} for d, v in sorted(by_date.items())]


# Metrics that can be queried intraday via GET /fitness/api/metrics/{metric}/samples.
# Only heart_rate for now: it's the only sample-based metric a user would
# want windowed to an activity's exact start/end.
SAMPLE_METRICS = {
    "heart_rate": ("heartRate", "beatsPerMinute"),
}


def _parse_datetime(value):
    """Parses a "Z"-suffixed UTC instant (ISO 8601) into an aware datetime,
    or None if missing/invalid."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_RESHAPERS = {
    "steps": _reshape_steps,
    "heart_rate": _reshape_heart_rate,
    "sleep": _reshape_sleep,
    "activity": _reshape_activity,
    "spo2": _reshape_spo2,
    "hrv": _reshape_hrv,
    "breathing_rate": _reshape_breathing_rate,
    "temperature": _reshape_temperature,
    "weight": _reshape_weight,
}


def _metric_records(data_store, metric, from_d, to_d):
    raw_points = data_store.get("metrics", {}).get(metric, [])
    try:
        records = _RESHAPERS[metric](raw_points)
    except Exception:
        # Defense in depth alongside the reshapers' own isinstance guards: an
        # unforeseen payload shape degrades this metric to an empty list
        # instead of a request-killing 500.
        return []
    return [r for r in records if _in_range(r["date"], from_d, to_d)]


# ---------------------------------------------------------------------------
# Route handlers - each returns (status_code, body_dict) for the caller
# (backend/server.py's TaskHandler) to serialize and send.
# ---------------------------------------------------------------------------

def health():
    last_modified = None
    if store.DATA_PATH.exists():
        mtime = store.DATA_PATH.stat().st_mtime
        last_modified = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    return 200, {"status": "ok", "data_store_last_modified": last_modified}


def metrics_summary(query):
    from_d, to_d = _parse_range(query, DEFAULT_SUMMARY_RANGE_DAYS)
    data_store = store.load_store()
    metrics = {m: _metric_records(data_store, m, from_d, to_d) for m in KNOWN_METRICS}
    return 200, {"from": from_d.isoformat(), "to": to_d.isoformat(), "metrics": metrics}


def metric_detail(metric, query):
    if metric not in KNOWN_METRICS:
        return 404, {"error": f"unknown metric: {metric}"}
    from_d, to_d = _parse_range(query, DEFAULT_DETAIL_RANGE_DAYS)
    data_store = store.load_store()
    records = _metric_records(data_store, metric, from_d, to_d)
    return 200, {
        "metric": metric,
        "from": from_d.isoformat(),
        "to": to_d.isoformat(),
        "records": records,
    }


def metric_samples(metric, query):
    """GET /fitness/api/metrics/{metric}/samples?from=<ISO datetime>&to=<ISO
    datetime> - raw timestamped readings in [from, to], bypassing the daily
    bucketing _metric_records()/_RESHAPERS do. Built for the activity detail
    view: an exercise's own start_time/end_time (raw UTC instants, passed
    through by _reshape_activity) become this endpoint's from/to, so the
    frontend can chart heart rate for that exact workout window."""
    if metric not in SAMPLE_METRICS:
        return 404, {"error": f"metric not available intraday: {metric}"}
    from_str = query.get("from", [None])[0]
    to_str = query.get("to", [None])[0]
    from_dt = _parse_datetime(from_str)
    to_dt = _parse_datetime(to_str)
    if from_dt is None or to_dt is None:
        return 400, {"error": "from and to must both be ISO 8601 datetimes"}
    nested_key, value_key = SAMPLE_METRICS[metric]
    data_store = store.load_store()
    samples = []
    for p in data_store.get("metrics", {}).get(metric, []):
        payload = p.get(nested_key)
        if not isinstance(payload, dict):
            continue
        sample_time = payload.get("sampleTime")
        if not isinstance(sample_time, dict):
            continue
        instant = _parse_datetime(sample_time.get("physicalTime"))
        if instant is None or not (from_dt <= instant <= to_dt):
            continue
        value = _to_number(payload.get(value_key))
        if value is None:
            continue
        samples.append({"time": sample_time.get("physicalTime"), "value": value})
    samples.sort(key=lambda s: s["time"])
    return 200, {"metric": metric, "from": from_str, "to": to_str, "samples": samples}


def trigger_sync():
    try:
        results, errors = sync.sync_all()
    except Exception as exc:  # noqa: BLE001 - a failure before per-metric isolation (e.g. auth) - surfaced as a 502
        return 502, {"error": f"sync failed: {exc}"}
    body = {
        "status": "ok",
        "synced": results,
        "synced_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # One or more metrics failing (see sync.sync_all()) is still a 200 - the
    # metrics that did succeed were genuinely synced and saved: not
    # reporting that as an error. `errors` carries which metrics didn't.
    if errors:
        body["errors"] = errors
    return 200, body
