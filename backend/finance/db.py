"""SQLite storage for CSV-imported finance transactions (see
finance/ARCHITECTURE.md Part A). A separate database from data/tasks.db -
this one holds real personal financial data and lives entirely under
data/finance/, which is gitignored, unlike the tasks database.
"""

import hashlib
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'finance')
DB_PATH = os.path.join(DATA_DIR, 'finance.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'csv_schema.sql')

# Bumped whenever a one-time migration is added below; tracked per
# database in PRAGMA user_version so each migration runs exactly once.
SCHEMA_VERSION = 3

ID_DIGEST_LENGTH = 12


def connect(path=None):
    """A connection for one unit of work. Callers close it when done."""
    path = path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_schema(conn):
    """Brings a database fully up to date: the DDL, then any one-time
    migrations it hasn't had yet. Every setup path goes through here
    (server startup, the CLI/upload import, tests), so no caller can end
    up on a database whose schema is current but whose data isn't."""
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    # A property of the file itself, so this sticks for every later
    # connection rather than needing to be re-set per request.
    conn.execute('PRAGMA journal_mode = WAL')
    conn.commit()
    migrate(conn)


def migrate(conn):
    """Applies the migrations this database is behind on, in order."""
    version = conn.execute('PRAGMA user_version').fetchone()[0]

    if version < 1:
        _rewrite_positional_transaction_ids(conn)

    if version < 2:
        _add_networth_account_columns(conn)

    if version < 3:
        _add_transaction_btc_quantity_column(conn)

    if version < SCHEMA_VERSION:
        # No bind parameters allowed in a PRAGMA, and SCHEMA_VERSION is
        # our own int constant, never user input.
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        conn.commit()


def transaction_id(account_id, date, description, amount, activity_type, occurrence):
    """A transaction's primary key, derived from what the transaction
    *is* rather than where it happened to sit in the imported file.

    Ids used to be positional (`account:date:N`, N being the row's index
    within its date), which meant any newly-appearing row on an
    already-imported date shifted every id after it - silently
    re-pointing the category overrides and cash flow exclusions keyed to
    those ids at different transactions. Hashing the identifying fields
    instead keeps an id attached to its transaction no matter what else
    shows up on the same day.

    `status` is deliberately not hashed: a Pending charge posting as
    Completed is the same transaction, and must keep the same id. Nor is
    `category`, since correcting a category must not move the row that
    correction is attached to. `occurrence` separates rows that really
    are identical - two separate $2.94 charges at one merchant on one day
    are a real case (ARCHITECTURE.md A3), and each needs its own id.
    """
    fingerprint = f'{date}|{description}|{amount:.2f}|{activity_type}'
    digest = hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:ID_DIGEST_LENGTH]
    return f'{account_id}:{date}:{digest}:{occurrence}'


def _rewrite_positional_transaction_ids(conn):
    """Migration 1: moves existing rows off the old positional ids onto
    transaction_id()'s content-derived ones, carrying every category
    override and cash flow exclusion across to the new id as it goes.

    Without this the id format change would orphan every correction
    already made - the same silent breakage the new format exists to
    prevent, just triggered once by the upgrade instead of by each
    re-import.
    """
    rows = conn.execute(
        '''SELECT id, account_id, date, description, amount, activity_type
           FROM transactions
           ORDER BY account_id, date, id'''
    ).fetchall()

    # Ordering by the old positional id reproduces the row order within
    # each date that the original import saw, so occurrence numbering
    # here lands the same way import_csv's does for identical rows.
    occurrences = {}
    remapped = []
    for r in rows:

        key = (r['account_id'], r['date'], r['description'], r['amount'], r['activity_type'])
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1

        new_id = transaction_id(*key, occurrence)
        if new_id != r['id']:
            remapped.append((r['id'], new_id))

    for old_id, new_id in remapped:

        conn.execute('UPDATE transactions SET id = ? WHERE id = ?', (new_id, old_id))
        conn.execute(
            'UPDATE transaction_category_overrides SET transaction_id = ? WHERE transaction_id = ?',
            (new_id, old_id),
        )
        conn.execute(
            'UPDATE cash_flow_exclusions SET transaction_id = ? WHERE transaction_id = ?',
            (new_id, old_id),
        )
    conn.commit()


def _add_networth_account_columns(conn):
    """Migration 2: adds accounts.currency/closed_at for databases created
    before Part C's net worth tables existed (ARCHITECTURE.md C5a/C10
    Phase 1). A fresh database's accounts table already has both columns
    (csv_schema.sql), since CREATE TABLE IF NOT EXISTS is a no-op against
    a table that already exists but says nothing about its columns - so
    this checks what's actually there rather than assuming either state.
    """
    existing = {row[1] for row in conn.execute('PRAGMA table_info(accounts)')}
    if 'currency' not in existing:
        conn.execute("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'CAD'")
    if 'closed_at' not in existing:
        conn.execute('ALTER TABLE accounts ADD COLUMN closed_at TEXT')
    conn.commit()


def _add_transaction_btc_quantity_column(conn):
    """Migration 3: adds transactions.btc_quantity, nullable, for the
    monthly-BTC-accumulated-from-round-ups figure (finance/README.md).
    Only import_shakepay.py's ROUNDUP_BUY rows ever populate it; every
    other row (CAD-only, or a pre-existing row from before this column
    existed) simply has NULL here, same "check what's actually there"
    reasoning as _add_networth_account_columns above."""
    existing = {row[1] for row in conn.execute('PRAGMA table_info(transactions)')}
    if 'btc_quantity' not in existing:
        conn.execute('ALTER TABLE transactions ADD COLUMN btc_quantity REAL')
    conn.commit()


def ensure_database(path=None):
    """Create the database and its schema if they don't exist yet. Called
    once at server startup, same pattern as tasks_db.ensure_database()."""
    conn = connect(path)

    try:
        init_schema(conn)
    finally:
        conn.close()


def upsert_account(conn, account_id, label, institution, kind):
    conn.execute(
        '''INSERT INTO accounts (id, label, institution, kind)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             label = excluded.label,
             institution = excluded.institution,
             kind = excluded.kind''',
        (account_id, label, institution, kind),
    )


def get_account(conn, account_id):
    row = conn.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
    return dict(row) if row else None


def replace_transactions_in_range(conn, account_id, date_start, date_end, rows):
    """Range-replace load (see ARCHITECTURE.md Part A3): delete every
    existing row for this account whose date falls within the newly
    imported file's own date range, then insert the file's rows fresh.
    Neither export format carries a stable per-row transaction id, so this
    is what makes re-importing an overlapping or identical export
    idempotent instead of relying on fragile per-row matching (same-day
    duplicate amounts are common in the credit card export, e.g. two
    separate McDonald's charges on one day)."""
    conn.execute(
        'DELETE FROM transactions WHERE account_id = ? AND date BETWEEN ? AND ?',
        (account_id, date_start, date_end),
    )
    conn.executemany(
        '''INSERT INTO transactions
           (id, account_id, date, description, amount, activity_type, category, status, btc_quantity, source_file, imported_at)
           VALUES (:id, :account_id, :date, :description, :amount, :activity_type, :category, :status, :btc_quantity, :source_file, :imported_at)''',
        rows,
    )


def account_transaction_count(conn, account_id):
    row = conn.execute('SELECT COUNT(*) AS n FROM transactions WHERE account_id = ?', (account_id,)).fetchone()
    return row['n']


def last_imported_at(conn):
    """The most recent imported_at across every transaction row, or None
    if nothing has been imported yet - what the dashboard's "data last
    imported" indicator (finance/ARCHITECTURE.md) shows."""
    row = conn.execute('SELECT MAX(imported_at) AS latest FROM transactions').fetchone()
    return row['latest']


def transaction_exists(conn, transaction_id):
    row = conn.execute('SELECT 1 FROM transactions WHERE id = ?', (transaction_id,)).fetchone()
    return row is not None


def set_transaction_category_override(conn, transaction_id, category, updated_at):
    """The "one-time" fix (see csv_schema.sql): recolors exactly this one
    transaction. `category` empty/None removes the override, reverting to
    whatever transactions_effective would otherwise resolve to (a merchant
    override if one exists, else the original stored category)."""
    if category:
        conn.execute(
            '''INSERT INTO transaction_category_overrides (transaction_id, category, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(transaction_id) DO UPDATE SET
                 category = excluded.category, updated_at = excluded.updated_at''',
            (transaction_id, category, updated_at),
        )
    else:
        conn.execute('DELETE FROM transaction_category_overrides WHERE transaction_id = ?', (transaction_id,))


def set_merchant_category_override(conn, description, category, updated_at):
    """The "permanent" fix (see csv_schema.sql): recolors every transaction,
    past and future, whose description exactly matches. `category`
    empty/None removes the override."""
    if category:
        conn.execute(
            '''INSERT INTO merchant_category_overrides (description, category, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(description) DO UPDATE SET
                 category = excluded.category, updated_at = excluded.updated_at''',
            (description, category, updated_at),
        )
    else:
        conn.execute('DELETE FROM merchant_category_overrides WHERE description = ?', (description,))


def create_import_batch(conn, kind, imported_at, source_file=None, file_hash=None,
                         date_range_start=None, date_range_end=None, row_count=1, notes=None):
    """One row per fact-producing event - a manual balance/holding entry
    today, a future net-worth CSV import later (ARCHITECTURE.md C3).
    Returns the new batch's id."""
    cursor = conn.execute(
        '''INSERT INTO import_batches
           (kind, source_file, file_hash, date_range_start, date_range_end, row_count, imported_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (kind, source_file, file_hash, date_range_start, date_range_end, row_count, imported_at, notes),
    )
    return cursor.lastrowid


def insert_balance_snapshot(conn, account_id, as_of_date, balance_cad, source, batch_id, recorded_at):
    """Appends one account_balance_snapshots row - never an update, per
    ARCHITECTURE.md C2's append-only rule. `balance_cad` is always a
    positive magnitude (C5a); `latest_account_balances` is "current"."""
    cursor = conn.execute(
        '''INSERT INTO account_balance_snapshots (account_id, as_of_date, balance_cad, source, batch_id, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (account_id, as_of_date, balance_cad, source, batch_id, recorded_at),
    )
    return cursor.lastrowid


def insert_terms_snapshot(conn, account_id, as_of_date, interest_rate, credit_limit, recorded_at):
    """Appends one account_terms_snapshots row (a line of credit's rate/
    limit) - only called when a term is actually given, not on every
    balance update (ARCHITECTURE.md C5d)."""
    cursor = conn.execute(
        '''INSERT INTO account_terms_snapshots (account_id, as_of_date, interest_rate, credit_limit, recorded_at)
           VALUES (?, ?, ?, ?, ?)''',
        (account_id, as_of_date, interest_rate, credit_limit, recorded_at),
    )
    return cursor.lastrowid


def set_cash_flow_exclusion(conn, transaction_id, is_excluded, reason, created_at):
    """Marks (or unmarks) one transaction as excluded from Cash Flow's
    income/expense totals (see csv_schema.sql's cash_flow_exclusions).
    `is_excluded=False` removes the exclusion."""
    if is_excluded:
        conn.execute(
            '''INSERT INTO cash_flow_exclusions (transaction_id, reason, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(transaction_id) DO UPDATE SET
                 reason = excluded.reason, created_at = excluded.created_at''',
            (transaction_id, reason, created_at),
        )
    else:
        conn.execute('DELETE FROM cash_flow_exclusions WHERE transaction_id = ?', (transaction_id,))
