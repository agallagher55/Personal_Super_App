# Finance

Plan for connecting real financial accounts (Wealthsimple first, any
Plaid-supported bank/investment institution after that) via
[Plaid](https://plaid.com), so `/finance` shows a live-ish view of income,
expenses, and investments instead of the current "coming soon" stub.

Nothing in this folder is implemented yet — see
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
