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
SCHEMA_VERSION = 5

ID_DIGEST_LENGTH = 12

# The single source of truth for accounts.kind - a CLOSED domain (see
# csv_schema.sql's classification comment): every value net worth math
# knows how to sign. networth.py's ASSET_KINDS/LIABILITY_KINDS partition
# this exact set (and assert as much, so the two can't quietly drift
# apart) rather than each defining their own - db.py can't import
# networth.py, which already imports db as finance_db, so this lives here
# and networth.py reads it instead of the schema owning two independent
# copies of the same list.
ACCOUNT_KINDS = frozenset({
    'chequing', 'savings', 'investment', 'bitcoin_wallet',
    'credit_card', 'line_of_credit', 'loan', 'bill',
})

# --- Financial value storage: containment, not elimination, of binary
# float imprecision --------------------------------------------------------
#
# transactions.amount/account_balance_snapshots.balance_cad/
# account_terms_snapshots.interest_rate/credit_limit and
# transactions.btc_quantity are all SQLite REAL (IEEE 754 double), not an
# integer-cents/integer-satoshis representation. Binary floating point
# cannot exactly represent most decimal fractions (0.1 has no exact double
# value), so this is a deliberate choice to contain that imprecision at a
# fixed, documented precision rather than eliminate it outright with an
# integer column type - the latter would mean every import path, every
# summary.py aggregation query, and the JSON contract every finance page
# already reads (whole-dollar-and-cents floats) changing in lockstep, for
# a personal-scale ledger where "off by a fraction of a cent in a value
# nothing compares with `==`" has never been an observed problem.
#
# The containment: every value is rounded to its canonical precision at
# the moment it's about to be written (ROUND_CAD_DECIMALS for anything in
# CAD, ROUND_BTC_DECIMALS for btc_quantity - see round_cad()/round_btc()
# below), so imprecision never accumulates across re-imports or repeated
# arithmetic. Reads that aggregate (SUM, in summary.py) round again at
# output time for the same reason. Nothing compares two of these values
# with `==` for equality - transaction_id() formats amount with `.2f`
# specifically so its content-derived hash depends on the canonical
# rounded value, never on whatever binary noise floats past two decimal
# places.
ROUND_CAD_DECIMALS = 2
ROUND_BTC_DECIMALS = 8


def round_cad(amount):
    """Canonical precision for any CAD-denominated value (transaction
    amounts, balances, credit limits) - None passes through unchanged,
    since several of these columns are nullable (e.g. account_terms_
    snapshots.credit_limit) and None means "not given," not zero."""
    return None if amount is None else round(amount, ROUND_CAD_DECIMALS)


def round_btc(quantity):
    """Canonical precision for a Bitcoin quantity (transactions.
    btc_quantity) - eight decimal places, a satoshi. None passes through
    unchanged: every non-Shakepay-round-up row has no BTC quantity at
    all, not zero."""
    return None if quantity is None else round(quantity, ROUND_BTC_DECIMALS)


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

    if version < 4:
        _add_account_kind_constraint(conn)

    if version < 5:
        _add_cad_only_currency_constraint(conn)

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


def _add_account_kind_constraint(conn):
    """Migration 4: adds the accounts.kind CHECK constraint (ACCOUNT_KINDS
    above; see csv_schema.sql's domain classification comment). SQLite
    can't ALTER TABLE to add a CHECK constraint, so this rebuilds accounts
    the way tasks_db._add_task_domain_constraints rebuilds tasks/tags:
    create the constrained shape under a temporary name, copy data across,
    drop the original, rename into place - SQLite's own documented
    procedure for a schema change ALTER TABLE can't express
    (https://www.sqlite.org/lang_altertable.html).

    Unlike that migration, there is no normalization pass first: an
    unrecognized status/priority has an obvious safe default, but an
    unrecognized account kind does not - guessing asset vs. liability for
    a kind nothing else in the codebase produces risks silently
    corrupting net worth math, the exact failure mode this constraint
    exists to prevent. If one somehow exists, this raises and leaves the
    database exactly as it was (see the transaction/foreign_key_check
    handling below) rather than picking a side for it.

    transactions, account_balance_snapshots, and account_terms_snapshots
    all declare `REFERENCES accounts(id)` but are not touched here: that
    reference is by table name, and accounts keeps its name throughout
    (recreated, then renamed back to it) - foreign keys are still turned
    off for the duration, since SQLite validates a REFERENCES clause
    against whatever table currently holds that name, and there's a
    window here where "accounts" briefly doesn't exist at all.
    """
    unknown = conn.execute(
        'SELECT DISTINCT kind FROM accounts WHERE kind NOT IN (%s)'
        % ', '.join('?' for _ in ACCOUNT_KINDS),
        tuple(ACCOUNT_KINDS),
    ).fetchall()
    if unknown:
        raise RuntimeError(
            'refusing to add the accounts.kind constraint: unrecognized kind(s) %s already stored - '
            'reclassify or remove those accounts by hand first, since this migration cannot safely '
            'guess whether an unknown kind counts as an asset or a liability.'
            % sorted(row['kind'] for row in unknown)
        )

    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('BEGIN')

        conn.execute('''
            CREATE TABLE accounts_new (
              id          TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              institution TEXT,
              kind        TEXT NOT NULL
                CHECK (kind IN ('credit_card', 'chequing', 'savings', 'investment', 'bitcoin_wallet',
                                 'line_of_credit', 'loan', 'bill')),
              currency    TEXT NOT NULL DEFAULT 'CAD',
              closed_at   TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO accounts_new (id, label, institution, kind, currency, closed_at)
            SELECT id, label, institution, kind, currency, closed_at FROM accounts
        ''')
        conn.execute('DROP TABLE accounts')
        conn.execute('ALTER TABLE accounts_new RENAME TO accounts')

        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            conn.execute('ROLLBACK')
            raise RuntimeError('foreign key violations after accounts rebuild: %r' % (violations,))

        conn.execute('COMMIT')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


def _add_cad_only_currency_constraint(conn):
    """Migration 5: adds the accounts.currency CHECK constraint (CAD-only
    for now - see csv_schema.sql's currency comment). Same table-rebuild
    procedure and same reasoning as _add_account_kind_constraint just
    above: no normalization pass, since a non-CAD account already in the
    data isn't something this migration can safely reinterpret as CAD -
    it refuses instead, leaving a human to decide what that account's
    balances/transactions actually mean before this constraint can land.
    """
    unknown = conn.execute("SELECT DISTINCT currency FROM accounts WHERE currency != 'CAD'").fetchall()
    if unknown:
        raise RuntimeError(
            'refusing to add the accounts.currency constraint: non-CAD currency/currencies %s already '
            'stored - this schema has no original-amount/exchange-rate modeling for a real multi-'
            'currency account yet (see csv_schema.sql), so reclassify or remove those accounts by hand '
            'first.' % sorted(row['currency'] for row in unknown)
        )

    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('BEGIN')

        conn.execute('''
            CREATE TABLE accounts_new (
              id          TEXT PRIMARY KEY,
              label       TEXT NOT NULL,
              institution TEXT,
              kind        TEXT NOT NULL
                CHECK (kind IN ('credit_card', 'chequing', 'savings', 'investment', 'bitcoin_wallet',
                                 'line_of_credit', 'loan', 'bill')),
              currency    TEXT NOT NULL DEFAULT 'CAD' CHECK (currency = 'CAD'),
              closed_at   TEXT
            )
        ''')
        conn.execute('''
            INSERT INTO accounts_new (id, label, institution, kind, currency, closed_at)
            SELECT id, label, institution, kind, currency, closed_at FROM accounts
        ''')
        conn.execute('DROP TABLE accounts')
        conn.execute('ALTER TABLE accounts_new RENAME TO accounts')

        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            conn.execute('ROLLBACK')
            raise RuntimeError('foreign key violations after accounts rebuild: %r' % (violations,))

        conn.execute('COMMIT')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


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
