# Finance

`/finance` is a working dashboard today — stat tiles (net worth, total
assets, debt), three donuts (asset allocation, investment breakdown,
portfolio by stock/ETF), a net-worth trend chart, five collapsible
sections (cash, investments, bitcoin, debt, lines of credit), and a
7-ticker watchlist sidebar proxied server-side (`backend/finance_prices.py`).
It's backed by a static seed JSON file scaffolded to the shape
[`ARCHITECTURE.md`](ARCHITECTURE.md) describes, not by real connected
accounts yet.

**Current plan (decided 2026-09-06):** instead of connecting real accounts
through Plaid, the dashboard gets populated from CSV exports pulled by hand
from the credit card and bank sites — see **Part A** of
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the full plan (what the exports
contain, the import/storage design, and a new "Spending by Category" +
"Spend by Month" section this adds to the dashboard). Nothing in that
import layer is built yet either — this is still the plan, not the
implementation.

Plaid-based live account linking (Wealthsimple first, any Plaid-supported
institution after that) is kept as **Part B** of `ARCHITECTURE.md`,
deferred rather than dropped, in case account-linking is revisited later.
[`schema.sql`](schema.sql) is that original Plaid-oriented DDL; the
CSV-import schema is simpler and lives inline in Part A of the
architecture doc for now (no accounts synced, no access tokens to store).

The one hard prerequisite called out for the Plaid path specifically: this
app has no authentication today, which is fine for a task list and not
fine for real bank data, so a minimal auth gate (§B6/Phase 5) has to land
before `PLAID_ENV` ever points at production instead of sandbox. CSV import
doesn't need that gate to get started, since there's no live credential
being stored — though real transaction data will exist in
`data/finance/` on disk once import lands, so that directory is gitignored
(see Part A §A6) the same way `data/fitness/` already is.
