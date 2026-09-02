# Fitness Query API Contract

The contract between `static/fitness/js/api.js` and
`backend/fitness/api.py`'s handlers, mounted by `backend/server.py` under
`/fitness/api/*`. Ported from the standalone `personal_health` project's
`docs/api-contract.md` — only the base path changed (`/api/*` →
`/fitness/api/*`); every response shape below is unchanged.

All endpoints return `Content-Type: application/json` and read from the
signed-in visitor's own `data/fitness/users/<user_id>/health_data.json` via
`store.py`. None of them call the Google Health API directly except
`POST /fitness/api/sync`.

## Authentication

Every endpoint below except `GET /fitness/api/me` requires a valid
`fitness_session` cookie, set by signing in at `/fitness/login` (see
`VISITOR-SIGNIN-PLAN.md`). A request without one gets:

**Response `401`:**
```json
{ "error": "sign-in required", "reauth_url": "/fitness/auth/start" }
```

`reauth_url` is also returned on a `401` from `POST /fitness/api/sync`
when a signed-in visitor's Google refresh token has expired or been
revoked (see `ReauthRequired` in `backend/fitness/auth.py`) — the frontend
sends the browser there in both cases rather than showing an error the
visitor can't act on.

## `GET /fitness/api/me`

Who the current session belongs to. The one endpoint that works whether or
not the visitor is signed in, so the frontend can render its header/account
chip without treating "signed out" as an error.

**Response `200`, signed in:**
```json
{ "signed_in": true, "email": "visitor@example.com", "name": "Visitor Name", "has_tokens": true }
```

**Response `200`, signed out:**
```json
{ "signed_in": false }
```

## Conventions

- Dates are `YYYY-MM-DD` strings, always local calendar dates (no timezone
  conversion — single-user and single-timezone is assumed).
- Date range params: `from` and `to`, both inclusive. If omitted, defaults
  are endpoint-specific (noted below).
- All successful responses are `200` with a JSON body. No pagination —
  ranges are expected to be small (days/weeks), not years.
- Errors return a non-2xx status and a JSON body: `{ "error": "message" }`.

## `GET /fitness/api/health`

Liveness check. Confirms the server is up and can read the data store.

**Response `200`:**
```json
{ "status": "ok", "data_store_last_modified": "2026-08-17T09:12:00Z" }
```

## `GET /fitness/api/metrics`

Dashboard-level summary across all metrics for a date range — the single
call the dashboard page makes on load. Default range: last 7 days if
`from`/`to` omitted.

**Request:** `GET /fitness/api/metrics?from=2026-08-11&to=2026-08-17`

**Response `200`:**
```json
{
  "from": "2026-08-11",
  "to": "2026-08-17",
  "metrics": {
    "steps": [
      { "date": "2026-08-11", "value": 8421 },
      { "date": "2026-08-12", "value": 6310 }
    ],
    "heart_rate": [
      { "date": "2026-08-11", "resting": 58 },
      { "date": "2026-08-12", "resting": 60 }
    ],
    "sleep": [
      { "date": "2026-08-11", "duration_minutes": 431, "stages": { "light": 210, "deep": 90, "rem": 100, "awake": 31 } }
    ],
    "activity": [
      { "date": "2026-08-11", "exercises": [ { "type": "walk", "duration_minutes": 32, "calories": 140, "start_time": "2026-08-11T20:00:04.400Z", "end_time": "2026-08-11T20:30:17.600Z", "distance_meters": 2105.4, "steps": 2885, "average_pace_min_per_km": 14.35, "average_heart_rate": 94, "active_zone_minutes": 2, "heart_rate_zones_minutes": { "light": 28.0, "moderate": 2.0, "vigorous": 0, "peak": 0 } } ] }
    ],
    "spo2": [ { "date": "2026-08-11", "value": 97.0 } ],
    "hrv": [ { "date": "2026-08-11", "value": 45.0 } ],
    "breathing_rate": [ { "date": "2026-08-11", "value": 15.2 } ],
    "temperature": [ { "date": "2026-08-11", "value": 36.8 } ],
    "weight": [ { "date": "2026-08-11", "value": 81.5 } ]
  }
}
```

`spo2`/`hrv`/`breathing_rate`/`temperature`/`weight` share one
`{ date, value }` shape (a same-day average, except `weight`, which takes
the last same-day reading). `spo2`, `hrv`, `breathing_rate`, and `weight`
are confirmed live against a real account; `temperature` is still
unverified (see `ARCHITECTURE.md` §6).

Any metric with no records in range is present as an empty array
(`"heart_rate": []`), not omitted — keeps the frontend's widget code from
having to check for missing keys.

Each `activity` exercise carries more than the dashboard timeline shows,
for the per-activity detail view: `start_time`/`end_time` are raw UTC
instants (unlike every other metric's `date`, a local calendar date), and
`distance_meters`, `steps`, `average_pace_min_per_km`, `average_heart_rate`,
`active_zone_minutes`, `heart_rate_zones_minutes` (`{ light, moderate,
vigorous, peak }`, in minutes) come straight from Google's per-workout
`exercise.metricsSummary`. Any of these may be `null`/`0` if the
device/workout type didn't record it.

## `GET /fitness/api/metrics/{metric}`

Single-metric detail, for per-metric pages (e.g. `/fitness/heart-rate`)
that want more than the dashboard summary gives. Default range: last 30
days if omitted.

`{metric}` is one of: `steps`, `heart_rate`, `sleep`, `activity`, `spo2`,
`hrv`, `breathing_rate`, `temperature`, `weight` (keep in sync with
`backend/fitness/api.py`'s `KNOWN_METRICS`).

**Request:** `GET /fitness/api/metrics/heart_rate?from=2026-07-18&to=2026-08-17`

**Response `200`:**
```json
{
  "metric": "heart_rate",
  "from": "2026-07-18",
  "to": "2026-08-17",
  "records": [
    { "date": "2026-08-11", "resting": 58 },
    { "date": "2026-08-12", "resting": 60 }
  ]
}
```

**Response `404`** (unknown metric name):
```json
{ "error": "unknown metric: heartrate" }
```

## `GET /fitness/api/metrics/{metric}/samples`

Raw timestamped readings in a datetime window, bypassing the daily
bucketing every other endpoint does. Built for the activity detail view:
clicking an exercise in the activity pane queries this with that exercise's
own `start_time`/`end_time` to chart heart rate across exactly that
workout.

`{metric}` is currently only `heart_rate` (keep in sync with
`backend/fitness/api.py`'s `SAMPLE_METRICS`) — `steps` can't get the same
treatment, since this device only ever emits daily totals, never intraday
samples.

**Request:** `GET /fitness/api/metrics/heart_rate/samples?from=2026-08-11T20:00:04.400Z&to=2026-08-11T20:30:17.600Z`

`from`/`to` are both required and must be full ISO 8601 UTC instants
(`Z`-suffixed), not the bare `YYYY-MM-DD` dates every other endpoint uses.

**Response `200`:**
```json
{
  "metric": "heart_rate",
  "from": "2026-08-11T20:00:04.400Z",
  "to": "2026-08-11T20:30:17.600Z",
  "samples": [
    { "time": "2026-08-11T20:05:12Z", "value": 96 },
    { "time": "2026-08-11T20:06:14Z", "value": 101 }
  ]
}
```
An empty `samples` array is a valid response, not an error.

**Response `400`** (missing/unparseable `from`/`to`):
```json
{ "error": "from and to must both be ISO 8601 datetimes" }
```

**Response `404`** (metric isn't sample-based):
```json
{ "error": "metric not available intraday: steps" }
```

## `POST /fitness/api/sync`

Triggers an on-demand pull from the Google Health API into the JSON data
store, backing the "Sync now" button on every page. Synchronous: the
request blocks until the sync finishes.

**Request:** `POST /fitness/api/sync` (empty body)

**Response `200`:**
```json
{
  "status": "ok",
  "synced": { "steps": 7, "heart_rate": 7, "sleep": 6, "activity": 3 },
  "synced_at": "2026-08-17T09:12:00Z"
}
```

**Response `200`, one or more metrics failed** (the metrics that succeeded
were genuinely synced and saved, so this is still `200`, not an error —
`errors` names which metrics didn't; that metric's `last_synced` isn't
advanced, so the same range is retried next sync):
```json
{
  "status": "ok",
  "synced": { "steps": 7, "heart_rate": 7, "sleep": 6, "activity": 3, "spo2": 5 },
  "errors": { "breathing_rate": "400 Client Error: Bad Request for url: ..." },
  "synced_at": "2026-08-17T09:12:00Z"
}
```

**Response `401`** (no stored Google credentials, or the refresh token was
rejected - see `ReauthRequired` in `backend/fitness/auth.py`):
```json
{ "error": "Google rejected the stored refresh token", "reauth_url": "/fitness/auth/start" }
```

**Response `409`** (a sync for this visitor is already running - a
double-clicked "Sync now" is turned away rather than interleaving two
read-modify-write cycles on the same store file):
```json
{ "error": "a sync is already running for this account" }
```

**Response `502`** (the sync couldn't start at all, for a reason other than
`ReauthRequired`):
```json
{ "error": "sync failed: <reason>" }
```

## Not implemented

- Write endpoints (this only reads from the Google Health API and re-serves
  locally; no editing stored data through the API).
- Pagination/streaming for large ranges.
