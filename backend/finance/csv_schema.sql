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
  id            TEXT PRIMARY KEY,   -- account_id:date:in-file-sequence, see import_csv.py
  account_id    TEXT NOT NULL REFERENCES accounts(id),
  date          TEXT NOT NULL,
  description   TEXT NOT NULL,      -- merchant (credit card) or activity description (bank)
  amount        REAL NOT NULL,      -- negative = outflow, positive = inflow, CAD
  activity_type TEXT NOT NULL,      -- Purchase | Payment | Refund | MoneyMovement | BonusPayment | Interest
  category      TEXT,               -- issuer-provided (credit card export only), NULL otherwise
  status        TEXT,               -- Completed | Pending (credit card export only), NULL otherwise
  source_file   TEXT NOT NULL,      -- which upload this row came from, for audit
  imported_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
