-- Finance datastore schema (SQLite).
-- See ARCHITECTURE.md §3 for the design rationale behind each table.
-- Plaid's own IDs (item_id, account_id, transaction_id, ...) are used
-- directly as primary keys so syncs are plain upserts.

CREATE TABLE IF NOT EXISTS plaid_items (
  id                     TEXT PRIMARY KEY,   -- Plaid item_id
  institution_id         TEXT NOT NULL,
  institution_name       TEXT NOT NULL,
  access_token_encrypted BLOB NOT NULL,      -- never store plaintext, see ARCHITECTURE.md §6
  transactions_cursor    TEXT,               -- cursor for /transactions/sync
  status                 TEXT NOT NULL DEFAULT 'good',  -- good | login_required | error
  error_code             TEXT,
  created_at             TEXT NOT NULL,
  last_synced_at         TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  id                TEXT PRIMARY KEY,   -- Plaid account_id
  item_id           TEXT NOT NULL REFERENCES plaid_items(id),
  name              TEXT NOT NULL,
  official_name     TEXT,
  mask              TEXT,
  type              TEXT NOT NULL,      -- depository | credit | investment | loan
  subtype           TEXT,               -- checking | savings | tfsa | rrsp | credit card | ...
  current_balance   REAL,
  available_balance REAL,
  iso_currency_code TEXT,
  is_closed         INTEGER NOT NULL DEFAULT 0,
  updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accounts_item ON accounts(item_id);

CREATE TABLE IF NOT EXISTS finance_categories (
  id    TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  kind  TEXT NOT NULL,   -- income | expense | transfer
  color TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
  id                       TEXT PRIMARY KEY,   -- Plaid transaction_id
  account_id               TEXT NOT NULL REFERENCES accounts(id),
  amount                   REAL NOT NULL,
  iso_currency_code        TEXT,
  date                     TEXT NOT NULL,
  authorized_date          TEXT,
  name                     TEXT NOT NULL,
  merchant_name            TEXT,
  pending                  INTEGER NOT NULL DEFAULT 0,
  plaid_category_primary   TEXT,
  plaid_category_detailed  TEXT,
  user_category_id         TEXT REFERENCES finance_categories(id),
  notes                    TEXT NOT NULL DEFAULT '',
  created_at               TEXT NOT NULL,
  modified_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(user_category_id);

CREATE TABLE IF NOT EXISTS securities (
  id                  TEXT PRIMARY KEY,   -- Plaid security_id
  ticker_symbol       TEXT,
  name                TEXT,
  type                TEXT,
  close_price         REAL,
  close_price_as_of   TEXT
);

CREATE TABLE IF NOT EXISTS investment_holdings (
  id                  TEXT PRIMARY KEY,   -- account_id:security_id, snapshot row
  account_id          TEXT NOT NULL REFERENCES accounts(id),
  security_id         TEXT NOT NULL REFERENCES securities(id),
  quantity            REAL NOT NULL,
  institution_value   REAL,
  cost_basis          REAL,
  iso_currency_code   TEXT,
  updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_holdings_account ON investment_holdings(account_id);

CREATE TABLE IF NOT EXISTS investment_transactions (
  id           TEXT PRIMARY KEY,   -- Plaid investment_transaction_id
  account_id   TEXT NOT NULL REFERENCES accounts(id),
  security_id  TEXT REFERENCES securities(id),
  type         TEXT NOT NULL,      -- buy | sell | dividend | fee | ...
  quantity     REAL,
  price        REAL,
  amount       REAL NOT NULL,
  date         TEXT NOT NULL,
  name         TEXT
);

CREATE INDEX IF NOT EXISTS idx_invtx_account ON investment_transactions(account_id);

CREATE TABLE IF NOT EXISTS sync_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id      TEXT NOT NULL REFERENCES plaid_items(id),
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL,   -- success | error
  detail       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_log_item ON sync_log(item_id);
