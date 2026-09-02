# Deployment

## Why not GitHub Pages

GitHub Pages only serves static files — there's no server-side code and
no writable filesystem. This app needs both:

- `POST /tasks/update` (saving notes/status/priority changes)
- `POST /tasks/delete` (deleting a task)
- `POST /tasks/new` (creating a task)
- reading and writing `data/sections.json`, `data/tasks.json`, and
  `data/tags.json` on disk as the datastore

All of that is handled by `backend/server.py`, a small Python
`http.server`-based server. Pages can't run it, so deploying there
would leave you with a read-only snapshot of the task list — every
save, delete, and new-task action would fail.

## Deploying to Render

This repo includes a `render.yaml` [Blueprint](https://render.com/docs/blueprint-spec)
that provisions everything needed to run the real app, backend
included.

### One-time setup

1. Sign in to [Render](https://render.com) (a GitHub login works) and
   make sure your GitHub account/org is connected.
2. From the Render dashboard, click **New > Blueprint**.
3. Select this repository. Render finds `render.yaml` at the repo
   root automatically and shows a preview of what it'll create:
   - a **web service** named `personal-super-app` on the free plan,
     running `python3 backend/server.py`
   - a **1GB persistent disk** mounted at `data/` inside the service
4. Click **Apply** to create the service. Render builds and starts it
   using the blueprint's config — no manual build/start command entry
   needed.

### What the persistent disk does

`data/sections.json`, `data/tasks.json`, and `data/tags.json` are the
only datastore this app has, and they're plain files on disk. Render's
ephemeral filesystem is wiped on every deploy, so without a disk every
deploy would reset your tasks back to whatever's committed in the repo.

The disk in `render.yaml` is mounted directly over `data/`. On the
**first** deploy, Render copies whatever's already at that path (the
three JSON files committed to the repo) onto the new disk to seed it.
After that, all reads/writes from `backend/server.py` go to the
persistent disk, so edits made through the running app survive
redeploys, restarts, and code pushes.

### Port binding

Render assigns a port at runtime via the `$PORT` environment variable
and expects the service to bind to it. `backend/server.py` already
does this (`PORT = int(os.environ.get('PORT', 8000))`), falling back
to `8000` for local development where `$PORT` isn't set — no
config needed on Render's side beyond the blueprint itself.

### After deploying

Render gives the service a URL like
`https://personal-super-app.onrender.com`. Use it in place of
`http://localhost:8000` everywhere — the app behaves identically
(same routes, same save/delete/new-task flows), just served from
Render instead of your machine.

### Redeploying

Render redeploys automatically on every push to the connected
branch (`main` by default) once the Blueprint is created. Manual
redeploys are available from the service's page in the Render
dashboard if you need to trigger one without a new commit.

### Free plan caveats

The free plan spins the service down after a period of inactivity;
the next request after that wakes it back up, which takes a few
seconds. This app is a personal task tracker, so that's a reasonable
tradeoff for zero cost. Upgrade the `plan` in `render.yaml` if you
want the service to stay warm.

## Fitness sign-in environment variables

`backend/fitness/config.json` is **not** on the persistent disk — the disk
mount in `render.yaml` covers `data/` only, and `config.json` is
git-ignored — so a deployed service has no way to read it. The
`FITNESS_GOOGLE_*` environment variables are therefore the only way `/fitness`
sign-in works on Render at all; `config.json` is a local-dev convenience,
not something the deploy can fall back to.

`render.yaml` declares these with `sync: false`, which tells Render to
prompt for each value in the dashboard when the Blueprint is applied and
never store them in the repo:

| Variable | Required | What it's for |
|---|---|---|
| `FITNESS_GOOGLE_CLIENT_ID` | Yes | OAuth client id from `fitness/google_health.md`. |
| `FITNESS_GOOGLE_CLIENT_SECRET` | Yes | OAuth client secret from the same setup. |
| `FITNESS_OAUTH_REDIRECT_URI` | Yes | `https://<your-service>.onrender.com/fitness/auth/callback` — must exactly match an Authorized redirect URI on the OAuth client in Google Cloud Console. |
| `FITNESS_SESSION_SECRET` | Recommended | HMAC key for signed session/state cookies. If unset, one is generated on first use and written to `data/fitness/session_secret` on the persistent disk — fine on Render (survives redeploys), but setting it explicitly means you control when it rotates (rotating logs every visitor out). |
| `FITNESS_OWNER_EMAIL` | One of these three | Simplest allowlist: exactly one email may sign in. |
| `FITNESS_ALLOWED_EMAILS` | | Comma-separated list of emails, takes precedence over `FITNESS_OWNER_EMAIL` and `data/fitness/allowed_users.json`. |
| `FITNESS_OAUTH_SCOPES` | No | Space-separated override of the default OAuth scopes; only needed if you're changing what the app requests. |

Sign-in fails closed: with none of `FITNESS_ALLOWED_EMAILS`,
`data/fitness/allowed_users.json`, or `FITNESS_OWNER_EMAIL` set, nobody can
sign in (`?error=not_configured`). See `fitness/VISITOR-SIGNIN-PLAN.md` §6
for the full allowlist resolution order, and `fitness/google_health.md` §9
for the 7-day refresh-token expiry every visitor on an unverified
("Testing") OAuth client will hit about once a week.
