# Fitness

`/fitness` is a ported copy of the standalone
[`personal_health`](https://github.com/agallagher55/personal_health) project:
a personal health dashboard that pulls data from the Google Health API
(steps, heart rate, sleep, SpO2, HRV, breathing rate, temperature variation,
weight, activity/exercise sessions), caches it locally, and charts it in the
browser.

Unlike `/finance` (still a planning-stage stub, see `finance/`), this is a
real, working feature — same code as the standalone app, just folded into
this repo's single stdlib `http.server` process and namespaced under
`/fitness` instead of running as its own server.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it's wired into the rest of
this app, [`API-CONTRACT.md`](API-CONTRACT.md) for the `/fitness/api/*`
response shapes, [`google_health.md`](google_health.md) for the one-time
Google Cloud/OAuth setup required before syncing any real data, and
[`VISITOR-SIGNIN-PLAN.md`](VISITOR-SIGNIN-PLAN.md) for the not-yet-built
plan to let visitors sign in with their own Google account.

## Local setup (one-time)

1. Follow [`google_health.md`](google_health.md) to create a Google Cloud
   project, OAuth client, and pick scopes.
2. `cp backend/fitness/config.json.example backend/fitness/config.json` and
   fill in `client_id`/`client_secret` from step 1. This file is
   git-ignored — never commit it.
3. From `backend/fitness/`, run `python cli.py auth` to run the OAuth flow
   once and save tokens into `backend/fitness/config.json`. (This briefly
   binds port 8000 for the OAuth redirect — don't run it while the main app
   server is also bound to that port.)
4. Start the main app as usual (`python3 backend/server.py` from the repo
   root) and open `/fitness`. Click **Sync now** on any page (or run
   `python cli.py sync` from `backend/fitness/`) to pull data.

Data lands in `data/fitness/health_data.json`, alongside this app's other
`data/*.json` files and covered by the same Render persistent disk mount —
also git-ignored, since it holds real personal health data.

## What changed from the standalone app

Only the HTTP glue and file locations — the OAuth flow, Google Health API
client, sync logic, storage format, reshaping logic, and every frontend
page/script are unchanged:

| | Standalone `personal_health` | Here |
|---|---|---|
| Backend entry point | `backend/cli.py serve` (its own `ThreadingHTTPServer`) | `backend/server.py` (this app's existing `TaskHandler`, extended) |
| Backend modules | `backend/*.py`, flat imports | `backend/fitness/*.py`, same flat imports, own directory |
| Query API base path | `/api/*` | `/fitness/api/*` |
| Config | `backend/config.json` | `backend/fitness/config.json` |
| Data store | `backend/data/health_data.json` | `data/fitness/health_data.json` |
| Frontend pages | `frontend/index.html`, `frontend/pages/*.html` | `html/fitness/index.html`, `html/fitness/pages/*.html` |
| Frontend assets | `frontend/css/`, `frontend/js/` | `static/fitness/css/`, `static/fitness/js/` |
| Page URLs | `frontend/pages/steps.html` (file path) | `/fitness/steps` (clean route, see `routes.md`) |

The `KNOWN_METRICS`/`_reshape_*` functions in `backend/fitness/api.py` still
carry the same confidence notes as the original `server.py` — `spo2`,
`hrv`, `breathing_rate`, and `weight` are confirmed live against a real
account (2026-08-19/20); `temperature` is still unverified pending a real
synced data point.
