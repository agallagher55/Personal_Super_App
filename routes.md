# Routes

How URLs map to HTML pages, their JS, and the backend handlers in
`backend/server.py`. Data lives in three normalized SQLite tables —
`sections`, `tasks`, `tags` in `data/tasks.db` — joined on the fly into the
nested shape below and served read-only at `/tasks.json`, mutated only
through the POST routes below. See `DATABASE-MIGRATION.md` for the schema,
the one-time import from the JSON files this replaced, and
`backend/tasks_export.py` for regenerating those files from the database.

Every page below loads `static/styles/styles.css` and
`static/styles/nav.css` first, then its own section stylesheet if it has
one — see `DESIGN-SYSTEM.md` for the shared shell those pages are built
from.

Every `/fitness*` route except `/fitness/login`, `/fitness/auth/*`, and
`/fitness/api/me` now requires a signed-in session — a signed-out visitor
gets a 302 to `/fitness/login` (HTML pages) or a 401 (API routes). See
`fitness/VISITOR-SIGNIN-PLAN.md` for the sign-in design.

## GET routes

| Route | Serves | Frontend JS | Notes |
|---|---|---|---|
| `/` | `html/home.html` | `static/js/home.js` | Dashboard hub — one live summary card per section (open task count, latest steps, BTC price), each linking through. |
| `/tasks` | `html/tasks/index.html` | `static/js/script.js` | All sections. `?view=all\|today\|waiting\|overdue` selects the queue pill above the list: **Today** is the personal `focus_today` flag, **Waiting** is `status = 'pending'` (which the ServiceNow sync maps Awaiting User Info onto), and **Overdue** is computed from `due_date`. Defaults to `all`, deliberately: a focused queue can legitimately be empty, and opening on one made a populated database look empty. A text search box filters the rendered cards on top of whichever view is active. |
| `/tasks/categories` | `html/tasks/tasks-index.html` | `static/js/tasks-index.js` | Category (section) list with open/closed counts. |
| `/tasks/new` | `html/tasks/new-task.html` | `static/js/new-task.js` | New task form. `?section=<id>` preselects a section. |
| `/tasks/new-category` | `html/tasks/new-category.html` | — | New category (section) form. |
| `/tasks/<slug>` | `html/tasks/index.html` | `static/js/script.js` | Same page as `/tasks`, but `script.js` reads the slug from the URL and renders only the matching section. 404 if `<slug>` doesn't match any section's `slug` (checked after the `/tasks/new`, `/tasks/new-category`, and `/tasks/categories` exact matches above). |
| `/task/<id>` | `html/tasks/task-detail.html` | `static/js/task-detail.js` | Edit/delete a single task by id. 404 if `<id>` doesn't exist. |
| `/fitness` | `html/fitness/index.html` | `static/fitness/js/dashboard.js` | Personal Health dashboard — see `fitness/README.md`. Requires a session cookie; 302 to `/fitness/login` otherwise. |
| `/fitness/<page>` | `html/fitness/pages/<page>.html` | `static/fitness/js/pages/<page>.js` | Per-metric detail view. `<page>` is one of `steps`, `heart-rate`, `sleep`, `activity`, `spo2`, `hrv`, `breathing-rate`, `temperature`, `weight`, `calories`, `food` (`FITNESS_PAGES` in `backend/server.py`). 404 if unknown; 302 to `/fitness/login?next=/fitness/<page>` if signed out. |
| `/fitness/login` | `html/fitness/login.html` | `static/fitness/js/login.js` | Sign-in page. 302 to `/fitness` if already signed in. |
| `/fitness/auth/start` | — | — | 302 to Google's consent screen, sets a short-lived signed state cookie. `?next=` (validated to a `/fitness*` path) carries where to land after sign-in. |
| `/fitness/auth/callback` | — | — | Google's OAuth redirect target: verifies state, exchanges the code, checks the allowlist, creates/updates the visitor's profile, sets the session cookie, 302 to `next`. On any failure, 302 to `/fitness/login?error=<code>`. |
| `/fitness/api/me` | JSON | — | `{"signed_in": false}` or `{"signed_in": true, "email", "name", "has_tokens"}`. Never gated — the one `/fitness/api/*` route a signed-out visitor can call. |
| `/fitness/api/health` | JSON | — | Liveness check for the signed-in visitor's own store; see `fitness/API-CONTRACT.md`. Requires a session; 401 otherwise. |
| `/fitness/api/metrics` | JSON | — | Dashboard summary across all metrics, `?from=&to=` (default last 7 days). Requires a session; 401 otherwise. |
| `/fitness/api/metrics/<metric>` | JSON | — | Single-metric detail, `?from=&to=` (default last 30 days). 404 if `<metric>` isn't in `KNOWN_METRICS`. Requires a session; 401 otherwise. |
| `/fitness/api/metrics/<metric>/samples` | JSON | — | Raw intraday readings in `[from, to]` (full ISO 8601 instants). Only `heart_rate` today. Requires a session; 401 otherwise. |
| `/finance` | `html/finance.html` | `static/finance/js/ticker.js`, `static/finance/js/dashboard.js`, `static/finance/js/import.js`, `static/finance/js/spending.js`, `static/finance/js/cashflow.js` | Net worth dashboard template (cash, investments, bitcoin, debt, lines of credit — each collapsible, each row with a % of section total), plus "Spending" (category donut, top merchants, monthly chart) and "Cash Flow" (income/expense stat tiles, monthly chart, click a bar for that month's transactions) sections backed by the real routes below, and a sidebar watchlist of 7 tickers (Bitcoin, gold, WTI crude, S&P 500, US 10Y Yield, US 30Y Yield, Canada 5Y Yield). Net worth (cash/investments/bitcoin/debt/lines of credit/net-worth-over-time) still renders from the static `static/finance/finance-dashboard.json` sample file — real tables for all of it exist as of `finance/ARCHITECTURE.md` Part C Phase 1, but nothing on this page reads them yet (Phase 3). See `finance/ARCHITECTURE.md` Part A for what's real today and Part C for the rest of the plan. |
| `/finance/spending-summary.json` | JSON | — | `?window=month\|30d\|90d\|all&category=<name>` (window defaults to `month`; category narrows Top Merchants only). Category totals, a 12-month trend, and top merchants, computed live from `data/finance/finance.db` (`backend/finance/summary.py`). |
| `/finance/cash-flow.json` | JSON | — | `?window=...` (same options as above). Income/expense/net stat tiles plus a 12-month income-vs-expense trend. |
| `/finance/cash-flow-transactions.json` | JSON | — | `?month=YYYY-MM&kind=income\|expense`. The individual transactions behind one bar of the Cash Flow chart, each annotated `excluded`/`reason` rather than filtered out; income rows also carry a friendly `type` (Deposits/Cashback/Giveaways/Interest) and the response includes a `byType` breakdown. 400 if `month` is missing. |
| `/finance/spend-month-transactions.json` | JSON | — | `?month=YYYY-MM`. The transactions behind one bar of the Spending chart, plus their total. 400 if `month` is missing. |
| `/finance/shakepay-btc-by-month.json` | JSON | — | Monthly totals of BTC accumulated through Shakepay round-up purchases. |
| `/finance/merchant-transactions.json` | JSON | — | `?merchant=<description>&window=...`. Individual transactions for one merchant/description, for the "Edit category" dialog's one-time-fix picker. 400 if `merchant` is missing. |
| `/finance/last-imported.json` | JSON | — | `{"lastImportedAt": <ISO timestamp>\|null}` — the most recent CSV import time across every transaction, shown next to the "Import CSV Export" button. |
| `/finance/api/prices` | JSON | — | Watchlist quotes, proxied server-side to avoid browser CORS issues (`backend/finance_prices.py`) — 6 of the 7 tickers come from Yahoo Finance's free keyless chart endpoint; the Canada 5Y yield comes from the Bank of Canada's Valet API instead, since Yahoo has no working symbol for it. Always 200; each ticker is fetched independently and comes back with `price`/`change_pct` as `null` if its own fetch failed, rather than failing the whole response. |
| `/finance/api/holding-prices` | JSON | — | Live quotes for arbitrary portfolio holding symbols (`?symbols=A,B,C`, comma-separated), proxied from Yahoo the same way as `/finance/api/prices` — no Bank of Canada fallback, since these are always equity/ETF symbols. 400 if `symbols` is missing; otherwise always 200 with `{"quotes": {symbol: {"price", "change_pct"} \| null}}`, one entry per requested symbol. |
| `/new` | — | — | 302 redirect to `/tasks/new`. |
| `/tasks.json` | the `sections` + `tasks` + `tags` tables joined into the nested shape the three JSON files used to hold, plus a top-level `scratchpad` key `{"date", "text"}` from the `scratchpad_entries` table | — | `?scratchpad_date=YYYY-MM-DD` selects that date's entry (the viewer's own local date, sent by the client - the server never guesses at it); omitted or malformed falls back to the most recently-dated saved entry, so a caller that doesn't pass one still sees the last thing actually written rather than an empty day. `no-store` cache headers. Every task-tracker page above fetches this client-side to render. |
| `/tasks/sync-status.json` | JSON | — | `{"latest_run": {...} \| null, "previous_success_started_at": "..."}` from the `sync_runs` table, for the ServiceNow freshness line on `/tasks`. `latest_run` is the most recent attempt whatever its result, so a failed sync stays visible rather than being hidden behind the last good one. `previous_success_started_at` is the baseline the "changed" badge compares each task's `source_updated_at` against: the run before the latest when that one succeeded, otherwise the last successful run. Both are empty on a database that has never synced. |
| `/tasks/scratchpad.json` | JSON | — | `?date=YYYY-MM-DD` (required, 400 if missing/malformed) - `{"date", "text"}` for that one day, from `scratchpad_entries`. Used by the day-navigation and carry-forward controls on `/tasks` so switching days doesn't re-fetch and re-render the whole task list the way `/tasks.json` would. |

Any other path falls through to `SimpleHTTPRequestHandler`, i.e. plain
static file serving from the repo root (`/static/...`, etc.).

## POST routes

| Route | Handler | Effect |
|---|---|---|
| `/tasks/new` | `handle_new_task` | Inserts a row in the `tasks` table (`section_id` foreign key) and any tags in the same SQLite transaction. Redirects `303` to `/tasks/<slug>?added=1` for the section the task was created in. |
| `/tasks/quick-task` | `handle_quick_task` | `{section_id, desc}` - the scratchpad's convert-line-to-task action (issue #165). Shares `create_task()` with `handle_new_task` (same defaults, no redirect) and returns `{id, section_slug}` as JSON so the caller can link straight to the new task. 400 if either field is missing or `section_id` doesn't exist. |
| `/tasks/new-category` | `handle_new_category` | Inserts a new empty row in `sections`, slugified from `label`. Redirects `303` to `/tasks/categories?added=1`. 400 if the name is empty or a category with that slug/id already exists. |
| `/tasks/update` | `handle_update_tasks` | Bulk update by task id in `data/tasks.db`, field by field against an allow-list: `desc`, `note`, `notes`, `tags`, `status`, `priority`, `ticket_number`, `assignment_group`, `requested_by`, `due_date`, `focus_today`, `follow_up_date`, `time_estimate`, `related_files`, `parent_id`, `section_id` (moves the task to another section, appended to its end, and renumbers the positions left behind in the old section), `work_type` (ignored outside the Work Tasks section), `env_dev`/`env_qa`/`env_prod`, `cmdb_updated`, plus reordering. Anything else in the payload is ignored, which is why `servicenow_sys_id` survives an edit. Only rows that actually changed get an `UPDATE` and a new `modified`. Reordering a section is applied only when the payload covers every task in it, so a single-task save from `/task/<id>` cannot shove that task to the front. Returns JSON. |
| `/tasks/delete` | `handle_delete_task` | Deletes a task row; its tags are removed by the foreign-key cascade. Returns JSON. |
| `/tasks/scratchpad` | `handle_update_scratchpad` | `{date, text}` — upserts the `scratchpad_entries` row for `date` (`YYYY-MM-DD`, the viewer's own local calendar date) with `text`. 400 if `date` is missing or malformed. Returns JSON. |
| `/fitness/auth/logout` | `handle_fitness_logout` | Clears the session cookie, 302 to `/fitness/login`. |
| `/fitness/api/sync` | `fitness_api.trigger_sync(user_id)` | Pulls new data from the Google Health API into the signed-in visitor's own `data/fitness/users/<user_id>/health_data.json`. Synchronous; requires a session (401 otherwise); 409 if a sync for this visitor is already running. See `fitness/API-CONTRACT.md`. |
| `/finance/import` | `handle_finance_import` | `?filename=<name>.csv`, raw CSV bytes as the request body (not multipart — the dashboard's upload form sends the `File` object directly as `fetch()`'s body). Saves a timestamped audit copy under `data/finance/imports/` and range-replace loads it into `data/finance/finance.db` — see `finance/ARCHITECTURE.md` Part A3/A4. 400 on an unrecognized header, non-UTF-8 content, or a file over 5MB. |
| `/finance/categories/transaction` | `handle_set_transaction_category` | `{transaction_id, category}` — a one-time category fix for a single transaction. Empty/omitted `category` removes the override. 404 if the transaction doesn't exist. |
| `/finance/categories/merchant` | `handle_set_merchant_category` | `{description, category}` — a permanent category fix for every transaction (past and future) with that exact description. |
| `/finance/cash-flow-exclusions` | `handle_set_cash_flow_exclusion` | `{transaction_id, excluded}` — marks (or unmarks) one transaction as not real income/expense for Cash Flow's totals, without affecting Spending. 404 if the transaction doesn't exist. |
| `/finance/balance-entries` | `handle_record_balance_entry` | `{account_id, as_of_date, balance_cad, label?, institution?, kind?, interest_rate?, credit_limit?}` — the manual-entry mechanism for Cash/Bitcoin/Debt/Lines of Credit (none of which have a CSV or API), appending a dated balance snapshot rather than overwriting one. `label`/`kind` are required the first time an `account_id` is used; an existing account keeps its stored values when they're left out. See `finance/ARCHITECTURE.md` Part C8. |

## Seeded sections (current `data/sections.json` snapshot)

Each section has an `id` (used by the `section` field on `/tasks/new`, the
`section_id` foreign key on tasks, and in `tasks/update` payloads) and a
`slug` (used in the `/tasks/<slug>` URL).

| id | slug | label |
|---|---|---|
| `own-tasks` | `work` | Work Tasks |
| `finance-tasks` | `finance` | Finance |
| `admin-tasks` | `admin` | Admin |
| `research-tasks` | `research` | Research |
| `mike-coverage` | `mike` | Covering for Mike Potter |

New sections can be added via the `/tasks/new-category` form (from the
"+ New Category" link on `/tasks/categories`), which slugifies the given name into
both `id` and `slug`. The table above describes the committed seed snapshot;
the running app reads `data/tasks.db`, not this JSON file. For a one-off manual
change, edit the database and then refresh the snapshot with
`python3 backend/tasks_export.py` as described in `README.md`.
