import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import import_csv  # noqa: E402


CC_HEADER = 'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'


class TestLastImportedAt(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_none_when_nothing_imported_yet(self):
        self.assertIsNone(finance_db.last_imported_at(self.conn))

    def test_returns_the_most_recent_import_timestamp(self):
        text = CC_HEADER + '2026-09-01,Purchase,Completed,Cafe,-5.00,CAD,,Coffee\n'
        import_csv.import_csv_text(self.conn, 'first.csv', text)
        first = finance_db.last_imported_at(self.conn)
        self.assertIsNotNone(first)

        # A later import (even of unrelated, non-overlapping data) should
        # move the timestamp forward, not just report the first import's.
        later_text = CC_HEADER + '2026-08-01,Purchase,Completed,Diner,-20.00,CAD,,Restaurants\n'
        import_csv.import_csv_text(self.conn, 'second.csv', later_text)
        second = finance_db.last_imported_at(self.conn)
        self.assertIsNotNone(second)
        self.assertGreaterEqual(second, first)


class TestTransactionExists(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_false_for_unknown_id(self):
        self.assertFalse(finance_db.transaction_exists(self.conn, 'no-such-id'))

    def test_true_for_a_real_transaction(self):
        text = CC_HEADER + '2026-09-01,Purchase,Completed,Cafe,-5.00,CAD,,Coffee\n'
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        self.assertTrue(finance_db.transaction_exists(
            self.conn, finance_db.transaction_id('main-credit-card', '2026-09-01', 'Cafe', -5.00, 'Purchase', 0)))


class TestCategoryOverrideSetters(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_set_transaction_override_inserts_a_row(self):
        finance_db.set_transaction_category_override(self.conn, 'tx1', 'Food', '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT category FROM transaction_category_overrides WHERE transaction_id = ?', ('tx1',)
        ).fetchone()
        self.assertEqual(row['category'], 'Food')

    def test_set_transaction_override_twice_updates_not_duplicates(self):
        finance_db.set_transaction_category_override(self.conn, 'tx1', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_transaction_category_override(self.conn, 'tx1', 'Gifts', '2026-09-07T00:00:00Z')
        rows = self.conn.execute(
            'SELECT category FROM transaction_category_overrides WHERE transaction_id = ?', ('tx1',)
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['category'], 'Gifts')

    def test_empty_category_removes_the_transaction_override(self):
        finance_db.set_transaction_category_override(self.conn, 'tx1', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_transaction_category_override(self.conn, 'tx1', '', '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT * FROM transaction_category_overrides WHERE transaction_id = ?', ('tx1',)
        ).fetchone()
        self.assertIsNone(row)

    def test_set_merchant_override_inserts_a_row(self):
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT category FROM merchant_category_overrides WHERE description = ?', ('Tim Hortons',)
        ).fetchone()
        self.assertEqual(row['category'], 'Food')

    def test_empty_category_removes_the_merchant_override(self):
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', '', '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT * FROM merchant_category_overrides WHERE description = ?', ('Tim Hortons',)
        ).fetchone()
        self.assertIsNone(row)


class TestCashFlowExclusionSetter(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_excluding_a_transaction_inserts_a_row(self):
        finance_db.set_cash_flow_exclusion(self.conn, 'tx1', True, 'Reimbursement', '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT reason FROM cash_flow_exclusions WHERE transaction_id = ?', ('tx1',)
        ).fetchone()
        self.assertEqual(row['reason'], 'Reimbursement')

    def test_excluding_twice_updates_not_duplicates(self):
        finance_db.set_cash_flow_exclusion(self.conn, 'tx1', True, 'First reason', '2026-09-06T00:00:00Z')
        finance_db.set_cash_flow_exclusion(self.conn, 'tx1', True, 'Second reason', '2026-09-07T00:00:00Z')
        rows = self.conn.execute(
            'SELECT reason FROM cash_flow_exclusions WHERE transaction_id = ?', ('tx1',)
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reason'], 'Second reason')

    def test_unexcluding_removes_the_row(self):
        finance_db.set_cash_flow_exclusion(self.conn, 'tx1', True, 'Reimbursement', '2026-09-06T00:00:00Z')
        finance_db.set_cash_flow_exclusion(self.conn, 'tx1', False, None, '2026-09-06T00:00:00Z')
        row = self.conn.execute(
            'SELECT * FROM cash_flow_exclusions WHERE transaction_id = ?', ('tx1',)
        ).fetchone()
        self.assertIsNone(row)


class TestPositionalIdMigration(unittest.TestCase):
    """Migration 1 (db._rewrite_positional_transaction_ids): moves an
    existing database off the old positional ids without orphaning the
    corrections attached to them."""

    OLD_COFFEE = 'main-credit-card:2026-09-02:0'
    OLD_HOTEL = 'main-credit-card:2026-09-02:1'

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        finance_db.init_schema(self.conn)

        self.conn.execute(
            "INSERT INTO accounts (id, label, institution, kind) VALUES ('main-credit-card', 'Credit Card', NULL, 'credit_card')"
        )
        self.conn.executemany(
            '''INSERT INTO transactions
               (id, account_id, date, description, amount, activity_type, category, status, source_file, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                (self.OLD_COFFEE, 'main-credit-card', '2026-09-02', 'Coffee Shop', -5.0,
                 'Purchase', 'Coffee', 'Completed', 'v1.csv', '2026-09-06T00:00:00Z'),
                (self.OLD_HOTEL, 'main-credit-card', '2026-09-02', 'Big Hotel', -450.0,
                 'Purchase', 'Hotels', 'Completed', 'v1.csv', '2026-09-06T00:00:00Z'),
            ],
        )
        self.conn.execute(
            "INSERT INTO transaction_category_overrides VALUES (?, 'Vacation', '2026-09-06T00:00:00Z')",
            (self.OLD_HOTEL,),
        )
        self.conn.execute(
            "INSERT INTO cash_flow_exclusions VALUES (?, 'reimbursed', '2026-09-06T00:00:00Z')",
            (self.OLD_COFFEE,),
        )
        # init_schema already migrated the (empty) database, so wind the
        # version back to stage a genuinely pre-migration one.
        self.conn.execute('PRAGMA user_version = 0')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def new_id(self, description, amount):
        return finance_db.transaction_id('main-credit-card', '2026-09-02', description, amount, 'Purchase', 0)

    def test_rewrites_ids_to_the_content_derived_form(self):
        finance_db.migrate(self.conn)
        ids = {r['description']: r['id'] for r in self.conn.execute('SELECT id, description FROM transactions')}
        self.assertEqual(ids['Coffee Shop'], self.new_id('Coffee Shop', -5.0))
        self.assertEqual(ids['Big Hotel'], self.new_id('Big Hotel', -450.0))

    def test_carries_the_category_override_onto_the_new_id(self):
        finance_db.migrate(self.conn)
        categories = {
            r['description']: r['effective_category']
            for r in self.conn.execute('SELECT description, effective_category FROM transactions_effective')
        }
        self.assertEqual(categories['Big Hotel'], 'Vacation')
        self.assertEqual(categories['Coffee Shop'], 'Coffee')

    def test_carries_the_cash_flow_exclusion_onto_the_new_id(self):
        finance_db.migrate(self.conn)
        excluded = self.conn.execute(
            'SELECT t.description FROM cash_flow_exclusions e JOIN transactions t ON t.id = e.transaction_id'
        ).fetchall()
        self.assertEqual([r['description'] for r in excluded], ['Coffee Shop'])

    def test_leaves_no_orphaned_corrections(self):
        finance_db.migrate(self.conn)
        orphans = self.conn.execute(
            '''SELECT COUNT(*) AS n FROM transaction_category_overrides o
               LEFT JOIN transactions t ON t.id = o.transaction_id WHERE t.id IS NULL'''
        ).fetchone()
        self.assertEqual(orphans['n'], 0)

    def test_is_idempotent(self):
        finance_db.migrate(self.conn)
        after_first = sorted(r['id'] for r in self.conn.execute('SELECT id FROM transactions'))

        finance_db.migrate(self.conn)
        self.assertEqual(sorted(r['id'] for r in self.conn.execute('SELECT id FROM transactions')), after_first)

    def test_records_the_schema_version_so_it_runs_once(self):
        finance_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], finance_db.SCHEMA_VERSION)


class TestNetworthColumnsMigration(unittest.TestCase):
    """Migration 2 (db._add_networth_account_columns): adds
    accounts.currency/closed_at for a database created before Part C's net
    worth tables existed, staged here as an accounts table without them -
    the shape every database had before this migration was added."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        self.conn.executescript('''
            CREATE TABLE accounts (
              id TEXT PRIMARY KEY, label TEXT NOT NULL, institution TEXT, kind TEXT NOT NULL
            );
            CREATE TABLE transactions (
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
              date TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL,
              activity_type TEXT NOT NULL, category TEXT, status TEXT,
              source_file TEXT NOT NULL, imported_at TEXT NOT NULL
            );
        ''')
        self.conn.execute(
            "INSERT INTO accounts (id, label, institution, kind) VALUES ('acc1', 'Chequing', 'TD', 'chequing')"
        )
        # Already past migration 1 (content-derived transaction ids) but not
        # yet migration 2 - the specific gap this test targets.
        self.conn.execute('PRAGMA user_version = 1')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_adds_currency_and_closed_at_columns(self):
        finance_db.migrate(self.conn)
        columns = {row[1] for row in self.conn.execute('PRAGMA table_info(accounts)')}
        self.assertIn('currency', columns)
        self.assertIn('closed_at', columns)

    def test_existing_account_rows_survive_with_the_default_currency(self):
        finance_db.migrate(self.conn)
        row = finance_db.get_account(self.conn, 'acc1')
        self.assertEqual(row['label'], 'Chequing')
        self.assertEqual(row['currency'], 'CAD')
        self.assertIsNone(row['closed_at'])

    def test_is_idempotent(self):
        finance_db.migrate(self.conn)
        finance_db.migrate(self.conn)
        columns = [row[1] for row in self.conn.execute('PRAGMA table_info(accounts)')]
        self.assertEqual(columns.count('currency'), 1)

    def test_records_the_schema_version(self):
        finance_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], finance_db.SCHEMA_VERSION)


class TestBtcQuantityColumnMigration(unittest.TestCase):
    """Migration 3 (db._add_transaction_btc_quantity_column): adds the
    nullable transactions.btc_quantity column, staged here as a
    transactions table without it - the shape every database had before
    the Shakepay round-up import needed somewhere to record it."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        self.conn.executescript('''
            CREATE TABLE accounts (
              id TEXT PRIMARY KEY, label TEXT NOT NULL, institution TEXT, kind TEXT NOT NULL,
              currency TEXT NOT NULL DEFAULT 'CAD', closed_at TEXT
            );
            CREATE TABLE transactions (
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
              date TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL,
              activity_type TEXT NOT NULL, category TEXT, status TEXT,
              source_file TEXT NOT NULL, imported_at TEXT NOT NULL
            );
        ''')
        self.conn.execute(
            "INSERT INTO accounts (id, label, institution, kind) VALUES ('acc1', 'Credit Card', NULL, 'credit_card')"
        )
        self.conn.execute(
            '''INSERT INTO transactions
               (id, account_id, date, description, amount, activity_type, source_file, imported_at)
               VALUES ('tx1', 'acc1', '2026-09-01', 'Coffee', -5.0, 'Purchase', 'v1.csv', '2026-09-06T00:00:00Z')'''
        )
        self.conn.execute('PRAGMA user_version = 2')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_adds_btc_quantity_column(self):
        finance_db.migrate(self.conn)
        columns = {row[1] for row in self.conn.execute('PRAGMA table_info(transactions)')}
        self.assertIn('btc_quantity', columns)

    def test_existing_transaction_rows_survive_with_null_btc_quantity(self):
        finance_db.migrate(self.conn)
        row = self.conn.execute('SELECT * FROM transactions WHERE id = ?', ('tx1',)).fetchone()
        self.assertEqual(row['description'], 'Coffee')
        self.assertIsNone(row['btc_quantity'])

    def test_is_idempotent(self):
        finance_db.migrate(self.conn)
        finance_db.migrate(self.conn)
        columns = [row[1] for row in self.conn.execute('PRAGMA table_info(transactions)')]
        self.assertEqual(columns.count('btc_quantity'), 1)

    def test_records_the_schema_version(self):
        finance_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], finance_db.SCHEMA_VERSION)


class TestAccountKindConstraint(unittest.TestCase):
    """Issue: finance account/source domain integrity. accounts.kind is a
    CLOSED domain (csv_schema.sql) - a fresh database rejects anything
    outside db.ACCOUNT_KINDS directly."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_accepts_every_known_kind(self):
        for i, kind in enumerate(sorted(finance_db.ACCOUNT_KINDS)):
            finance_db.upsert_account(self.conn, 'acc%d' % i, 'Label', None, kind)

    def test_rejects_an_unknown_kind(self):
        with self.assertRaises(sqlite3.IntegrityError):
            finance_db.upsert_account(self.conn, 'acc1', 'Label', None, 'crypto_stash')


class TestAccountKindConstraintMigration(unittest.TestCase):
    """Migration 4 (db._add_account_kind_constraint): rebuilds accounts
    with the kind CHECK constraint, staged here as the unconstrained shape
    every finance.db had before this migration - one account plus rows in
    every table that references accounts(id), so the rebuild's foreign
    keys have something real to preserve."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        self.conn.executescript('''
            CREATE TABLE accounts (
              id TEXT PRIMARY KEY, label TEXT NOT NULL, institution TEXT, kind TEXT NOT NULL,
              currency TEXT NOT NULL DEFAULT 'CAD', closed_at TEXT
            );
            CREATE TABLE transactions (
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
              date TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL,
              activity_type TEXT NOT NULL, category TEXT, status TEXT, btc_quantity REAL,
              source_file TEXT NOT NULL, imported_at TEXT NOT NULL
            );
            CREATE TABLE import_batches (
              id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source_file TEXT,
              file_hash TEXT, date_range_start TEXT, date_range_end TEXT, row_count INTEGER NOT NULL,
              imported_at TEXT NOT NULL, notes TEXT
            );
            CREATE TABLE account_balance_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(id),
              as_of_date TEXT NOT NULL, balance_cad REAL NOT NULL, source TEXT NOT NULL,
              batch_id INTEGER REFERENCES import_batches(id), recorded_at TEXT NOT NULL
            );
        ''')
        self.conn.execute(
            "INSERT INTO accounts (id, label, institution, kind) VALUES ('acc1', 'Chequing', 'TD', 'chequing')"
        )
        self.conn.execute(
            '''INSERT INTO transactions (id, account_id, date, description, amount, activity_type, source_file, imported_at)
               VALUES ('tx1', 'acc1', '2026-09-01', 'Coffee', -5.0, 'Purchase', 'v1.csv', '2026-09-06T00:00:00Z')'''
        )
        self.conn.execute(
            "INSERT INTO account_balance_snapshots (account_id, as_of_date, balance_cad, source, recorded_at) "
            "VALUES ('acc1', '2026-09-01', 100.0, 'manual', '2026-09-06T00:00:00Z')"
        )
        self.conn.execute('PRAGMA user_version = 3')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_adds_the_kind_check_constraint(self):
        finance_db.migrate(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            finance_db.upsert_account(self.conn, 'bad', 'Label', None, 'crypto_stash')

    def test_preserves_the_existing_account(self):
        finance_db.migrate(self.conn)
        self.assertEqual(finance_db.get_account(self.conn, 'acc1')['kind'], 'chequing')

    def test_preserves_rows_that_reference_the_account(self):
        finance_db.migrate(self.conn)
        self.assertTrue(finance_db.transaction_exists(self.conn, 'tx1'))
        snapshot = self.conn.execute('SELECT * FROM account_balance_snapshots WHERE account_id = ?', ('acc1',)).fetchone()
        self.assertEqual(snapshot['balance_cad'], 100.0)

    def test_foreign_keys_are_intact_after_the_rebuild(self):
        finance_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_is_idempotent(self):
        finance_db.migrate(self.conn)
        finance_db.migrate(self.conn)
        self.assertEqual(finance_db.get_account(self.conn, 'acc1')['kind'], 'chequing')

    def test_records_the_schema_version(self):
        finance_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], finance_db.SCHEMA_VERSION)

    def test_refuses_to_migrate_an_unrecognized_existing_kind(self):
        """An unknown kind already in the data can't be safely guessed as
        an asset or a liability - the migration must refuse rather than
        pick a side, and leave the version/data exactly as they were."""
        self.conn.execute("UPDATE accounts SET kind = 'crypto_stash' WHERE id = 'acc1'")
        self.conn.commit()

        with self.assertRaises(RuntimeError):
            finance_db.migrate(self.conn)

        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], 3)
        self.assertEqual(finance_db.get_account(self.conn, 'acc1')['kind'], 'crypto_stash')


if __name__ == '__main__':
    unittest.main()
