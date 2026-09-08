"""SQLite storage for CSV-imported finance transactions (see
finance/ARCHITECTURE.md Part A). A separate database from data/tasks.db -
this one holds real personal financial data and lives entirely under
data/finance/, which is gitignored, unlike the tasks database.
"""

import hashlib
import os
import sqlite3

import dates

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'finance')
DB_PATH = os.path.join(DATA_DIR, 'finance.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'csv_schema.sql')

# Bumped whenever a one-time migration is added below; tracked per
# database in PRAGMA user_version so each migration runs exactly once.
SCHEMA_VERSION = 8

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

    if version < 6:
        _add_transaction_date_constraints(conn)

    if version < 7:
        _add_transaction_batch_id_column(conn)

    if version < 8:
        _add_snapshot_append_only_triggers(conn)

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


def file_hash(text):
    """A full-content hash for one import_batches row's file_hash column -
    not truncated like transaction_id's digest, since this identifies a
    whole file for audit/dedup purposes rather than needing to stay short
    inside a composite id."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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


def _add_transaction_date_constraints(conn):
    """Migration 6: adds the transactions.date/imported_at CHECK
    constraints (shape-only - see csv_schema.sql's date/timestamp
    classification comment and dates.is_iso_date's docstring for why).
    Same table-rebuild procedure as the migrations above; no
    normalization pass, for the same reason as the other two -
    reinterpreting a malformed date without human judgment about what it
    was supposed to be risks getting it silently wrong, which is exactly
    what this constraint exists to catch.
    """
    bad_dates = conn.execute(
        "SELECT DISTINCT date FROM transactions "
        "WHERE date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
    ).fetchall()
    bad_timestamps = conn.execute(
        "SELECT DISTINCT imported_at FROM transactions "
        "WHERE imported_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
        "T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'"
    ).fetchall()
    if bad_dates or bad_timestamps:
        raise RuntimeError(
            'refusing to add the transactions date/imported_at constraints: malformed date(s) %s '
            'and/or imported_at value(s) %s already stored - fix or remove those rows by hand first, '
            'since this migration cannot safely guess what a malformed date was supposed to be.'
            % (sorted(r['date'] for r in bad_dates), sorted(r['imported_at'] for r in bad_timestamps))
        )

    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('BEGIN')

        # transactions_effective (csv_schema.sql) selects from transactions
        # by name - SQLite's automatic view-reference-rewriting on RENAME
        # (the same mechanism that keeps tasks_new's self-referencing FK
        # correct after its own rename, see tasks_db._add_task_domain_
        # constraints) trips over a view whose underlying table is
        # mid-rebuild rather than merely renamed, so the view is dropped
        # and recreated verbatim around the rebuild instead of relying on
        # that rewrite here. IF EXISTS: every real database has it by this
        # point (init_schema() always runs csv_schema.sql's
        # CREATE VIEW IF NOT EXISTS before any migration), but this
        # function is also called directly against a hand-built fixture in
        # tests that only stage the tables one specific migration cares
        # about.
        conn.execute('DROP VIEW IF EXISTS transactions_effective')

        conn.execute('''
            CREATE TABLE transactions_new (
              id            TEXT PRIMARY KEY,
              account_id    TEXT NOT NULL REFERENCES accounts(id),
              date          TEXT NOT NULL
                CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
              description   TEXT NOT NULL,
              amount        REAL NOT NULL,
              activity_type TEXT NOT NULL,
              category      TEXT,
              status        TEXT,
              btc_quantity  REAL,
              source_file   TEXT NOT NULL,
              imported_at   TEXT NOT NULL
                CHECK (imported_at GLOB
                       '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
            )
        ''')
        conn.execute('''
            INSERT INTO transactions_new (
              id, account_id, date, description, amount, activity_type, category, status,
              btc_quantity, source_file, imported_at
            )
            SELECT id, account_id, date, description, amount, activity_type, category, status,
                   btc_quantity, source_file, imported_at
            FROM transactions
        ''')
        conn.execute('DROP TABLE transactions')
        conn.execute('ALTER TABLE transactions_new RENAME TO transactions')
        conn.execute('CREATE INDEX idx_transactions_account_date ON transactions(account_id, date)')
        conn.execute('CREATE INDEX idx_transactions_category ON transactions(category)')

        conn.execute('''
            CREATE VIEW transactions_effective AS
            SELECT
              t.*,
              COALESCE(tco.category, mco.category, t.category) AS effective_category
            FROM transactions t
            LEFT JOIN transaction_category_overrides tco ON tco.transaction_id = t.id
            LEFT JOIN merchant_category_overrides mco ON mco.description = t.description
        ''')

        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            conn.execute('ROLLBACK')
            raise RuntimeError('foreign key violations after transactions rebuild: %r' % (violations,))

        conn.execute('COMMIT')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


def _add_transaction_batch_id_column(conn):
    """Migration 7: adds the nullable transactions.batch_id column (see
    csv_schema.sql). A plain ALTER TABLE ADD COLUMN suffices here, unlike
    the CHECK-constraint migrations above - no table rebuild needed since
    a nullable column with no CHECK is exactly what ALTER TABLE ADD
    COLUMN can express directly. Existing transactions get NULL, not a
    reconstructed batch: there is no way to know which long-ago import
    call produced them, and inventing a batch would claim provenance the
    data doesn't actually have (see the "Legacy transactions remain
    usable with a documented null/legacy batch state" requirement this
    satisfies)."""
    existing = {row[1] for row in conn.execute('PRAGMA table_info(transactions)')}
    if 'batch_id' not in existing:
        conn.execute('ALTER TABLE transactions ADD COLUMN batch_id INTEGER REFERENCES import_batches(id)')
    conn.commit()


def _add_snapshot_append_only_triggers(conn):
    """Migration 8: adds the BEFORE UPDATE/BEFORE DELETE triggers that
    make account_balance_snapshots/account_terms_snapshots append-only as
    a database invariant rather than just a convention (see
    csv_schema.sql's comment just above those tables for the full
    reasoning and the administrative-repair procedure). CREATE TRIGGER
    IF NOT EXISTS, not a table rebuild: a trigger isn't part of a table's
    own shape, so unlike a CHECK constraint it can be added directly.

    Guarded by an actual table-existence check, not just IF NOT EXISTS on
    the trigger itself: CREATE TRIGGER ... ON <table> raises "no such
    table" outright if the table isn't there yet, unlike a column's
    REFERENCES clause (see _add_transaction_batch_id_column), which
    SQLite never validates against the target existing. Every real
    finance.db has had both tables since Part C shipped, but this keeps
    the migration honest about that assumption instead of asserting it.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    if 'account_balance_snapshots' in tables:
        conn.executescript('''
            CREATE TRIGGER IF NOT EXISTS account_balance_snapshots_no_update
            BEFORE UPDATE ON account_balance_snapshots
            BEGIN
              SELECT RAISE(ABORT, 'account_balance_snapshots is append-only - insert a new, later snapshot instead of updating an existing one');
            END;

            CREATE TRIGGER IF NOT EXISTS account_balance_snapshots_no_delete
            BEFORE DELETE ON account_balance_snapshots
            BEGIN
              SELECT RAISE(ABORT, 'account_balance_snapshots is append-only - corrections are additive, never a deletion');
            END;
        ''')

    if 'account_terms_snapshots' in tables:
        conn.executescript('''
            CREATE TRIGGER IF NOT EXISTS account_terms_snapshots_no_update
            BEFORE UPDATE ON account_terms_snapshots
            BEGIN
              SELECT RAISE(ABORT, 'account_terms_snapshots is append-only - insert a new, later snapshot instead of updating an existing one');
            END;

            CREATE TRIGGER IF NOT EXISTS account_terms_snapshots_no_delete
            BEFORE DELETE ON account_terms_snapshots
            BEGIN
              SELECT RAISE(ABORT, 'account_terms_snapshots is append-only - corrections are additive, never a deletion');
            END;
        ''')

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
    separate McDonald's charges on one day).

    date_start/date_end are validated (shape only, see dates.is_iso_date)
    before the DELETE runs: both are typically `min(dates)`/`max(dates)`
    over the rows just parsed, and BETWEEN compares them lexically against
    the date column - a malformed value here (a parser regression, a stray
    non-ISO date slipping through) wouldn't just fail to match, it could
    silently delete a wrong, wildly different-shaped range of existing
    rows before the also-malformed new rows are inserted in their place.
    Refusing outright is safer than guessing at what range was meant.
    """
    if not dates.is_iso_date(date_start) or not dates.is_iso_date(date_end):
        raise ValueError(
            f'refusing to range-replace transactions for {account_id!r}: date_start={date_start!r}, '
            f'date_end={date_end!r} must both be YYYY-MM-DD dates'
        )

    conn.execute(
        'DELETE FROM transactions WHERE account_id = ? AND date BETWEEN ? AND ?',
        (account_id, date_start, date_end),
    )
    conn.executemany(
        '''INSERT INTO transactions
           (id, account_id, date, description, amount, activity_type, category, status, btc_quantity,
            source_file, imported_at, batch_id)
           VALUES (:id, :account_id, :date, :description, :amount, :activity_type, :category, :status,
                   :btc_quantity, :source_file, :imported_at, :batch_id)''',
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
