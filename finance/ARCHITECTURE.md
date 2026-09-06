# Finance — Architecture

## Status (as of 2026-09-06)

- **Current plan: manual CSV import** (Part A below). Decided 2026-09-06:
  instead of connecting real accounts through Plaid, the dashboard is
  populated from CSV exports pulled by hand from the credit card and bank
  websites — no Plaid account, no `plaid-python`/`cryptography` dependency,
  no production-approval process, right now.
- **Phase 1 (storage + import) is built** — see A4/A7. `backend/finance/`
  (`db.py`, `csv_schema.sql`, `import_csv.py`) plus a
  `POST /finance/import` route and an "Import CSV Export" button on
  `/finance` are live. Phase 2 (spending summary + the category
  donut/monthly chart on the dashboard) is not started yet.
- **Deferred: Plaid-based live sync** (Part B below). This was the original
  plan for this file and is kept in full further down, unstarted and
  unimplemented, in case account-linking is revisited later. Nothing in Part
  B has changed; only its position in this document has, to make clear it's
  not the current work.

---

## Part A — CSV import (current plan)

### A1. Why CSV import instead of Plaid, for now

Plaid needs a developer application, a sandbox→production review, and (per
Part B §6) an auth gate in front of the whole app before it's safe to point
at real accounts. CSV export is available today, free, and needs none of
that — every bank/card site already offers "export transactions." The
tradeoff is manual effort (you have to go pull a fresh export yourself
periodically, there's no live sync) and messier source data (free-text
merchant names, no stable transaction IDs) — acceptable for "see my spending
in the dashboard now," revisit Part B if that stops being enough.

### A2. What the exports actually contain

Reviewed two sample exports (2026-09-06 pull, covering ~Jun–Sep 2026):

**Credit card export** — `transaction_date, transaction_type, status,
merchant, amount, currency, notes, category`

- `transaction_type`: `Purchase` | `Payment` | `Refund`
- `status`: `Completed` | `Pending`
- `category` is already assigned by the card issuer (`Coffee`,
  `Restaurants`, `Groceries`, `Bars and nightlife`, `Subscriptions`, etc.) —
  usable as-is, no categorizer needs to be built.
- `Payment` rows (positive amount, `category = Uncategorized`) are the
  card's own bill being paid off — a transfer, not spend. Excluded from
  spending totals by filtering on `transaction_type = Purchase`.
- `Refund` rows (e.g. an Airbnb refund under `Hotels`) net back against
  that category's spend.
- No account/institution identifier anywhere in the file — one credit card
  assumed for now; see A8 for what changes if a second card is added later.
- `currency` is `CAD` on every row.

**Bank activity export** — `effective_date, effective_time, settlement_date,
account_id, account_type, activity_type, activity_sub_type, description,
direction, symbol, name, currency, quantity, unit_price, commission,
net_cash_amount`

- One chequing account (`account_id` present, `account_type = Chequing`).
- `activity_type`: `MoneyMovement` (e-transfers, direct deposit, bill
  payments, pre-authorized debits, P2P, EFT), `BonusPayment` (cashback,
  ATM-fee reimbursements, giveaways), `Interest`.
- `symbol` / `quantity` / `unit_price` / `commission` are present in the
  header but empty in every row here — this export format is shared with a
  brokerage/investment activity export; those columns would populate for an
  investment account, unused today.
- Several rows are the chequing-side mirror of the credit card's `Payment`
  rows (`activity_sub_type = TRANSFER`, description `Credit card payment`,
  amount matching a CC `Payment` row) — same money movement seen from the
  other account. Not needed for the spending-by-category chart (that's
  driven entirely by the CC file's own `Purchase` rows, see A5), but worth
  naming here since a future income/cash-flow view would need to exclude
  these to avoid double-counting.
- `currency` is `CAD` on every row.

Net effect: **the credit card export alone is enough to build the spending
graphic** — it's already categorized and self-contained. The bank export is
useful for a broader income/cash-flow picture later, not required for A5.

### A3. Data storage

New, CSV-oriented tables (no Plaid fields — `access_token`, sync cursors,
etc. don't apply here and stay entirely in Part B):

```sql
CREATE TABLE IF NOT EXISTS accounts (
  id          TEXT PRIMARY KEY,   -- human-assigned, e.g. 'main-credit-card', 'ws-chequing'
  label       TEXT NOT NULL,
  institution TEXT,
  kind        TEXT NOT NULL       -- credit_card | chequing | (later) investment
);

CREATE TABLE IF NOT EXISTS transactions (
  id            TEXT PRIMARY KEY,   -- account_id + date + in-file row sequence
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  date          TEXT NOT NULL,
  description   TEXT NOT NULL,      -- merchant (CC) or activity description (chequing)
  amount        REAL NOT NULL,      -- negative = outflow, positive = inflow, CAD
  activity_type TEXT NOT NULL,      -- Purchase | Payment | Refund | MoneyMovement | BonusPayment | Interest
  category      TEXT,               -- issuer-provided, null on chequing rows
  status        TEXT,               -- Completed | Pending, null where not applicable
  source_file   TEXT NOT NULL,      -- which import file this came from, for audit
  imported_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
```

**Idempotency / re-import strategy:** neither export has a stable per-row
transaction ID (the CC file doesn't even have a timestamp, and same-day
duplicate amounts genuinely happen — e.g. two separate $2.94 McDonald's
charges in one day), so per-row hashing across imports is fragile. Instead,
each import is a **range replace**: for the account the file belongs to,
`DELETE FROM transactions WHERE account_id = ? AND date BETWEEN <min date in
file> AND <max date in file>`, then insert every row from the file fresh.
Re-running the same or an overlapping export is then naturally idempotent,
and there's no cross-file matching heuristic to get wrong.

### A4. Import flow — built

Decided 2026-09-06 (see A8): the trigger is a button on the dashboard
itself, not a CLI-only step, so this differs from the original sketch here.
What's actually built, in `backend/finance/`:

1. **`/finance` has an "Import CSV Export" button.** Clicking it opens a
   file picker (`accept=".csv"`); picking a file uploads it immediately —
   no separate "drop into a folder, then run a script" step.
2. **The browser sends the file's raw bytes as the POST body** — deliberately
   *not* `multipart/form-data`. `static/finance/js/import.js` calls
   `fetch("/finance/import?filename=<name>", { method: "POST", body: file })`,
   and `backend/server.py`'s new `handle_finance_import` reads it with a
   plain `Content-Length` + `self.rfile.read(length)`, the same pattern
   every other POST handler in that file already uses. This avoids writing
   a multipart parser (Python's `cgi` module is deprecated/gone in newer
   versions) for a one-file form with no other fields.
3. **`import_csv.py` detects the file type from its header row** (the sets
   in A2 above) and dispatches to the credit-card or bank-activity parser.
   No `accounts.json` mapping file — the credit card always resolves to
   the fixed `main-credit-card` account (A2/A8), and the bank file carries
   its own `account_id` column, so there was nothing left for a mapping
   file to do. Revisit if a second card is ever added.
4. **Range-replace load** (A3) into `data/finance/finance.db` via
   `backend/finance/db.py`.
5. **An audit copy of every upload** is saved to `data/finance/imports/`
   (timestamped filename) before parsing, so the original export is never
   lost even though the trigger is now upload-based rather than
   drop-a-file-and-run-a-script.
6. **A same-origin check** (`check_same_origin()`, the same one
   `/fitness/auth/logout` and `/fitness/api/sync` already use) rejects a
   POST whose `Origin` names a different host. This is not a real auth
   gate — there still isn't one anywhere in this app (Part B §6's caveat
   applies here too, now that it's live instead of hypothetical) — just a
   basic cross-site-request guard. Revisit before this app's URL is shared
   or exposed more broadly than "just me."
7. Still no scheduling — each import is a manual click after pulling a
   fresh export.

`python3 backend/finance/import_csv.py <path-to-csv>` also works as a CLI
entry point (same parsing/loading code, reads a file from disk instead of
an HTTP body) — kept for scripting/testing, not the primary path.

### A5. Dashboard integration — the spending graphic (not built yet, Phase 2/3)

New **Spending** section on `html/finance.html`, sitting with the existing
donut row/net-worth chart and reusing `static/finance/js/charts.js`'s
existing renderers rather than introducing a new charting approach:

- **Spending by Category** donut (the graphic asked for) — sums
  `abs(amount)` for `activity_type = Purchase` rows (netted against
  `Refund` rows in the same category), grouped by `category`, for the
  current calendar month by default. `Payment`/`Uncategorized` rows are
  excluded — they're bill payments, not spend. Visually matches the
  existing "Asset Allocation" / "Investment Breakdown" donuts already on
  the page.
- **Spend by Month** bar chart underneath, same treatment as the existing
  "Net Worth Over Time" line chart — one bar per month of imported history,
  so the trend across however many exports you've pulled in is visible at a
  glance.
- Small **Top Merchants** list (merchant, total, visit count) below the
  donut — cheap to compute from the same query, directly answers "where is
  the money actually going."

New backend route (`backend/server.py` dispatching into
`finance/routes.py`, same pattern Part B §4/§5 already proposed):
`GET /finance/spending-summary.json` serves the cached
`data/finance/spending-summary.json` instantly (no recompute in the request
path):

```json
{
  "asOf": "2026-09-06",
  "windowStart": "2026-09-01",
  "windowEnd": "2026-09-06",
  "byCategory": [{ "category": "Restaurants", "total": 812.44 }],
  "byMonth": [{ "month": "2026-07", "total": 1893.21 }],
  "topMerchants": [{ "merchant": "Mcdonalds 40487", "total": 61.71, "count": 21 }]
}
```

`dashboard.js` gains a `renderSpendingSection(data)` that fetches this the
same way it already fetches `finance-dashboard.json` today — no change to
how the existing net-worth/cash/investment/debt sections work.

### A6. File layout, and what's gitignored

Code lives under `backend/finance/`, matching the repo's actual
convention (`backend/fitness/` for that feature's code, `fitness/` at the
repo root for its docs only) rather than the `finance/import_csv.py` at
repo-root sketch this section originally had — corrected once real
implementation started, 2026-09-06:

```
data/finance/                  gitignored — real personal financial data lives only here
  imports/                     timestamped audit copy of every uploaded CSV
  finance.db                   SQLite store (accounts, transactions)
  spending-summary.json        (Phase 2, not built yet) generated cache

backend/finance/                tracked — code, no real data, mirrors backend/fitness/'s layout
  db.py                          connect() / init_schema() / ensure_database(), range-replace load
  csv_schema.sql                 DDL for accounts + transactions (A3) — separate from finance/schema.sql,
                                  which is Part B's Plaid-oriented DDL and unrelated to this
  import_csv.py                  CSV parsing + range-replace load; also a CLI entry point
  tests/test_import_csv.py       19 tests: parsing, idempotency, range-replace, the real upload path
  (summary.py, Phase 2, not built yet)

finance/                       tracked — docs + the Part B (Plaid) schema reference only, no code
  ARCHITECTURE.md              (this file)
  README.md
  schema.sql                    Part B's Plaid-oriented DDL (unused, deferred)

backend/server.py               gains POST /finance/import (handle_finance_import) and a
                                 finance_db.ensure_database() call at startup

static/finance/
  finance-dashboard.json        unchanged — existing sample balance/net-worth data
  js/import.js                   new — wires the "Import CSV Export" button (A4)
  css/dashboard.css              gains .fin-import-* rules for that button/status line
  js/dashboard.js, js/charts.js  unchanged so far — Phase 2/3 (A5) is what touches these
```

`.gitignore` has `data/finance/` — mirrors the existing `data/fitness/`
entry, same reasoning (real personal data, never committed).

### A7. Phased plan

1. **Phase 1 — storage + import. Built 2026-09-06.** `backend/finance/`
   (`db.py`, `csv_schema.sql`, `import_csv.py`), the range-replace schema
   from A3, `POST /finance/import`, and the dashboard's "Import CSV
   Export" button (A4) — the trigger decision in A8 folded the original
   Phase 4 upload-form idea into Phase 1. Verified against both sample
   exports: parses correctly, re-import is idempotent, a second file's
   date range doesn't touch the first's rows, cross-origin POSTs are
   rejected. 19 tests in `backend/finance/tests/test_import_csv.py`, plus
   the existing 40 (`backend/tests`) + 26 (`backend/fitness/tests`) still
   pass.
2. **Phase 2 — summary + route.** `backend/finance/summary.py` (category
   totals, monthly trend, top merchants, computed over *all* rows
   regardless of `status` per A8) writing `spending-summary.json`;
   `GET /finance/spending-summary.json` wired into `backend/server.py`.
3. **Phase 3 — dashboard.** The Spending section on `html/finance.html`
   (category donut + monthly bar chart + top-merchants list), `dashboard.js`
   fetching the new route.
4. **Phase 4 — stretch, later.** Fold in chequing income/cashback/bill-pay
   rows for a full income-vs-expense cash-flow view (excluding the CC
   payment transfer rows, per A2, to avoid double counting); support more
   than one credit card (needs a real answer to A8's still-open question);
   a proper auth gate in front of the upload endpoint (and the rest of the
   app), since A4's same-origin check is a basic guard, not real auth.

### A8. Open questions

Two settled 2026-09-06, two still open:

- ~~**Import trigger**~~ — **decided: a button/upload form on the
  dashboard**, built in Phase 1 rather than deferred to Phase 4. See A4.
- ~~**Pending purchases**~~ — **decided: count immediately**, same as
  `Completed`. `status` is still stored on every row (so a future UI could
  filter by it if that ever turns out to matter), but nothing in
  `import_csv.py` filters on it, and Phase 2's summary queries should
  follow the same rule rather than re-litigating it.
- **Multiple cards later**: since neither export file names or contains a
  stable card/institution identifier, how should a second card's export be
  told apart from the first? Still just the fixed `main-credit-card`
  account today (A2). (Proposal, unchanged: a CLI/route flag to pick the
  target account, e.g. `import_csv.py --account second-card
  path/to/export.csv`, until there's a reason to automate it.)
- **Default window** for the category donut (Phase 3): current calendar
  month, trailing 30 days, or a picker on the dashboard?

---

## Part B — Plaid-based live sync (deferred, not started)

Everything below is the original plan for this document, unchanged except
for heading numbers (§1–§8 → B1–B8) to avoid colliding with Part A above.
None of it is implemented; it's kept here for when/if account-linking is
revisited instead of (or in addition to) CSV import.

This was the plan for turning `/finance` from a static "coming soon" page
into a real feature: connect bank/investment accounts (Wealthsimple first,
any Plaid-supported institution after that) and get an ongoing view of
income, expenses, and investments.

`html/finance.html` is a working dashboard today, fetching sample data
client-side from `static/finance/finance-dashboard.json` (a plain static
file, no backend route behind it) scaffolded to match the shape this
document describes. As of Part A above, the near-term way that page gets
real data is CSV import, not this section.

### B1. Decisions already made

Confirmed with the user 2026-08-23:

| Decision | Choice | Why |
|---|---|---|
| Backend framework | Stay on stdlib `http.server`, extend it | Matches the rest of the app; a framework isn't needed to call an external API and write to SQLite |
| Datastore | SQLite (file on the same Render persistent disk as `data/`) | Real relational queries (by date/account/category) without adding a hosted DB service |

**Framework migration, tracked but not decided (2026-08-23):** the user is
considering moving the whole app to Flask or Django at some point. Not
decided yet, so the plan above stands and Phase 1 can start on stdlib —
but this is worth resurfacing before too much finance-specific route code
piles up, since the two candidates have very different costs:

- **Flask** would be a low-cost migration. Its view functions map almost
  directly onto the `finance/routes.py` handlers described below, and it
  doesn't force an ORM — `db.py`'s raw `sqlite3` usage and `schema.sql`
  could carry over largely as-is. Building finance now on stdlib and
  migrating later is fine under this option.
- **Django** would be a bigger rework but solves more at once: its ORM
  would replace `schema.sql`/hand-written SQL with models + migrations,
  and — notably — its built-in auth/session system would largely satisfy
  the "this app has no authentication" gap flagged as a hard prerequisite
  in §6, plus its admin panel is a genuinely useful tool for eyeballing
  synced Plaid data during development. If Django looks likely, it's
  worth migrating the base app to it *before* Phase 1 of finance, rather
  than building the finance layer twice.

Revisit this decision before Phase 1 if a framework choice firms up in
the meantime; nothing below assumes one outcome over the other beyond
"stdlib for now."
| Sync model | Poll on demand (page load + manual Refresh button), no public webhook endpoint | Simpler, no inbound HTTPS endpoint to secure/verify; acceptable since Plaid itself only refreshes Transactions/Investments/Liabilities ~once/day server-side anyway |

Two new third-party dependencies are unavoidable and are a deliberate,
scoped exception to the repo's stdlib-only rule (this will be the first
`requirements.txt` in the repo):

- **`plaid-python`** — official Plaid SDK. Hand-rolling Plaid's request
  signing/pagination/error model isn't worth it.
- **`cryptography`** — to encrypt Plaid `access_token`s at rest. Python's
  stdlib has no authenticated-encryption primitive suitable for this; this
  is a hard security requirement, not a convenience dependency (see B6).

### B2. What Plaid actually gives us

Confirmed via Plaid's own docs (Feb/Apr 2026): Wealthsimple (Canada) is a
supported institution for Transactions, Investments, and Auth products.
One caveat worth designing around: Wealthsimple Items commonly require
MFA re-authentication roughly every 30 days — the sync layer has to detect
and surface this (B4), not just silently fail.

Plaid's data model, and how it maps onto this app:

- **Item** — one login/connection to one institution (one Wealthsimple
  login, one bank login). Holds the `access_token`. A user can have many
  Items (this app: you will, over time — Wealthsimple + at least one bank).
- **Account** — a specific account under an Item (chequing, savings, TFSA,
  RRSP, credit card). Belongs to an Item.
- **Transaction** — a posted/pending transaction on a depository or credit
  account, fetched via the cursor-based `/transactions/sync` endpoint
  (the modern replacement for `/transactions/get`).
- **Security** + **Investment Holding** — current position (security +
  quantity + value) in an investment account, via
  `/investments/holdings/get`. This is a snapshot, not a stream — each
  sync replaces the current holdings for that account.
- **Investment Transaction** — buys/sells/dividends/fees, via
  `/investments/transactions/get` (date-ranged, not cursor-based).
- **Liabilities** (credit cards, loans — APR, min payment, due date) —
  useful for the expenses picture but scoped to Phase 5, not required for
  a first working version.

### B3. Data model (SQLite)

One file, e.g. `data/finance.db`, on the same persistent disk `render.yaml`
already mounts over `data/` — no new infrastructure. Concrete DDL lives in
`finance/schema.sql`; summary below.

```
plaid_items
  id (Plaid item_id, PK)
  institution_id, institution_name
  access_token_encrypted        -- see §6, never stored in plaintext
  transactions_cursor           -- Plaid's /transactions/sync cursor
  status                        -- 'good' | 'login_required' | 'error'
  error_code                    -- last Plaid error, if any
  created_at, last_synced_at

accounts
  id (Plaid account_id, PK)
  item_id            -> plaid_items.id
  name, official_name, mask
  type, subtype                 -- depository/credit/investment/loan, checking/tfsa/...
  current_balance, available_balance, iso_currency_code
  is_closed
  updated_at

finance_categories                -- user-facing budget categories (mirrors sections.json)
  id, label, kind                 -- kind: income | expense | transfer
  color

transactions
  id (Plaid transaction_id, PK)
  account_id         -> accounts.id
  amount, iso_currency_code
  date, authorized_date
  name, merchant_name
  pending
  plaid_category_primary, plaid_category_detailed   -- Plaid's personal_finance_category
  user_category_id   -> finance_categories.id, nullable   -- user override
  notes                           -- freeform, same pattern as tasks.json's `notes`
  created_at, modified_at

securities
  id (Plaid security_id, PK)
  ticker_symbol, name, type
  close_price, close_price_as_of

investment_holdings                -- snapshot, replaced wholesale each sync
  id, account_id -> accounts.id, security_id -> securities.id
  quantity, institution_value, cost_basis, iso_currency_code
  updated_at

investment_transactions
  id (Plaid investment_transaction_id, PK)
  account_id -> accounts.id, security_id -> securities.id
  type                             -- buy | sell | dividend | fee | ...
  quantity, price, amount, date, name

sync_log                            -- audit trail (addresses "no logging" gap
  id, item_id -> plaid_items.id      -- called out in architecture_Review.md, applied here from day 1)
  started_at, finished_at, status, detail
```

Design notes:

- Plaid IDs are used directly as primary keys (no separate surrogate key) —
  they're already stable, unique strings, and using them directly makes
  upserts trivial (`INSERT ... ON CONFLICT DO UPDATE`).
- `user_category`/`notes` on transactions mirror the existing
  `tasks.json` pattern (`note` = fixed/system data, `notes` = your own
  freeform scratch text) so the editing UX feels consistent with the rest
  of the app.
- Holdings are a snapshot table, not a history table — good enough for
  "what do I own right now." A `investment_holdings_history` table (one
  row per sync instead of overwrite) would be needed for a portfolio
  value-over-time chart; deliberately deferred to a later phase, noted
  in §7.

### B4. Sync flow

**Linking a new institution** (first-time connect, or reconnecting after
`login_required`):

1. Frontend (`static/finance/js/dashboard.js`) calls `POST /finance/link-token`.
2. Backend calls Plaid `/link/token/create`, returns the `link_token`.
3. Frontend opens Plaid Link (Plaid's own hosted JS widget, loaded from
   `cdn.plaid.com` — the one intentional exception to this app having no
   external script dependencies) with that token. User authenticates with
   their institution inside Plaid's UI; Plaid never shares credentials
   with this app.
4. On success, Plaid Link returns a `public_token` to the frontend, which
   POSTs it to `POST /finance/items/exchange`.
5. Backend exchanges it for an `access_token` via
   `/item/public_token/exchange`, encrypts it (§6), inserts a
   `plaid_items` row, then immediately runs a first sync for that item
   (accounts, transactions, and holdings if any account is `investment`
   type).

**Ongoing sync** ("poll on demand," per the confirmed decision):

- `GET /finance` and `GET /finance/summary.json` always serve cached data
  from SQLite instantly — no live Plaid call in the request path, so the
  page never blocks on Plaid's latency.
- A **Refresh** button POSTs `/finance/sync` (optionally
  `{"item_id": "..."}` for one institution, or all items if omitted),
  which calls `/accounts/get`, `/transactions/sync`, and (for investment
  accounts) `/investments/holdings/get` +
  `/investments/transactions/get` for each item, upserts rows, updates
  `last_synced_at`, and writes a `sync_log` row.
- The summary page shows a "last synced 3h ago" style timestamp per item
  so staleness is always visible, since nothing pushes updates on its own.
- Optional, later: a Render **Cron Job** hitting `POST /finance/sync`
  nightly, so data stays roughly fresh even on days you don't open the
  page. This is still polling (consistent with the "no webhooks" choice),
  just on a timer instead of only on click — noted as a Phase 6
  nice-to-have, not required for a working v1.

**Item health**: if a sync call fails with Plaid's `ITEM_LOGIN_REQUIRED`
(expected periodically for Wealthsimple, per §2), `sync.py` sets
`plaid_items.status = 'login_required'` rather than treating it as a hard
error, and the UI should surface a "Reconnect Wealthsimple" action that
re-runs the Link flow in update mode for that specific item.

### B5. Proposed folder layout

```
finance/
  ARCHITECTURE.md   (this file)
  README.md         (human-facing docs, same convention as service_now/README.md)
  schema.sql         DDL for every table in §3
  db.py              SQLite connection + schema init (CREATE TABLE IF NOT EXISTS from schema.sql)
  crypto.py           encrypt/decrypt access_token (Fernet, key from env — §6)
  plaid_client.py      builds the Plaid API client from env vars (PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV)
  sync.py               sync_item(item_id), sync_all() — the logic in §4
  categorize.py          maps Plaid's personal_finance_category to finance_categories defaults
  routes.py                request handlers for everything under /finance/*
```

`backend/server.py` gets a small number of new lines dispatching any path
under `/finance/` (beyond the existing static `/finance` page route) into
`finance/routes.py`, the same way it currently dispatches `/tasks/*` to
its own inline handlers — one process, one server, no new deployable, so
`render.yaml` doesn't need to change.

Frontend: `html/finance.html` is already a real dashboard page (see
`static/finance/js/{dashboard,charts,ticker}.js` and
`static/finance/css/{dashboard,ticker}.css`) — a per-section directory
under `static/finance/`, matching `static/fitness/`'s layout rather than
the flat `static/js/` convention (`script.js`, `task-detail.js`, etc.)
this section originally proposed. The Plaid sync's own frontend calls
(link-token, item exchange, refresh) extend `dashboard.js` rather than
introducing a new file, still with no shared frontend framework.

### B6. Security

This is the part where "personal task tracker" and "personal finance app
with real bank data" stop being architecturally equivalent, and it needs
to be treated that way:

- **`access_token` is encrypted at rest.** Fernet symmetric encryption
  (`cryptography.fernet.Fernet`) keyed by a `PLAID_TOKEN_ENCRYPTION_KEY`
  env var, generated once via `Fernet.generate_key()` and set in Render's
  environment — never committed, never logged. Losing/rotating this key
  makes all stored tokens unrecoverable (every Item has to be re-linked);
  that's an accepted operational tradeoff, documented here so it isn't a
  surprise later.
- **`access_token` never reaches the frontend or logs.** Only
  short-lived, single-use `link_token`s and `public_token`s cross the
  browser boundary; those are safe by design (Plaid's own model).
- **This app currently has zero authentication** (architecture_Review.md
  §2, finding 3). That was an acceptable gap for a task list. It is not
  an acceptable gap for real bank balances and transaction history sitting
  on a public Render URL. Recommendation: **minimal auth (a shared-secret
  cookie/header gate in front of the whole app, not just `/finance`) is a
  hard prerequisite before this is used with real (non-sandbox)
  accounts**, not a nice-to-have to get to eventually. It's also required
  in practice — Plaid's own application review for Production access asks
  how end-user data is protected. Phase 5 below is scheduled accordingly.
- **Plaid environment**: build and test against `PLAID_ENV=sandbox`
  (fake institutions, fake data, no real bank ever touched) through
  Phases 1-4. Moving to `production` (real Wealthsimple/bank data)
  requires a Plaid application review and only happens after the auth
  gate in Phase 5 is in place.
- **No webhook endpoint** given the polling decision, so there's no
  inbound-signature-verification surface to build/secure right now. If
  webhooks are reconsidered later (Phase 6+), that reopens this section —
  Plaid webhook payloads are JWT-signed and must be verified before trust.

### B7. Phased plan

1. **Phase 0 — setup.** Create a Plaid developer account (sandbox
   access is instant, free). Add `requirements.txt` with `plaid-python`
   and `cryptography`. Add `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`,
   `PLAID_TOKEN_ENCRYPTION_KEY` as local `.env`-style config (matching
   `service_now/`'s existing dotenv convention) and Render env vars.
2. **Phase 1 — Link + storage.** `schema.sql`, `db.py`, `crypto.py`,
   `plaid_client.py`, the Link flow end-to-end against Plaid Sandbox,
   storing one `plaid_items` row and its `accounts` rows.
3. **Phase 2 — Transactions.** `/transactions/sync` integration,
   `transactions` table, `GET /finance/transactions.json` (filterable by
   account/date/category), a first real `html/finance.html` showing
   accounts + a recent-transactions list.
4. **Phase 3 — Investments.** Holdings + investment transactions,
   `securities` table, net-worth and portfolio-value summary on the
   dashboard.
5. **Phase 4 — Categorization.** `finance_categories` management (own
   "+ New Category" flow, mirroring `/tasks/new-category`), user
   overrides on transactions, spending-by-category breakdown.
6. **Phase 5 — Auth gate.** Minimal shared-secret auth in front of the
   whole app (§6). Required before switching `PLAID_ENV` to `production`.
7. **Phase 6 — optional.** Nightly scheduled sync (Render Cron Job),
   Liabilities product (credit card/loan details), holdings-history table
   for a portfolio-value-over-time chart, webhook-based push if "poll on
   demand" ever stops feeling live enough.

### B8. Open questions / assumptions

Flagging these rather than silently deciding — happy to keep the defaults
below and adjust later, just don't want to bake in the wrong one:

- **Currency**: assuming CAD-primary (Wealthsimple + presumably Canadian
  banks), but every Plaid account/transaction carries its own
  `iso_currency_code`, so multi-currency is handled naturally by the
  schema — this only affects how totals are displayed/summed (naive
  summing across currencies would be wrong), which is a Phase 3/4 UI
  detail, not an architectural blocker.
- **Which other institutions** beyond Wealthsimple you actually want to
  connect — not architecturally load-bearing (Plaid Link's own search UI
  handles institution choice generically), just useful to know for
  testing scope in Sandbox before Phase 5.
- **Deployment**: assumed this stays the single existing Render web
  service (same process as today), not a second service — consistent
  with "poll on demand" needing no public webhook endpoint. Flag if you'd
  rather split finance into its own service for any reason.
- **Framework migration timing** (see §1): if Flask or Django firms up as
  a real near-term plan for the whole app, decide *before* starting Phase
  1 whether to migrate first — especially for Django, where the ORM and
  built-in auth would otherwise mean rebuilding `schema.sql`/`db.py` and
  the auth gate in §6/Phase 5 shortly after writing them.
