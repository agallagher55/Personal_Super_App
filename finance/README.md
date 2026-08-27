# Finance

`/finance` is a working dashboard today — stat tiles (net worth, total
assets, debt), three donuts (asset allocation, investment breakdown,
portfolio by stock/ETF), a net-worth trend chart, five collapsible
sections (cash, investments, bitcoin, debt, lines of credit), and a
7-ticker watchlist sidebar proxied server-side (`backend/finance_prices.py`).
It's backed by a static seed JSON file scaffolded to the shape
[`ARCHITECTURE.md`](ARCHITECTURE.md) describes, not by real connected
accounts yet.

This folder's actual content is the plan for that next step: connecting
real financial accounts (Wealthsimple first, any Plaid-supported
bank/investment institution after that) via [Plaid](https://plaid.com),
so the dashboard reflects live synced data instead of that static seed
file. Nothing in that sync layer is implemented yet — see
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the full plan (data model, sync
flow, security requirements, phased build order) and
[`schema.sql`](schema.sql) for the concrete SQLite DDL it describes.

Short version: `plaid-python` handles talking to Plaid, `cryptography`
encrypts stored access tokens, everything else stays consistent with the
rest of this repo — stdlib `http.server`, one Render service, no build
step. The one hard prerequisite called out in the architecture doc: this
app has no authentication today, which is fine for a task list and not
fine for real bank data, so a minimal auth gate (§6/Phase 5 of
`ARCHITECTURE.md`) has to land before `PLAID_ENV` ever points at
production instead of sandbox.
