# Finance

`/finance` is a working dashboard today — stat tiles (net worth, total
assets, debt), three donuts (asset allocation, investment breakdown,
portfolio by stock/ETF), a net-worth trend chart, five collapsible
sections (cash, investments, bitcoin, debt, lines of credit), and a
7-ticker watchlist sidebar proxied server-side (`backend/finance_prices.py`).
**All of that is still backed by a static seed JSON file
(`static/finance/finance-dashboard.json`) — hardcoded sample data, not
real connected accounts.** Only the Spending and Cash Flow sections below
read real data.

**Current plan (decided 2026-09-06):** instead of connecting real accounts
through Plaid, the dashboard gets populated from CSV exports pulled by hand
from the credit card and bank sites — see **Part A** of
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the full plan (what the exports
contain, the import/storage design, and a new "Spending by Category" +
"Spend by Month" section this adds to the dashboard).

**Phases 1-3 and 4a are built** (`backend/finance/`): `/finance` has an
"Import CSV Export" button that uploads a credit card or bank activity
export and range-replace loads it into `data/finance/finance.db` (a "data
last imported" timestamp next to the button confirms it landed), a
"Spending" block (category donut — click a category to filter Top
Merchants down to it, and a pencil button on any merchant opens a dialog
to fix its category, either for just one transaction or permanently — a
spend-by-month chart) that now covers chequing debit spend (debit
purchases, pre-authorized debits like rent, bill payments) alongside
credit-card purchases, and a "Cash Flow" block (income/expense/net stat
tiles, a monthly income-vs-expense chart where clicking a bar lists the
transactions behind it, each with an Exclude/Include toggle so a
transaction that isn't real income/expense — e.g. a reimbursement deposit
that just zeroes out an earlier purchase — can be dropped from the totals
without affecting Spending) folding in chequing income (direct deposits,
cashback, etc. default to category "Income") alongside credit-card
spend — both with their own This month/30 days/90 days/All time window
selector. **Phase 4b (a second
credit card, from a different institution) is documented but not built**
— see `ARCHITECTURE.md` §A9 for the concrete plan; it's blocked on having
a real sample export from that institution, not on a decision. **Not
started**: a real auth gate in front of the upload/route endpoints.

**Part C** of `ARCHITECTURE.md` is a holistic, documented-but-not-built
plan (2026-09-07) for an append-only raw/staging capture layer under
every financial fact this app tracks — not just CSV transactions but
also Cash/Investments/Bitcoin/Debt/Lines of Credit, still hardcoded
sample data per the note above — with curated tables translated from
that raw layer, a manual balance-entry mechanism for everything with no
CSV/API today, and a plan to backfill today's already-imported CSVs into
the new layer rather than starting history from zero.

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
