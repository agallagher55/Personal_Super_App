"""SQLite storage for CSV-imported finance transactions (see
finance/ARCHITECTURE.md Part A). A separate database from data/tasks.db -
this one holds real personal financial data and lives entirely under
data/finance/, which is gitignored, unlike the tasks database.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'finance')
DB_PATH = os.path.join(DATA_DIR, 'finance.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'csv_schema.sql')


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
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    # A property of the file itself, so this sticks for every later
    # connection rather than needing to be re-set per request.
    conn.execute('PRAGMA journal_mode = WAL')
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
           (id, account_id, date, description, amount, activity_type, category, status, source_file, imported_at)
           VALUES (:id, :account_id, :date, :description, :amount, :activity_type, :category, :status, :source_file, :imported_at)''',
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
