-- Schema for data/finance/finance.db (CSV-import approach, see
-- finance/ARCHITECTURE.md Part A). Deliberately separate from
-- finance/schema.sql at the repo root, which is the Plaid-oriented schema
-- for the deferred Part B plan - no access tokens, sync cursors, or other
-- Plaid-specific fields belong here.
--
-- Which text domains below are database-enforced (CHECK), versus
-- documented but left open, is a deliberate split:
--
--   accounts.kind - CLOSED, and constrained. networth.py's
--     ASSET_KINDS/LIABILITY_KINDS partition this exact set to decide a
--     balance's sign in net worth math (raising UnknownAccountKindError
--     for anything else); a typo or a stray value from direct SQL landing
--     here wouldn't fail loudly at the point it was written, only later
--     and less obviously when net worth math trips over it. See
--     db.ACCOUNT_KINDS, the single source of truth both this constraint
--     and networth.py's two sets are checked against.
--   account_balance_snapshots.source, import_batches.kind -
--     APPLICATION-EXTENSIBLE, left unconstrained. Both are genuinely
--     expected to grow (a future Plaid/API source alongside
--     manual/import; a future net-worth CSV import batch kind alongside
--     manual_balance/manual_holding, ARCHITECTURE.md Part C3) and nothing
--     downstream partitions on the full set the way net worth math
--     partitions on account kind - an unrecognized value here is a
--     forward-compatible admission, not silent data corruption.
--   transactions.activity_type, transactions.category, transactions.status -
--     EXTERNALLY SUPPLIED, left unconstrained. These come from whatever
--     text the bank's or card issuer's export happens to contain
--     (ARCHITECTURE.md Part A2) - constraining them risks rejecting a
--     legitimate future export format change outright.
--
-- Every REAL column below (transactions.amount/btc_quantity,
-- account_balance_snapshots.balance_cad, account_terms_snapshots.
-- interest_rate/credit_limit) is IEEE 754 double, which cannot exactly
-- represent most decimal fractions - CONTAINED, not eliminated, by
-- rounding to a fixed canonical precision at every write boundary
-- (db.round_cad/round_btc, db.ROUND_CAD_DECIMALS/ROUND_BTC_DECIMALS: two
-- decimal places for anything CAD-denominated including interest_rate,
-- eight for btc_quantity - a satoshi) rather than switching these to an
-- integer-cents/integer-satoshis column type, which would mean every
-- import path, every summary.py aggregation, and the JSON contract every
-- finance page already reads changing in lockstep for a personal-scale
-- ledger where two of these values have never needed to be compared with
-- `==`. See db.py's longer comment next to ROUND_CAD_DECIMALS for the
-- full reasoning.
--
-- CAD-only, enforced: accounts.currency exists as a column, but every
-- export, every sample value, and transactions.amount/account_balance_
-- snapshots.balance_cad are CAD today (ARCHITECTURE.md A1/A2, "Every
-- export and every sample value today is CAD... Not worth solving until
-- real"). Leaving currency an unconstrained free-text column would let
-- the schema silently *imply* multi-currency support - a non-CAD account
-- whose transactions and balances are still bare CAD amounts with no
-- original currency, no original amount, and no exchange rate anywhere -
-- that no calculation in this codebase actually provides. Constrained to
-- 'CAD' below until that's real: adding a genuinely non-CAD account
-- needs, at minimum, a transaction's original amount/currency alongside
-- its normalized CAD value, an exchange rate, and documented conversion
-- behavior for refunds/transfers/account totals - not just relaxing this
-- constraint.
--
-- Dates are 'YYYY-MM-DD' (a calendar date, no time-of-day or timezone);
-- timestamps are 'YYYY-MM-DDTHH:MM:SSZ' (an instant, always UTC - see
-- dates.py, the single place that formats "right now" into either
-- shape). Every date/timestamp column here is TEXT NOT NULL with no ''
-- sentinel for "missing" - a row that has one at all always has a real
-- value; where the value can legitimately be absent (import_batches.
-- date_range_start/end, accounts.closed_at) the column is nullable and
-- NULL means "not given," never ''.
--
-- transactions.date/imported_at are CHECK-constrained to that shape
-- (GLOB, not a real calendar check - see dates.is_iso_date's docstring
-- for why that's a deliberate, not lazy, choice) since transactions.date
-- in particular feeds db.replace_transactions_in_range's DELETE...
-- BETWEEN boundaries directly; a malformed value there risks silently
-- deleting the wrong rows, not just failing to match. The remaining
-- date/timestamp columns below (account_balance_snapshots,
-- account_terms_snapshots, import_batches, the override/exclusion
-- tables, accounts.closed_at) follow the identical format by convention,
-- enforced by dates.py at the handful of trusted internal call sites
-- that write them, rather than by a CHECK constraint on every single one
-- - unlike transactions.date, none of them is used as a destructive
-- operation's own boundary.

CREATE TABLE IF NOT EXISTS accounts (
  id          TEXT PRIMARY KEY,   -- human-assigned (e.g. 'main-credit-card') or the bank export's own account_id
  label       TEXT NOT NULL,
  institution TEXT,
  kind        TEXT NOT NULL      -- credit_card | chequing | savings | investment | bitcoin_wallet |
                                   -- line_of_credit | loan | bill (net worth kinds, see networth.py -
                                   -- ARCHITECTURE.md Part C5a) - CLOSED domain, see db.ACCOUNT_KINDS above
    CHECK (kind IN ('credit_card', 'chequing', 'savings', 'investment', 'bitcoin_wallet',
                     'line_of_credit', 'loan', 'bill')),
  currency    TEXT NOT NULL DEFAULT 'CAD' CHECK (currency = 'CAD'),  -- CAD-only for now, see above
  closed_at   TEXT                -- NULL while open; a closed account stops counting toward net worth
                                   -- (ARCHITECTURE.md C6) from this date. Existing databases get these two
                                   -- columns via db.py's migration 2, since CREATE TABLE IF NOT EXISTS is a
                                   -- no-op against an accounts table that already exists.
);

CREATE TABLE IF NOT EXISTS transactions (
  id            TEXT PRIMARY KEY,   -- account_id:date:content-digest:occurrence, see db.transaction_id
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  date          TEXT NOT NULL       -- YYYY-MM-DD - CHECK is shape-only (GLOB), see the classification
                                     -- comment above for why this one column is enforced
    CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  description   TEXT NOT NULL,      -- merchant (credit card) or activity description (bank)
  amount        REAL NOT NULL,      -- negative = outflow, positive = inflow, CAD
  activity_type TEXT NOT NULL,      -- credit card: Purchase | Payment | Refund
                                     -- chequing: the export's activity_sub_type (AFT_IN, SPEND, CASHBACK,
                                     -- E_TRFOUT, TRANSFER, ...), falling back to activity_type (e.g.
                                     -- 'Interest') only when sub_type is blank/'-' - see import_csv.py's
                                     -- _rows_from_bank_activity and summary.py's income/expense classification
  category      TEXT,               -- issuer-provided (credit card export only) or a default assigned
                                     -- at import time (chequing income rows get 'Income' - see
                                     -- import_csv.py); NULL for everything else (chequing expense/transfer rows)
  status        TEXT,               -- Completed | Pending (credit card export only), NULL otherwise
  btc_quantity  REAL,               -- Shakepay ROUNDUP_BUY rows only (import_shakepay.py) - the BTC bought
                                     -- by that round-up, for the monthly-accumulated-BTC figure; NULL
                                     -- for every other row (existing databases get this column via
                                     -- db.py's migration 3, since CREATE TABLE IF NOT EXISTS is a no-op
                                     -- against a transactions table that already exists)
  source_file   TEXT NOT NULL,      -- which upload this row came from, for audit
  imported_at   TEXT NOT NULL       -- YYYY-MM-DDTHH:MM:SSZ
    CHECK (imported_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  batch_id      INTEGER REFERENCES import_batches(id)  -- which import_csv_text()/import_shakepay_text()
                                     -- call produced this row - see import_batches below. NULL for a
                                     -- transaction imported before this column existed (existing
                                     -- databases get it via db.py's migration 7); no batch is
                                     -- reconstructed retroactively for those rows, since inventing one
                                     -- would claim provenance the data doesn't actually have.
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);

-- Category corrections (see finance/ARCHITECTURE.md's "Editing categories"
-- section). Two independent, precedence-ordered mechanisms rather than
-- rewriting `transactions.category` in place, so the original
-- issuer-provided value is never lost and a correction survives a
-- re-import untouched:
--
--   transaction_category_overrides - a "one-time" fix: recolors exactly
--     one transaction, keyed by its id. Deliberately NOT a foreign key
--     with ON DELETE CASCADE: a range-replace re-import (db.py) deletes
--     and re-inserts every row in the affected date range, and a cascade
--     would silently wipe the override the moment the same CSV is
--     re-uploaded. Left as a plain column instead - the override simply
--     re-applies automatically if a transaction with that same id
--     reappears (the normal case for an unchanged re-export), and
--     harmlessly points at nothing otherwise.
--   merchant_category_overrides - a "permanent" fix: recolors every
--     transaction (past AND future) whose description exactly matches,
--     keyed by that description text. Naturally stable across re-imports
--     since nothing here depends on a row's synthetic id.
--
-- Precedence when both could apply to the same row: transaction-level
-- wins (see the transactions_effective view below) - a deliberate
-- one-off correction is more specific/intentional than a blanket rule.

CREATE TABLE IF NOT EXISTS transaction_category_overrides (
  transaction_id TEXT PRIMARY KEY,
  category       TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_category_overrides (
  description TEXT PRIMARY KEY,
  category    TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- Every summary.py query reads effective_category (never transactions.category
-- directly) so both override mechanisms apply everywhere uniformly - the
-- Spending donut, Top Merchants, and the monthly trend all resolve
-- corrections the same way, in one place, rather than each query
-- reimplementing the same COALESCE/JOIN.
CREATE VIEW IF NOT EXISTS transactions_effective AS
SELECT
  t.*,
  COALESCE(tco.category, mco.category, t.category) AS effective_category
FROM transactions t
LEFT JOIN transaction_category_overrides tco ON tco.transaction_id = t.id
LEFT JOIN merchant_category_overrides mco ON mco.description = t.description;

-- Cash Flow exclusions (finance/ARCHITECTURE.md A5f): marks a specific
-- transaction as not real income/expense - e.g. a benefits reimbursement
-- deposit that just zeroes out an earlier purchase, so counting it as
-- income overstates take-home money. Deliberately its own table, not a
-- third case bolted onto the category-override tables above: "does this
-- count toward Cash Flow" is a different question from "what Spending
-- category is this," and a transaction can need one answer changed
-- without the other (the reimbursed purchase itself may still belong in
-- Spending's "where did my money go," even though the reimbursement
-- shouldn't count as income).
--
-- Always keyed by transaction id, never by description, unlike
-- merchant_category_overrides - every direct deposit shares the identical
-- generic description "Direct deposit received," so a description-keyed
-- rule would incorrectly exclude real paycheck deposits too. Same
-- reasoning as transaction_category_overrides for skipping
-- ON DELETE CASCADE: a range-replace re-import regenerates the same
-- content-derived id for the same transaction, so the exclusion sticks
-- naturally; a cascade would wipe it the moment that CSV is re-uploaded.
CREATE TABLE IF NOT EXISTS cash_flow_exclusions (
  transaction_id TEXT PRIMARY KEY,
  reason         TEXT,
  created_at     TEXT NOT NULL
);

-- Net worth (finance/ARCHITECTURE.md Part C, Phase 1): Cash, Bitcoin,
-- Debt, and Lines of Credit, none of which have a CSV/API today (Part
-- C4c) - only a hand-maintained sample JSON file. Every balance is a
-- dated, append-only snapshot rather than a mutable column, so
-- "current" is just "the latest one" (latest_account_balances below)
-- and history falls out of the same table for free - see networth.py.

-- One row per "event that produced facts": a manual balance entry
-- (kind = manual_balance/manual_holding, source_file/file_hash/
-- date_range_* left NULL - nothing to fill them with) or, since the
-- September 2026 database review, one per successful import_csv.py/
-- import_shakepay.py call (kind = csv_credit_card/csv_bank_activity/
-- shakepay_card/shakepay_account - see those modules), which do
-- populate every column here and are what transactions.batch_id above
-- points at. "Successful" specifically: both importers create this row
-- inside the same transaction as the rows it describes, so a failed
-- import - whether it fails before ever reaching that transaction, or
-- partway through it - never leaves a batch with no matching rows, or a
-- row_count that disagrees with what actually landed.
CREATE TABLE IF NOT EXISTS import_batches (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  kind              TEXT NOT NULL,
  source_file       TEXT,
  file_hash         TEXT,
  date_range_start  TEXT,
  date_range_end    TEXT,
  row_count         INTEGER NOT NULL,
  imported_at       TEXT NOT NULL,
  notes             TEXT
);

CREATE TABLE IF NOT EXISTS account_balance_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  as_of_date    TEXT NOT NULL,
  balance_cad   REAL NOT NULL,     -- always a positive magnitude; accounts.kind decides the sign
                                    -- for net worth math (networth.py's ASSET_KINDS/LIABILITY_KINDS)
  source        TEXT NOT NULL,     -- 'manual' | 'import' (room for a future Plaid/API source, Part B)
  batch_id      INTEGER REFERENCES import_batches(id),
  recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_account_date ON account_balance_snapshots(account_id, as_of_date);

-- A line of credit's rate/limit, split from its balance because they
-- change on a much slower cadence (a rate hike, a new limit) than the
-- balance does (every statement) - written only when a term changes.
CREATE TABLE IF NOT EXISTS account_terms_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  as_of_date    TEXT NOT NULL,
  interest_rate REAL,
  credit_limit  REAL,
  recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_terms_snapshots_account_date ON account_terms_snapshots(account_id, as_of_date);

-- "Current" balance per account - what Cash/Bitcoin/Debt/Lines of
-- Credit will render (Phase 3). A view, not a cached column, so it can
-- never drift out of sync with account_balance_snapshots. Ties broken
-- by recorded_at then id, both descending, so a same-day correction (two
-- snapshots sharing an as_of_date - C8) always resolves to whichever was
-- written most recently, deterministically.
CREATE VIEW IF NOT EXISTS latest_account_balances AS
SELECT id, account_id, as_of_date, balance_cad, source, batch_id, recorded_at
FROM (
  SELECT s.*,
         ROW_NUMBER() OVER (
           PARTITION BY account_id
           ORDER BY as_of_date DESC, recorded_at DESC, id DESC
         ) AS rn
  FROM account_balance_snapshots s
)
WHERE rn = 1;
