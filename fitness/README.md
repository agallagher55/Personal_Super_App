# Fitness

`/fitness` is a personal health dashboard: any allowed visitor signs in
with their own Google account and sees their own Google Health data (steps,
heart rate, sleep, SpO2, HRV, breathing rate, temperature variation,
weight, activity/exercise sessions), synced from the Google Health API,
cached locally per visitor, and charted in the browser. It started as a
ported copy of the standalone
[`personal_health`](https://github.com/agallagher55/personal_health)
project (a single-user app); per-visitor sign-in was added on top per
[`VISITOR-SIGNIN-PLAN.md`](VISITOR-SIGNIN-PLAN.md).

Unlike `/finance` (still a planning-stage stub, see `finance/`), this is a
real, working feature, folded into this repo's single stdlib `http.server`
process and namespaced under `/fitness` instead of running as its own
server.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it's wired into the rest of
this app, [`API-CONTRACT.md`](API-CONTRACT.md) for the `/fitness/api/*`
response shapes, [`google_health.md`](google_health.md) for the one-time
Google Cloud/OAuth setup required before anyone can sign in, and
[`VISITOR-SIGNIN-PLAN.md`](VISITOR-SIGNIN-PLAN.md) for the sign-in design
itself.

## Local setup (one-time)

1. Follow [`google_health.md`](google_health.md) to create a Google Cloud
   project, OAuth client, and pick scopes. Add
   `http://localhost:8000/fitness/auth/callback` as an Authorized redirect
   URI.
2. Either `cp backend/fitness/config.json.example backend/fitness/config.json`
   and fill in `client_id`/`client_secret` from step 1 (git-ignored — never
   commit it), or set the `FITNESS_GOOGLE_CLIENT_ID`/
   `FITNESS_GOOGLE_CLIENT_SECRET`/`FITNESS_OAUTH_REDIRECT_URI` environment
   variables instead (env vars win if both are set; required on Render,
   since `backend/fitness/config.json` is never present in a deploy — see
   `DEPLOYMENT.md`).
3. Set `FITNESS_OWNER_EMAIL` (or `FITNESS_ALLOWED_EMAILS`, or
   `data/fitness/allowed_users.json`) to your own Google account's email —
   sign-in fails closed with nothing configured. See
   `VISITOR-SIGNIN-PLAN.md` §6.
4. Start the main app (`python3 backend/server.py` from the repo root),
   open `/fitness`, and sign in at `/fitness/login`. The dashboard
   auto-syncs once on first load; click **Sync now** on any page afterward
   (or run `python cli.py sync` from `backend/fitness/`) to pull again.
5. If you're bringing forward data from before sign-in existed
   (`data/fitness/health_data.json`), run `python cli.py migrate` from
   `backend/fitness/` after signing in once — see that command's own
   `--help` output for what it moves.

Data lands in `data/fitness/users/<user_id>/health_data.json`, one
directory per visitor, alongside this app's other `data/*.json` files and
covered by the same Render persistent disk mount — the whole
`data/fitness/` tree is git-ignored, since it holds real personal health
data and OAuth tokens.

## What changed from the standalone app

The OAuth flow (now browser-driven instead of a CLI step), Google Health
API client, sync logic, storage format, reshaping logic, and every frontend
page/script's actual behavior are otherwise unchanged from the ported
`personal_health` code:

| | Standalone `personal_health` | Here |
|---|---|---|
| Backend entry point | `backend/cli.py serve` (its own `ThreadingHTTPServer`) | `backend/server.py` (this app's existing `TaskHandler`, extended) |
| Backend modules | `backend/*.py`, flat imports | `backend/fitness/*.py`, same flat imports, own directory |
| Sign-in | `cli.py auth` (CLI, opens a browser, binds port 8000) | Browser flow at `/fitness/login` → `/fitness/auth/start` → Google → `/fitness/auth/callback` |
| Query API base path | `/api/*` | `/fitness/api/*`, session-gated except `/fitness/api/me` |
| Config | `backend/config.json` (client + tokens) | `backend/fitness/config.json` (client only; env vars override) |
| Token/data store | `backend/config.json` + `backend/data/health_data.json`, one shared file each | `data/fitness/users/<user_id>/{tokens,user,health_data}.json`, one set per visitor |
| Frontend pages | `frontend/index.html`, `frontend/pages/*.html` | `html/fitness/index.html`, `html/fitness/pages/*.html`, `html/fitness/login.html` |
| Frontend assets | `frontend/css/`, `frontend/js/` | `static/fitness/css/`, `static/fitness/js/` |
| Page URLs | `frontend/pages/steps.html` (file path) | `/fitness/steps` (clean route, see `routes.md`) |

The `KNOWN_METRICS`/`_reshape_*` functions in `backend/fitness/api.py` still
carry the same confidence notes as the original `server.py` — `spo2`,
`hrv`, `breathing_rate`, and `weight` are confirmed live against a real
account (2026-08-19/20); `temperature` is still unverified pending a real
synced data point.
