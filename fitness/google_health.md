# Google Health API Setup Guide

Everything needed to get from "nothing set up" to "the fitness backend can
pull data" for the Google Health API — the account setup, Google Cloud
project, and OAuth credentials. Do this once, before running `Sync now` (or
`backend/fitness/cli.py sync`) for the first time. Ported from the
standalone `personal_health` project's `google_health.md`, with paths
updated for where things live in this repo (see `README.md`'s "what
changed" table).

This is written from Google's own setup docs
(`developers.google.com/health/setup`, `/get-started`,
`/developer-checklist`) plus their Fitbit migration docs. Some details
(exact console screens/button labels) may drift as Google updates the
console — if a step doesn't match what you see, treat this doc as a
starting point and follow the console's own prompts.

## 0. Background: why OAuth, and why a Google account for Fitbit

- The Google Health API is the successor to the Fitbit Web API. It
  authenticates entirely through **Google OAuth 2.0**, not the old
  Fitbit-specific auth.
- **Fitbit accounts now need to be linked to (or migrated onto) a Google
  Account** to use the Google Health app/API. If your Fitbit login isn't
  already a Google account, you'll be prompted to move it — see [Google's
  guide on moving a Fitbit account to a Google
  Account](https://support.google.com/googlehealth/answer/14237024). You
  **cannot** use a Google Workspace account for this — use a personal
  Google account.
- The legacy Fitbit Web API is being shut down (Google has announced a
  September 2026 turn-down).

## 1. Move/link your Fitbit account to a Google Account

1. If you don't already sign into Fitbit with a Google account, follow
   Google's [Fitbit-to-Google-Account migration
   flow](https://support.google.com/googlehealth/answer/14237024) first.
2. Make sure your Fitbit device is syncing normally under that
   Google-linked account in the Fitbit app before moving on — the Google
   Health API only surfaces data your account is already collecting.
3. Optionally check the [Google Health app connected-devices
   settings](https://support.google.com/fitbit/answer/14236613) to confirm
   the device shows up there.

## 2. Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   sign in with the **same Google account** your Fitbit data lives under.
2. Create a new project (or reuse an existing personal one).
3. From **APIs & Services > Library**, search for **"Google Health API"**
   and enable it for the project.

## 3. Configure the OAuth consent screen

1. Go to **APIs & Services > OAuth consent screen** (Google may label this
   "Google Auth Platform" / prompt "Get Started" if it's the first time in
   this project).
2. Fill in the required app info (app name, support email, developer
   contact email). For a personal project, this can be minimal.
3. Choose **External** user type unless you have a Workspace org you
   specifically want to scope this to.
4. Add the scopes this project needs (see step 5 below) — or add them
   later when creating credentials; either order works.
5. Under **Test users**, add your own Google account email. Newly created
   OAuth clients start unverified, capped at 100 users, and only addresses
   on the Test users list can authorize until the app goes through
   Google's verification process. Staying in unverified/testing mode
   indefinitely with yourself as the only test user is fine for a personal
   project.

## 4. Create an OAuth 2.0 Client ID

1. Go to **APIs & Services > Credentials**.
2. Click **+ Create Credentials > OAuth client ID**.
3. When asked **"Where are you calling from?"**, choose **Web Server**.
4. Set **Authorized redirect URIs**. Add both:
   - `http://localhost:8000/fitness/auth/callback` (matches
     `backend/fitness/config.json.example`'s default — the browser sign-in
     flow at `/fitness/login` catches this locally)
   - `https://personal-super-app.onrender.com/fitness/auth/callback` (or
     your own Render service URL, if different — see `DEPLOYMENT.md`)

   Also add `https://developers.google.com/oauthplayground` if you want to
   sanity-check the setup via step 6 first; it can be removed again once
   you have a working sign-in.
5. Once created, **download the credentials JSON** (or copy the **Client
   ID** and **Client Secret** shown). You'll paste these into
   `backend/fitness/config.json` — **this file must never be committed**;
   see step 7 — or into the `FITNESS_GOOGLE_CLIENT_ID`/
   `FITNESS_GOOGLE_CLIENT_SECRET` environment variables, which is the only
   option on Render (see step 7 and `DEPLOYMENT.md`).

## 5. Pick the scopes we need

Google Health API scopes take the form
`https://www.googleapis.com/auth/googlehealth.<category>.<readonly|writeonly>`.
This project only needs **read** access, plus three standard OpenID Connect
scopes so sign-in can identify *who's* signing in:

| Data we want | Scope |
|---|---|
| The visitor's Google account id/email/name (for sign-in, not health data) | `openid`, `email`, `profile` |
| Steps, distance, floors, altitude (activity) | `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly` |
| Sleep | `https://www.googleapis.com/auth/googlehealth.sleep.readonly` |
| Weight and other health metrics/measurements | `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly` |

Add `openid`/`email`/`profile` alongside the three readonly health scopes to
the OAuth consent screen's scope list, and request the same scopes when
starting the auth flow in code (already set in
`backend/fitness/config.json.example`, and in `config.py`'s
`DEFAULT_SCOPES`). Double-check the current full scope list at
`developers.google.com/health/scopes` and the data types each one covers at
`developers.google.com/health/data-types` before finalizing.

## 6. Get a first token and sanity-check the API (before signing in through the app)

Google provides a codelab for this — do it once by hand to confirm the
project/credentials/scopes are all correct before signing in through
`/fitness/login`:

- [Make your first Google Health API call using the OAuth2
  Playground](https://developers.google.com/health/codelabs/make-your-first-api-call-using-oauth2-playground)
  — fastest path: plug your Client ID/Secret into Google's [OAuth 2.0
  Playground](https://developers.google.com/oauthplayground), authorize
  with the scopes from step 5, and exchange for a token without writing any
  code yet. Make sure `https://developers.google.com/oauthplayground` is
  in the OAuth client's Authorized redirect URIs (step 4) first. You can
  remove it again once you have a refresh token.
- [Make your first Google Health API
  call](https://developers.google.com/health/codelabs/make-your-first-api-call)
  — the fuller walkthrough, closer to what `backend/fitness/auth.py`
  automates.

**Troubleshooting: `Access blocked... doesn't comply with Google's OAuth
2.0 policy`, even though the Playground worked** — if the Playground
succeeds but signing in at `/fitness/login` gets blocked with `Error 400:
invalid_request` / "doesn't comply with Google's OAuth 2.0 policy for
keeping apps secure," even after confirming `redirect_uri` (or
`FITNESS_OAUTH_REDIRECT_URI`) matches an Authorized redirect URI in the
Cloud Console character-for-character, check the *type* of that value in
`backend/fitness/config.json`, not just its text. It must be a plain JSON
**string**:
```
"redirect_uri": "http://localhost:8000/fitness/auth/callback"
```
not a single-item **array** left over from copy-pasting the `redirect_uris`
key out of Google's downloaded credentials JSON:
```
"redirect_uri": ["http://localhost:8000/fitness/auth/callback"]
```
`auth.py` builds the authorization URL with Python's `urlencode()`, which
silently stringifies a list value into
`['http://localhost:8000/fitness/auth/callback']` — that mangled string
then gets percent-encoded into the request's `redirect_uri` parameter,
matching nothing registered in the Cloud Console. (`config.py`'s
`load_client_config()` actually guards against this one specific shape by
unwrapping a one-item list automatically — but it's worth knowing the
failure mode if a *different* malformed value slips through.) To confirm,
look at the full authorization URL the browser is sent to from
`/fitness/auth/start` and decode the `redirect_uri=` value — if it starts
with `%5B%27` (`['`), this is the bug.

## 7. Store credentials safely (local, git-ignored)

- Save the OAuth Client ID/Secret in `backend/fitness/config.json` — **not**
  in any committed doc/source file — or in the `FITNESS_GOOGLE_CLIENT_ID`/
  `FITNESS_GOOGLE_CLIENT_SECRET` environment variables (required on Render;
  see `DEPLOYMENT.md`). Per-visitor tokens are never stored here — each
  visitor's own access/refresh tokens live under
  `data/fitness/users/<user_id>/tokens.json`, written automatically by the
  sign-in flow.
- Already covered by the root `.gitignore`:
  ```
  backend/fitness/config.json
  data/fitness/
  ```
  The whole `data/fitness/` tree is ignored — visitor profiles, tokens, and
  health data all live there.
- Keep `backend/fitness/config.json.example` as its own separate,
  always-placeholder file. Don't rename/move it into `config.json` when
  setting up real credentials — copy it instead
  (`cp backend/fitness/config.json.example backend/fitness/config.json`)
  and edit the copy.
- Never paste the Client Secret or a token into a chat, issue, commit
  message, or any doc.

## 8. Checklist — before signing in at `/fitness/login` for the first time

- [ ] Fitbit account is on/linked to a Google account, and device is
      syncing normally.
- [ ] Google Cloud project created, Google Health API enabled.
- [ ] OAuth consent screen configured, your Google account added as a test
      user.
- [ ] OAuth 2.0 Client ID created (Web Server type), both redirect URIs set
      (step 4).
- [ ] Needed scopes chosen and added to the consent screen (step 5).
- [ ] First token pulled successfully via the OAuth Playground codelab
      (step 6) — confirms everything above is correct.
- [ ] Client ID/Secret saved to `backend/fitness/config.json`, or the
      `FITNESS_GOOGLE_*` environment variables — never committed.
- [ ] `FITNESS_OWNER_EMAIL` (or `FITNESS_ALLOWED_EMAILS`/
      `data/fitness/allowed_users.json`) set to your own email, so the
      app's own allowlist doesn't reject you (`VISITOR-SIGNIN-PLAN.md` §6).
- [ ] `python3 backend/server.py`, then signed in successfully at
      `/fitness/login`.

## 9. The 7-day refresh-token expiry (Testing publishing status)

While the OAuth client's publishing status is **Testing** (the default, and
what step 3's Test users list implies), every refresh token Google issues
expires after **7 days** — not the months/indefinitely a verified app's
tokens last. In practice this means every signed-in visitor, owner
included, gets sent back through `/fitness/login` (via `ReauthRequired` →
a 401 with `reauth_url` — see `API-CONTRACT.md`) about once a week, even if
they never explicitly signed out. This is expected, handled behavior, not a
bug — but it's the single biggest thing that will make the app feel
unfinished if you don't know to expect it.

Moving the client to **In production** removes the 7-day limit, but
requires Google's app-verification process, which for the sensitive health
scopes this app requests is a real review, not a formality — reasonable to
defer indefinitely for a family-and-friends-scale deployment, and worth
doing before inviting many visitors past the 100-user Test users cap.

## Reference links

- [Get started](https://developers.google.com/health/get-started)
- [Set up Google Cloud and OAuth](https://developers.google.com/health/setup)
- [Developer checklist](https://developers.google.com/health/developer-checklist)
- [Scopes](https://developers.google.com/health/scopes)
- [Data types](https://developers.google.com/health/data-types)
- [Client libraries](https://developers.google.com/health/libraries)
- [Migration guide (from Fitbit Web API)](https://developers.google.com/health/migration)
- [Move a Fitbit account to a Google Account](https://support.google.com/googlehealth/answer/14237024)
