"""Thin wrapper over the Google Health API's read endpoints.

Endpoint shape, filter syntax, and pagination verified against the
open-source `ghealth` CLI (github.com/Google-Health-API/google-health-cli),
since developers.google.com wasn't reachable from this environment while
writing this. Re-check against the official REST reference
(developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints)
before relying on anything marked "unverified" below.

Each data type is either:
  - "civil"    - interval/session data filtered by local calendar time
                 (no UTC offset in the filter value), e.g. steps, sleep.
  - "physical" - sample data filtered by an absolute UTC instant
                 ("Z"-suffixed), e.g. heart_rate.

Most data types are readable via the plain `dataPoints` list endpoint, but
some devices never emit raw per-interval samples for a given data type -
only rolled-up daily totals. Confirmed live for `steps` on a Fitbit Air:
`dataPoints` and `dataPoints:reconcile` both returned zero results for a
week with real activity, while `dataPoints:dailyRollUp` returned real daily
totals for the same range. Data types with this behavior are marked
`"read_method": "daily_rollup"` below and go through `_list_via_daily_rollup`
instead of the plain list endpoint.
"""

from datetime import datetime, timedelta

import http_client

BASE_URL = "https://health.googleapis.com/v4"

# Our metric name -> Google Health API data type details.
DATA_TYPES = {
    "steps": {
        "api_id": "steps",
        # This device only emits steps as daily-rollup totals, never as raw
        # dataPoints - see the module docstring. filter_field/time_kind are
        # unused for daily_rollup but kept for reference/consistency.
        "filter_field": "steps.interval.civil_start_time",
        "time_kind": "civil",
        "page_size": 10000,
        "read_method": "daily_rollup",
    },
    "heart_rate": {
        "api_id": "heart-rate",
        "filter_field": "heart_rate.sample_time.physical_time",
        "time_kind": "physical",
        "page_size": 10000,
    },
    "sleep": {
        "api_id": "sleep",
        # sleep is the one interval type that filters on civil_end_time
        # instead of civil_start_time.
        "filter_field": "sleep.interval.civil_end_time",
        "time_kind": "civil",
        "page_size": 25,
    },
    "activity": {
        # Google Health API's data type ID for exercise/workout sessions.
        "api_id": "exercise",
        "filter_field": "exercise.interval.civil_start_time",
        "time_kind": "civil",
        "page_size": 25,
    },
    # --- Added 2026-08-18, NOT YET VERIFIED LIVE ---------------------------
    # api_id/filter_field for these five are inferred from the `ghealth` CLI's
    # type registry (pkg/types/registry.go on GitHub - developers.google.com
    # is unreachable from this environment, same issue noted for the four
    # types above), following the same "{filter_name}.{sample_time|interval}.
    # {physical_time|civil_start_time}" pattern the four confirmed types use,
    # but NOT cross-checked against a real API response the way steps/
    # heart_rate/sleep/activity were. Run `python cli.py sync` and inspect
    # backend/data/health_data.json for these metrics before trusting the
    # field names in server.py's reshapers - see docs/backend-architecture.md.
    "spo2": {
        # ghealth registry: id "oxygen-saturation", sample-based (physical time).
        "api_id": "oxygen-saturation",
        "filter_field": "oxygen_saturation.sample_time.physical_time",
        "time_kind": "physical",
        "page_size": 10000,
    },
    "hrv": {
        # ghealth registry: id "heart-rate-variability", sample-based (physical time).
        "api_id": "heart-rate-variability",
        "filter_field": "heart_rate_variability.sample_time.physical_time",
        "time_kind": "physical",
        "page_size": 10000,
    },
    "breathing_rate": {
        # ghealth registry: id "daily-respiratory-rate". Two things confirmed
        # live 2026-08-19: (1) dailyRollUp is explicitly NOT supported for
        # this type (400, UNSUPPORTED_DATA_TYPE_ACTION - "the following
        # actions are supported: list, reconcile") - list is correct, unlike
        # steps' quirk which needed dailyRollUp instead. (2) the original
        # filter_field guess, "daily_respiratory_rate.interval.civil_start_
        # time", is flatly rejected: "Member ... is not supported for
        # filtering" - this type has no `interval` sub-message. Re-checked
        # the ghealth registry source directly (not just the earlier
        # secondary summary) for its TimeField-to-filter-path mapping: a
        # "daily" TimeField (which is what this type has, vs. "sample" for
        # the four physical-time types above) maps to a bare `.date` suffix,
        # not `.interval.civil_start_time`. Switched to that - see the
        # "civil_date" time_kind in _build_filter(). Still UNVERIFIED
        # against a live response (this is a third guess after two
        # confirmed-wrong ones) - if this also 400s, the error should at
        # least point at what actually is expected next.
        "api_id": "daily-respiratory-rate",
        "filter_field": "daily_respiratory_rate.date",
        "time_kind": "civil_date",
        "page_size": 10000,
    },
    "temperature": {
        # Issue #30: a live sync against `core-body-temperature` (the original
        # guess) returned 0 data points while every other metric returned real
        # data - not an error, so the request itself was valid, but this
        # Fitbit device apparently never emits raw core-body-temperature
        # samples. This is the same "device doesn't populate this shape"
        # quirk `steps` had (see the module docstring), except here the fix
        # isn't a different read_method for the same data type - it's a
        # different data type. Fitbit's actual temperature feature is
        # nightly "skin temperature variation" (deviation from a personal
        # baseline), which the ghealth CLI registry lists separately as
        # "daily-sleep-temperature-derivations" (TimeField "daily", alongside
        # daily-respiratory-rate etc.) - not "core-body-temperature" at all.
        # Switched to that, following breathing_rate's confirmed "daily"
        # TimeField -> bare ".date" filter pattern. Still UNVERIFIED against
        # a live response - see server.py's _reshape_temperature for the
        # value field name, which is a fresh guess.
        "api_id": "daily-sleep-temperature-derivations",
        "filter_field": "daily_sleep_temperature_derivations.date",
        "time_kind": "civil_date",
        "page_size": 10000,
    },
    "weight": {
        # ghealth registry: id "weight", sample-based (physical time).
        "api_id": "weight",
        "filter_field": "weight.sample_time.physical_time",
        "time_kind": "physical",
        "page_size": 10000,
    },
}


def _build_filter(filter_field, time_kind, from_date, to_date):
    """Build an AIP-160-style filter string covering [from_date, to_date]
    (inclusive), as a half-open interval on the underlying time field.
    """
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

    if time_kind == "civil":
        start_str = start.strftime("%Y-%m-%dT00:00:00")
        end_str = end.strftime("%Y-%m-%dT00:00:00")
    elif time_kind == "civil_date":
        # UNVERIFIED (see breathing_rate's DATA_TYPES entry): a bare
        # "YYYY-MM-DD" value, not a datetime, for data types whose filter
        # field is a plain google.type.Date (e.g. "{name}.date") rather than
        # an interval/sample_time sub-message.
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
    else:
        start_str = start.strftime("%Y-%m-%dT00:00:00Z")
        end_str = end.strftime("%Y-%m-%dT00:00:00Z")

    return f'{filter_field} >= "{start_str}" AND {filter_field} < "{end_str}"'


def _civil_date(date_str):
    """Build a CivilDateTime "date" object from a "YYYY-MM-DD" string, for
    dailyRollUp's range.start/range.end (verified against `ghealth`'s
    buildDailyRollupBody: {"date": {"year", "month", "day"}}, no "time"
    sub-object needed).
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


def _list_via_daily_rollup(api_id, from_date, to_date, access_token):
    """Fetch daily-rollup totals for `api_id` in [from_date, to_date]
    (inclusive), following pagination until exhausted.
    """
    url = f"{BASE_URL}/users/me/dataTypes/{api_id}/dataPoints:dailyRollUp"
    headers = {"Authorization": f"Bearer {access_token}"}
    end_date = (datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    all_points = []
    page_token = None
    while True:
        body = {
            "range": {"start": _civil_date(from_date), "end": _civil_date(end_date)},
            # Documented as optional (defaults to 1) but the live API 400s
            # if it's omitted, per `ghealth`'s buildDailyRollupBody - always
            # send it explicitly.
            "windowSizeDays": 1,
        }
        if page_token:
            body["pageToken"] = page_token

        response = http_client.post_json(url, body, headers=headers)
        all_points.extend(response.get("rollupDataPoints", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return all_points


def list_data_points(metric, from_date, to_date, access_token):
    """Fetch every raw data point for `metric` in [from_date, to_date]
    (both "YYYY-MM-DD"), following pagination until exhausted.
    """
    if metric not in DATA_TYPES:
        raise ValueError(f"unknown metric: {metric}")
    spec = DATA_TYPES[metric]

    if spec.get("read_method") == "daily_rollup":
        return _list_via_daily_rollup(spec["api_id"], from_date, to_date, access_token)

    url = f"{BASE_URL}/users/me/dataTypes/{spec['api_id']}/dataPoints"
    headers = {"Authorization": f"Bearer {access_token}"}
    filter_str = _build_filter(spec["filter_field"], spec["time_kind"], from_date, to_date)

    all_points = []
    page_token = None
    while True:
        params = {"filter": filter_str, "pageSize": spec["page_size"]}
        if page_token:
            params["pageToken"] = page_token

        response = http_client.get_json(url, params=params, headers=headers)
        all_points.extend(response.get("dataPoints", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return all_points
