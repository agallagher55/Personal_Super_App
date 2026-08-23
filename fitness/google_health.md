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
4. Set **Authorized redirect URIs**. Add `http://localhost:8000/oauth/callback`
   (matches `backend/fitness/config.json.example`'s default) — the local
   backend catches this once during `cli.py auth`. Also add
   `https://developers.google.com/oauthplayground` if you want to
   sanity-check the setup via step 6 first.
5. Once created, **download the credentials JSON** (or copy the **Client
   ID** and **Client Secret** shown). You'll paste these into
   `backend/fitness/config.json` — **this file must never be committed**;
   see step 7.

## 5. Pick the scopes we need

Google Health API scopes take the form
`https://www.googleapis.com/auth/googlehealth.<category>.<readonly|writeonly>`.
This project only needs **read** access:

| Data we want | Scope |
|---|---|
| Steps, distance, floors, altitude (activity) | `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly` |
| Sleep | `https://www.googleapis.com/auth/googlehealth.sleep.readonly` |
| Weight and other health metrics/measurements | `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly` |

Add the readonly scopes you need to the OAuth consent screen's scope list,
and request the same scopes when starting the auth flow in code (already
set in `backend/fitness/config.json.example`). Double-check the current
full scope list at `developers.google.com/health/scopes` and the data
types each one covers at `developers.google.com/health/data-types` before
finalizing.

## 6. Get a first token and sanity-check the API (before running `cli.py auth`)

Google provides a codelab for this — do it once by hand to confirm the
project/credentials/scopes are all correct before running the backend's own
auth flow:

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
2.0 policy` from `cli.py auth`, even though the Playground worked** — if
the Playground succeeds but `python cli.py auth` (from
`backend/fitness/`) gets blocked with `Error 400: invalid_request` /
"doesn't comply with Google's OAuth 2.0 policy for keeping apps secure,"
even after confirming `redirect_uri` in `backend/fitness/config.json`
matches an Authorized redirect URI in the Cloud Console
character-for-character, check the *type* of that value, not just its
text. It must be a plain JSON **string**:
```
"redirect_uri": "http://localhost:8000/oauth/callback"
```
not a single-item **array** left over from copy-pasting the `redirect_uris`
key out of Google's downloaded credentials JSON:
```
"redirect_uri": ["http://localhost:8000/oauth/callback"]
```
`auth.py` builds the authorization URL with Python's `urlencode()`, which
silently stringifies a list value into
`['http://localhost:8000/oauth/callback']` — that mangled string then gets
percent-encoded into the request's `redirect_uri` parameter, matching
nothing registered in the Cloud Console. To confirm, look at the full
authorization URL `auth.py` prints to the terminal before opening the
browser and decode the `redirect_uri=` value — if it starts with `%5B%27`
(`['`), this is the bug.

## 7. Store credentials safely (local, git-ignored)

- Save the OAuth Client ID/Secret (and later, the refresh token) in
  `backend/fitness/config.json` — **not** in any committed doc/source file.
- Already covered by the root `.gitignore`:
  ```
  backend/fitness/config.json
  data/fitness/health_data.json
  ```
- Keep `backend/fitness/config.json.example` as its own separate,
  always-placeholder file. Don't rename/move it into `config.json` when
  setting up real credentials — copy it instead
  (`cp backend/fitness/config.json.example backend/fitness/config.json`)
  and edit the copy.
- Never paste the Client Secret or a token into a chat, issue, commit
  message, or any doc.

## 8. Checklist — before running `Sync now` / `cli.py sync` for the first time

- [ ] Fitbit account is on/linked to a Google account, and device is
      syncing normally.
- [ ] Google Cloud project created, Google Health API enabled.
- [ ] OAuth consent screen configured, your Google account added as a test
      user.
- [ ] OAuth 2.0 Client ID created (Web Server type), redirect URI(s) set.
- [ ] Needed scopes chosen and added to the consent screen (step 5).
- [ ] First token pulled successfully via the OAuth Playground codelab
      (step 6) — confirms everything above is correct.
- [ ] Client ID/Secret saved to `backend/fitness/config.json` — never
      committed.
- [ ] `cd backend/fitness && python cli.py auth` completed successfully.

## Reference links

- [Get started](https://developers.google.com/health/get-started)
- [Set up Google Cloud and OAuth](https://developers.google.com/health/setup)
- [Developer checklist](https://developers.google.com/health/developer-checklist)
- [Scopes](https://developers.google.com/health/scopes)
- [Data types](https://developers.google.com/health/data-types)
- [Client libraries](https://developers.google.com/health/libraries)
- [Migration guide (from Fitbit Web API)](https://developers.google.com/health/migration)
- [Move a Fitbit account to a Google Account](https://support.google.com/googlehealth/answer/14237024)
