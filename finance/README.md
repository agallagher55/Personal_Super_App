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

A live bug found while reviewing the Part C plan below is **fixed**:
transaction ids
were positional, so re-importing an export that contained any new row on
an already-imported date silently moved category corrections and Cash
Flow exclusions onto the wrong transaction. Ids are content-derived now,
and an automatic migration carries existing corrections across — see
`ARCHITECTURE.md` §A3b.

**Part C** of `ARCHITECTURE.md` is a holistic plan (2026-09-07) for an
append-only raw/staging capture layer under every financial fact this
app tracks — not just CSV transactions but also
Cash/Investments/Bitcoin/Debt/Lines of Credit, still hardcoded sample
data per the note above. **Phase 1 is built**: `accounts` is extended,
new snapshot tables (`account_balance_snapshots`, `account_terms_snapshots`)
give Cash/Bitcoin/Debt/Lines of Credit a real, dated history instead of
a single mutable number, `POST /finance/balance-entries` is the manual
entry mechanism for all of it, and the real database has been seeded
from today's sample values as a starting point. The dashboard itself
still reads `finance-dashboard.json` for now — that switch is Phase 3.
Phases 2 (investment holdings) and 4 (a raw layer under CSV
transactions, plus backfilling today's already-imported CSVs into it)
remain documented, not built.

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

## Shakepay: PDF import (manual, standalone)

Shakepay isn't a Plaid-linkable institution and doesn't offer a CSV export
in either shape `backend/finance/import_csv.py` understands, so it falls
outside both the Plaid plan (Part B) and the CSV-import system above, so
it gets its own ingestion path: `backend/finance/import_shakepay.py`
parses the monthly PDF statements Shakepay emails out and range-replace
loads them into the same `data/finance/finance.db` `transactions` table
`import_csv.py` writes to — Shakepay activity shows up in Spending and
Cash Flow the same way the credit card/bank CSV imports do, no dashboard
changes needed.

Shakepay actually sends **two separate PDFs** each month for the same
account, and they are not interchangeable:

- **"Shakepay Inc." statement** (the longer one, ~18 pages) — cash, USD,
  and crypto activity: round-up BTC purchases, staking/cashback rewards,
  P2P sends/receives, Interac e-Transfers. Every card purchase shows up
  here only as an anonymous `Transfer ... to Shakepay Financial Inc. for
  Card purchase` line — no merchant name.
- **"Shakepay Financial Inc." statement** (the shorter one, ~6 pages) —
  card purchases only, but with the actual merchant name for each one
  (e.g. `Card purchase Tim Hortons #0476 -$4.55`).

For tracking what you actually spent money on, the second file is the one
that matters — the first file's card lines are uninformative without it.
Import both together for a full month: the account statement's funding-
transfer lines are always dropped in favor of the card statement's
merchant-named lines, so a month imported without the card PDF is simply
missing card-spend detail. Same idea for round-up buys, which appear once
in the cash table (the CAD side, kept) and once in the crypto table (the
BTC side, dropped) — only the CAD side counts.

```
pip install pypdf   # not part of this repo's stdlib-only rule; scoped
                     # exception for this tool, same as plaid-python/
                     # cryptography above

python3 backend/finance/import_shakepay.py path/to/shakepay-account.pdf path/to/shakepay-card.pdf
# or point it at a folder you save every month's two downloads into -
# any argument that's a directory expands to the *.pdf files in it:
python3 backend/finance/import_shakepay.py data/finance/shakepay/
```

On Windows, `backend/shakepay-update.bat` wraps that last form (same
`python.exe` path `start-server.bat` already uses) — double-click it, or
run it with a folder path as its one argument to import from somewhere
other than `data\finance\shakepay\`.

This creates three accounts on first run — `shakepay-card` (kind
`credit_card`; card purchases as `Purchase`/`Refund`, exactly the shape
`credit_card_expense_total()`/`category_breakdown()`/`top_merchants()`
already scope for, i.e. the "second credit card" case `ARCHITECTURE.md`
§A9 flagged but hadn't built), `shakepay-cash` (kind `chequing`; P2P
sends reuse the existing `P2P` expense type, everything else — P2P
receives, Interac transfers, round-ups — uses a value that deliberately
isn't in `summary.CHEQUING_INCOME_TYPES`/`CHEQUING_EXPENSE_TYPES`, so it's
recorded but excluded from Spending/Cash Flow by default, same
conservative treatment e-transfers already get), and `shakepay-crypto`
(kind `bitcoin_wallet`; staking rewards/interest/external BTC deposits,
also excluded by default — paid in BTC, not spendable CAD). See the
module docstring in `import_shakepay.py` for the full mapping and the
reasoning behind each choice. These are separate from the
`shakepay-cad`/`shakepay-btc` accounts `networth.py` seeded for the net
worth sections (Part C) — those are dated balance snapshots, these are
itemized transactions, the same relationship `main-credit-card` has to
its own net worth entry.

New card purchases land with category `None` (shows "Uncategorized" until
tagged via the pencil-edit dialog, same as any other uncategorized row).
Re-running with the same PDF is idempotent (range-replace, same as CSV
import); a "data last imported" refresh on `/finance` picks up Shakepay's
timestamp too, since it's the same `transactions` table.

### Bulk-categorizing Shakepay merchants

Tagging each merchant by hand through the dashboard adds up once there
are a few dozen of them across several months, so
`backend/finance/categorize_shakepay.py` does it in bulk: a
keyword-pattern table (Tim Hortons/Starbucks/etc. → `Coffee`, grocery
chains → `Groceries`, "PARKING"/"AIR-SERV" → `Gas, parking, and tolls`,
and so on — category names deliberately match the taxonomy the existing
credit card export already uses, so Shakepay spend merges into the same
Spending categories instead of fragmenting into new ones) matched
case-insensitively against every distinct `shakepay-card` merchant, each
match written through the exact same `set_merchant_category_override`
the dashboard's pencil-edit dialog uses. Never overwrites a category
you already set by hand. `backend/shakepay-update.bat` runs this
automatically after every import; run it on its own with:

```
python3 backend/finance/categorize_shakepay.py            # apply
python3 backend/finance/categorize_shakepay.py --dry-run  # preview only
```

Prints what it categorized and, more usefully, which merchants matched
nothing — extend `CATEGORY_RULES` with a pattern for those and re-run,
or just tag the odd one out by hand via the dashboard.

Deliberately a CLI script, not a `/finance` upload button: `pypdf` would
otherwise become a dependency of the live server process
(`backend/server.py` imports `import_csv`/`db`/`summary`/`networth` at
startup) for a file type only run by hand, a few times a month. Run it
locally, or in a Render Shell against the deployed `data/finance/finance.db`.

`data/finance/` is git-ignored (see above) — real dollar amounts and
transaction history shouldn't sit in git history or a public-ish
deployment (see the auth gap called out above). Feed the PDFs themselves
straight from wherever you download them; don't commit those either.
