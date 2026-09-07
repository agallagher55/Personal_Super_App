-- Schema for data/finance/finance.db (CSV-import approach, see
-- finance/ARCHITECTURE.md Part A). Deliberately separate from
-- finance/schema.sql at the repo root, which is the Plaid-oriented schema
-- for the deferred Part B plan - no access tokens, sync cursors, or other
-- Plaid-specific fields belong here.

CREATE TABLE IF NOT EXISTS accounts (
  id          TEXT PRIMARY KEY,   -- human-assigned (e.g. 'main-credit-card') or the bank export's own account_id
  label       TEXT NOT NULL,
  institution TEXT,
  kind        TEXT NOT NULL       -- credit_card | chequing | (later) investment
);

CREATE TABLE IF NOT EXISTS transactions (
  id            TEXT PRIMARY KEY,   -- account_id:date:content-digest:occurrence, see db.transaction_id
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  date          TEXT NOT NULL,
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
  source_file   TEXT NOT NULL,      -- which upload this row came from, for audit
  imported_at   TEXT NOT NULL
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
