# Finance — Architecture

## Status (as of 2026-09-06)

- **Current plan: manual CSV import** (Part A below). Decided 2026-09-06:
  instead of connecting real accounts through Plaid, the dashboard is
  populated from CSV exports pulled by hand from the credit card and bank
  websites — no Plaid account, no `plaid-python`/`cryptography` dependency,
  no production-approval process, right now.
- **Phases 1-3 (storage, summary, and the dashboard graphic) are built** —
  see A4/A5/A7. `backend/finance/` (`db.py`, `csv_schema.sql`,
  `import_csv.py`, `summary.py`) plus `POST /finance/import`,
  `GET /finance/spending-summary.json`, and the "Import CSV Export" button
  + "Spending" section (category donut, top merchants, monthly bar chart,
  window selector) on `/finance` are all live.
- **Phase 4a (Cash Flow — chequing income folded in) is built** — see A5b.
  A separate "Cash Flow" block (income/expense/net stat tiles + a monthly
  income-vs-expense chart) reads chequing income/expense alongside the
  existing credit-card spend total. A real bug this surfaced (a big refund
  could push the overall expense total negative) was caught in browser
  testing against the real sample data and fixed before landing.
- **Phase 4b (a second credit card, from a different institution) is
  documented, not built** — see A9. No sample export from that institution
  exists yet to design a parser against, so this is a concrete plan for
  what changes when one does, not code.
- **Not started**: a real auth gate in front of the upload/route endpoints
  (still just the same-origin check from A4).
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

**What this doesn't touch, worth being explicit about:** `/finance`'s
stat tiles (Net Worth/Assets/Debt), the three overview donuts, the
Cash/Investments/Bitcoin/Debt/Lines of Credit sections, and the Net Worth
Over Time chart are **all still reading `static/finance/finance-dashboard.json`**
- the hardcoded sample data ("Sample data — no accounts are connected
yet," per that file's own `note` field) this dashboard was scaffolded
with before any of Part A existed. None of it is real, and none of it is
touched by anything in this document. Only **Spending** (A5) and **Cash
Flow** (A5b) read your real imported CSV data. Populating the rest for
real means either building CSV import for those sources too (bills and
lines of credit aren't things a credit card or chequing export would
contain anyway - they'd need their own source) or eventually landing
Part B's Plaid sync, which was designed to cover all of it at once.

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

### A5. Dashboard integration — the spending graphic — built

A **Spending** block on `html/finance.html`, between the net-worth chart
and the Cash section, built as described below with a few deviations from
the original sketch (each noted):

- **Spending by Category** donut — sums `-amount` for `Purchase` rows
  netted against `Refund` rows in the same category, grouped by
  `category`. `Payment`/`Uncategorized` rows are excluded — they're the
  card bill being paid off, not spend. Visually matches the existing
  "Asset Allocation" / "Investment Breakdown" donuts, reusing
  `charts.js`'s `drawDonut` directly.
- **Spend by Month** bar chart underneath, in its own card the same shape
  as "Net Worth Over Time" — one bar per month across the full imported
  history (not window-filtered, unlike the category donut and top
  merchants, so the trend is visible regardless of which window is
  selected). New `drawMonthlyBarChart` in `charts.js`, sharing that file's
  `niceAxis`/`formatCad`/`formatMonth`/`themeColor` helpers rather than
  duplicating them.
- **Top Merchants** list (merchant, total, visit count), next to the donut
  rather than below it — reuses `dashboard.js`'s existing `renderRow` (now
  exported) instead of a new template, same as the Cash/Debt/Investments
  rows.
- **A window selector** (`<select>`: This month / Last 30 days / Last 90
  days / All time) resolves A8's "what's the default window" question by
  giving you the control instead of picking one - defaults to "This
  month," matching how a credit card statement reads.
- Every one of these three has an empty state ("No spending in this window
  yet," "No purchases in this window yet," "No spending history yet —
  import a CSV export above to get started") rather than a broken-looking
  blank chart before anything's been imported - verified by screenshotting
  a fresh install.

**Deviation from the original sketch: no `spending-summary.json` cache
file.** `backend/finance/summary.py`'s `build_summary()` queries
`data/finance/finance.db` live on every request instead of writing and
serving a cached JSON file. Part B's Plaid design cached because a Plaid
API call is slow and shouldn't sit in the request path; here the "upstream"
is a local SQLite query over a few hundred/thousand personal rows, fast
enough that a cache would only add invalidation (regenerate after every
import) to worry about for no real benefit. `GET
/finance/spending-summary.json?window=<month|30d|90d|all>` in
`backend/server.py` calls it directly:

```json
{
  "asOf": "2026-09-06",
  "window": "month",
  "windowStart": "2026-09-01",
  "windowEnd": "2026-09-06",
  "byCategory": [{ "category": "Restaurants", "total": 812.44 }],
  "byMonth": [{ "month": "2026-07", "total": 1893.21 }],
  "topMerchants": [{ "merchant": "Mcdonalds 40487", "total": 61.71, "count": 21 }]
}
```

**Deviation: a new `static/finance/js/spending.js`, not
`dashboard.js`'s `renderSpendingSection`.** Self-contained (fetches its
own data, owns its own DOM) like `ticker.js` and `import.js` already are,
rather than folded into `initFinanceDashboard()` - `dashboard.js` only
changes to `export` `renderRow`/`renderLegend` for reuse, nothing about
its own net-worth/cash/investment/debt rendering changes.

### A5b. Cash Flow — income vs expense — built (Phase 4a, 2026-09-06)

Requested explicitly: "fold chequing income in for a full income-vs-expense
view." The Spending block above is credit-card-purchases-only by design
(A5); this is the separate, broader picture - what actually came in
against everything that actually went out, combining both imported
sources.

**A real parsing gap had to be fixed first.** `import_csv.py`'s bank-
activity parser was only storing the CSV's coarse `activity_type` column
(`MoneyMovement` / `BonusPayment` / `Interest`) - the same value on a
paycheck, a bill payment, and an e-transfer alike, useless for telling
income from expense. Fixed to store `activity_sub_type` instead (`AFT_IN`,
`SPEND`, `CASHBACK`, `E_TRFOUT`, ...), falling back to the coarse type only
when sub_type is blank/`-` (Interest rows). `csv_schema.sql`'s comment on
`activity_type` documents this dual meaning (Purchase/Payment/Refund for
credit card rows, the sub_type for chequing rows). Re-importing existing
data (already the normal flow, per A4's range-replace) picks this up
automatically - no migration needed.

**Classification** (`backend/finance/summary.py`), keyed off that now-
correct `activity_type`:

| Bucket | Chequing `activity_type` values |
|---|---|
| Income | `AFT_IN`, `CASHBACK`, `GIVEAWAY`, `Interest` |
| Expense | `SPEND`, `AFT_OUT`, `OBP_OUT`, `P2P` |
| Neither (excluded) | `E_TRFIN`, `E_TRFOUT`, `TRANSFER`, `TRANSFER_TF`, `EFT`, anything else |

**The "neither" bucket is a deliberate, conservative default worth
flagging, not a settled judgment call.** Interac e-Transfers and EFT
transfers are indistinguishable, from the CSV alone, between "paid/was
paid by another person" (real income/expense) and "moved to/from one of
your own other accounts" (not real income/expense - e.g. sending money to
an investment account). Excluding them entirely never double-counts your
own money moving around, but it does mean a real e-transfer payment to a
friend (splitting a bill, say) doesn't show up as expense here. `TRANSFER`
specifically also catches the chequing-side mirror of a credit card bill
payment (`activity_sub_type = TRANSFER`, description "Credit card
payment") - that one's unambiguous and correctly excluded, since the
underlying purchases already count as expense on the card side. Revisit
the e-transfer/EFT default if it turns out to hide too much of the real
picture.

Total expense combines both sources:
`chequing_expense_total()` + `credit_card_expense_total()` (the latter is
literally the same "real spend" query `category_breakdown()`/
`monthly_trend()` already use - Purchase netted against Refund,
Payment/Uncategorized excluded).

**A real bug this surfaced, caught in browser testing (not just unit
tests) against the actual reviewed sample data:** `credit_card_expense_total()`
wasn't clamped at 0 the way `category_breakdown()`'s `HAVING total > 0`
and `monthly_trend()`'s `max(..., 0)` already were. The sample credit card
export has a $445.62 refund against a much smaller total of real
purchases in the same window, and summing across *all* categories at once
(rather than per-category, where the existing clamp lived) let that one
refund push the overall total negative - "Expense: -$96" on the dashboard,
which reads as nonsense. Fixed by clamping all three total functions
(`chequing_income_total`, `chequing_expense_total`,
`credit_card_expense_total`) at 0, with a regression test
(`test_a_large_refund_clamps_to_zero_rather_than_going_negative`) using
the same shape of data that exposed it. This is exactly the kind of bug
unit tests alone (built from hand-picked, individually-reasonable
fixtures) can miss and a real end-to-end check against real data catches.

**Dashboard**: a second `.fin-block-header` ("Cash Flow", with its own
window selector - independent from the Spending block's, so
`spending.js` and the new `static/finance/js/cashflow.js` stay fully
decoupled, each owning its own DOM, matching A5's established pattern),
a 3-tile stat row (Income / Expense / Net - `net` gets a
`.fin-stat-value-negative` red-text class when negative), and an "Income
vs Expense by Month" grouped bar chart (`drawIncomeExpenseChart`, new in
`charts.js`, two bars per month rising from a shared zero baseline -
reuses `drawMonthlyBarChart`'s axis/theme/resize/hover scaffolding). New
route: `GET /finance/cash-flow.json?window=<...>` →
`summary.build_cash_flow()`.

### A5c. Click a category to filter Top Merchants, and a "data last imported" indicator — built (2026-09-06)

Two small requested additions on top of A5/A5b:

**Click-to-filter.** Clicking a category - either its donut segment or its
legend row - narrows the Top Merchants list to just that category;
clicking the same category again (or the "× Clear" chip that appears next
to "Top Merchants") clears it. Selecting a category never re-renders the
donut/legend itself (`byCategory` doesn't change), only restyles it -
`GET /finance/spending-summary.json` gains an optional `&category=<name>`
param that narrows `topMerchants` alone (`summary.build_summary()`,
`summary.top_merchants()`), leaving `byCategory`/`byMonth` computed the
same as always.

`charts.js`'s `drawDonut()` and `dashboard.js`'s `renderLegend()` (used
by every donut on the page, not just Spending's) each gained one optional
parameter - `onSliceClick`/`onClick` - so only `spending.js` opts into
click behavior; every other donut/legend call site is unchanged. Selected/
dimmed styling is plain DOM class-toggling in `spending.js` after render
(`.fin-legend-row-selected`, `.fin-legend-row-dimmed`,
`.donut-seg-dimmed`), not baked into the shared, generic render helpers.
Switching the window selector clears any active category filter, so a
stale filter can never point at data outside the newly selected window.

**"Data last imported."** A `db.last_imported_at()` (`MAX(imported_at)`
across every transaction row) behind a new
`GET /finance/last-imported.json`, shown next to the "Import CSV Export"
button (`static/finance/js/import.js`, styled `.fin-last-imported`) -
fetched on page load and refreshed immediately after a successful upload.
Deliberately one global timestamp across both accounts, not a
per-account/per-source one - simplest thing that answers "did my last
import actually happen and when," which is what was asked; revisit if
per-source staleness (e.g. "chequing data is 3 weeks older than the
credit card's") ever turns out to matter.

Verified in a real browser (Playwright): clicking a category correctly
narrows the merchant list and restyles the legend/donut, clicking it
again and the Clear chip both restore the exact original unfiltered
list, and the last-imported timestamp updates after a real upload (a
timing gap between the upload finishing and the async refresh landing
is a test-script race, not a product bug - confirmed by waiting slightly
longer before reading it). 5 new tests (`test_summary.py`'s category-filter
cases, `test_db.py`'s `last_imported_at` cases).

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
                                (no spending-summary.json/cash-flow.json - summary.py queries live, no cache file)

backend/finance/                tracked — code, no real data, mirrors backend/fitness/'s layout
  db.py                          connect() / init_schema() / ensure_database(), range-replace load,
                                  last_imported_at() (A5c)
  csv_schema.sql                 DDL for accounts + transactions (A3) — separate from finance/schema.sql,
                                  which is Part B's Plaid-oriented DDL and unrelated to this
  import_csv.py                  CSV parsing + range-replace load; also a CLI entry point
  summary.py                     category/monthly/top-merchant queries (A5, with an optional category
                                  filter for A5c) + cash-flow queries (A5b)
  tests/test_import_csv.py       21 tests: parsing, idempotency, range-replace, the real upload path,
                                  the activity_sub_type extraction fix (A5b)
  tests/test_summary.py          22 tests: netting, window filtering, exclusions, empty-database
                                  handling, the category filter (A5c)
  tests/test_cash_flow.py        15 tests: income/expense classification, the negative-expense
                                  regression (A5b), empty-database handling
  tests/test_db.py               2 tests: last_imported_at() (A5c)

finance/                       tracked — docs + the Part B (Plaid) schema reference only, no code
  ARCHITECTURE.md              (this file)
  README.md
  schema.sql                    Part B's Plaid-oriented DDL (unused, deferred)

backend/server.py               gains POST /finance/import, GET /finance/spending-summary.json
                                 (now takes &category=, A5c), GET /finance/cash-flow.json,
                                 GET /finance/last-imported.json (A5c), and a finance_db.ensure_database()
                                 call at startup

static/finance/
  finance-dashboard.json        unchanged — existing sample balance/net-worth data. Cash, Investments,
                                 Bitcoin, Debt (student loan/credit cards/bills), and Lines of Credit are
                                 ALL still sourced from here, not from any CSV import - only Spending and
                                 Cash Flow (A5/A5b) read real imported data. See A1's "what this doesn't
                                 touch" note.
  js/import.js                   wires the "Import CSV Export" button (A4) and the "data last imported"
                                  indicator (A5c)
  js/spending.js                 wires the "Spending" section - donut, top merchants (with the category
                                  click-to-filter, A5c), monthly chart, window select (A5)
  js/cashflow.js                 wires the "Cash Flow" section - stat tiles, monthly chart, window select (A5b)
  js/dashboard.js                unchanged except exporting renderRow/renderLegend (with an optional
                                  onClick, A5c) for spending.js to reuse
  js/charts.js                   gains drawMonthlyBarChart (A5) and drawIncomeExpenseChart (A5b),
                                  sharing their axis/theme/format helpers; drawDonut gains an optional
                                  onSliceClick (A5c)
  css/dashboard.css               gains .fin-import-*, .fin-block-*, .fin-spending-*, .fin-bar-canvas,
                                  .fin-empty-note, .fin-chart-legend*, .fin-stat-value-negative,
                                  .fin-legend-row-selected/-dimmed, .donut-seg-dimmed, .fin-merchants-filter*,
                                  .fin-last-imported rules
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
2. **Phase 2 — summary + route. Built 2026-09-06.** `backend/finance/summary.py`
   (category totals over the selected window, a 12-month trend regardless
   of window, top merchants) computed live over *all* rows regardless of
   `status` per A8 — no cache file, see A5's deviation note.
   `GET /finance/spending-summary.json?window=<...>` wired into
   `backend/server.py`. 19 tests in `backend/finance/tests/test_summary.py`.
3. **Phase 3 — dashboard. Built 2026-09-06.** The Spending block on
   `html/finance.html` (category donut, top merchants, monthly bar chart,
   window selector — A5), `static/finance/js/spending.js` fetching the new
   route. Verified in a real browser (Playwright): both sample exports
   imported through the actual upload button, the donut/legend/merchants/
   chart all render with the correct numbers, the empty states render
   correctly on a fresh database, and a real bug this surfaced (the
   monthly chart's "no data yet" text staying visible on top of real bars,
   because an explicit `display: flex` in the new CSS was beating the
   browser's own `[hidden]` rule) was fixed before landing.
4. **Phase 4a — Cash Flow. Built 2026-09-06.** Chequing income/expense
   classification, combined with credit-card spend, into a full
   income-vs-expense view (A5b) — the fixes and the design tradeoffs
   (what counts as income/expense vs. is excluded as a transfer) are
   documented there, not repeated here.
5. **Phase 4b — a second credit card, a different institution.
   Documented, not built** — see A9. Explicitly requested but explicitly
   not buildable yet: every institution's export format differs, and
   there's no real sample from the second one to design a parser against.
   A9 is the concrete plan for when there is one.
6. **Phase 4c — still not started.** A proper auth gate in front of the
   upload/route endpoints (and the rest of the app), since A4's
   same-origin check is a basic guard, not real auth.

### A8. Open questions

All four resolved (the fourth by A9, a plan rather than a decision - it's
blocked on a real sample export, not on a choice):

- ~~**Import trigger**~~ — **decided: a button/upload form on the
  dashboard**, built in Phase 1 rather than deferred to Phase 4. See A4.
- ~~**Pending purchases**~~ — **decided: count immediately**, same as
  `Completed`. `status` is still stored on every row (so a future UI could
  filter by it if that ever turns out to matter), but nothing in
  `import_csv.py` or `summary.py` filters on it.
- ~~**Default window**~~ — **decided: give you the control instead of
  picking one.** The Spending block's window selector (This month / Last
  30 days / Last 90 days / All time) defaults to "This month," per A5.
- ~~**Multiple cards later**~~ — **not a decision, a plan: see A9.** The
  original proposal here (a CLI/route flag to pick the target account) is
  still roughly right, but A9 goes further: the second institution's
  export format is unknown, so `detect_kind()` needs a third branch built
  against a real sample when one exists, categorization may differ or be
  entirely absent (which would silently exclude that card's spend under
  the current `category != 'Uncategorized'` filter - a real gap to fix at
  that time, not before).

### A9. Adding a second credit card (a different institution) — documented, not built

Explicitly requested (2026-09-06): a second card is coming, but it's from
a different institution than the Wealthsimple-issued card the current
parser was built against, so its export will very likely look nothing
like `CREDIT_CARD_HEADER` in `import_csv.py`. This section is what to do
when a real sample of that export exists - not speculative code against a
format nobody has seen yet.

**Why not built now:** every card issuer's CSV export is genuinely
different - different column names, different date formats, different
sign conventions (some show purchases as positive with a separate
debit/credit indicator column instead of a signed amount), and no
guarantee of issuer-provided categories at all. Guessing at that shape
without a real file to test against would just produce a parser for a
format that doesn't exist.

**What changes when a real sample export shows up:**

1. **A third `detect_kind()` branch.** `import_csv.py`'s `detect_kind()`
   matches on an exact header-column-set (`CREDIT_CARD_HEADER` today) -
   add the new institution's header set alongside it, and a
   `_rows_from_<institution>_credit_card()` parser mirroring
   `_rows_from_credit_card()`'s shape (date, description, amount,
   activity_type, category, status).
2. **`DEFAULT_CREDIT_CARD_ACCOUNT` stops being a single constant.** Today
   *any* file matching the one known credit-card header shape resolves to
   the same hardcoded `main-credit-card` account (A2/A8) - that assumption
   breaks the moment a second, differently-shaped credit card export
   exists, since now there are two *different* header shapes, each
   needing its own fixed account id (e.g. `main-credit-card` and
   `second-credit-card`). The natural fix given the new header shape is
   already how `detect_kind()` tells the two apart: hardcode each known
   institution's shape to its own account id, the same one-shape-one-account
   pattern used today, just doubled rather than turned into a
   general-purpose "which account" parameter - no reason to build that
   generality before there's a third format to justify it.
3. **Categorization may differ or be entirely absent - and this is a real
   gap to fix, not just a note.** The current `category != 'Uncategorized'`
   filter (`_SPEND_FILTER` in `summary.py`) uses "has a real category" as
   a proxy for "this is a purchase, not a bill payment," because the
   Wealthsimple-issued card always provides one. **If the second
   institution doesn't categorize purchases at all, every one of that
   card's purchases would silently vanish from Spending, Cash Flow, and
   the Income vs Expense chart** - not an error, just quietly excluded,
   which is worse. Fix at that time: filter on `activity_type = 'Purchase'`
   for what counts as spend, and treat "has a category" as a separate,
   optional thing only the *category breakdown* needs (falling back to an
   "Uncategorized" or "Other" bucket in the donut rather than dropping the
   row from spend entirely).
4. **Watch for format quirks specific to the new issuer**: date format
   (`MM/DD/YYYY` vs. this export's `YYYY-MM-DD`), amount sign convention
   (signed amount vs. a separate debit/credit or type column), and
   currency (assumed CAD throughout today, per A1 - fine unless the new
   card is USD-denominated, which would need real per-row currency
   handling rather than the implicit CAD assumption).

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
