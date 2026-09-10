"""Cross-schema integrity checks for both SQLite databases (tasks.db and
finance.db). These make the guarantees each module's migrate() relies on
explicit - a broken migration or an accidentally dropped index/view fails
a test here instead of surfacing later as corrupted data or a silent
missing feature. See issue #149, "Add cross-schema integrity checks and
migration fixtures".

Migration-path fixtures for a *specific* old schema (a database from
before some particular column/version existed) live next to the module
they migrate: backend/tests/test_tasks_db.py's TestSchemaMigrations and
backend/finance/tests/test_db.py's TestPositionalIdMigration/
TestNetworthColumnsMigration/TestBtcQuantityColumnMigration. This file is
about the schema-agnostic checks that apply to any current database,
whichever path it took to get there.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'finance'))

import tasks_db  # noqa: E402
import db as finance_db  # noqa: E402


TASKS_TABLES = {'sections', 'tasks', 'tags', 'scratchpad'}
TASKS_INDEXES = {'idx_tasks_section', 'idx_tasks_parent', 'idx_tags_task'}

FINANCE_TABLES = {
    'accounts', 'transactions', 'transaction_category_overrides',
    'merchant_category_overrides', 'cash_flow_exclusions', 'import_batches',
    'account_balance_snapshots', 'account_terms_snapshots',
}
FINANCE_VIEWS = {'transactions_effective', 'latest_account_balances'}
FINANCE_INDEXES = {
    'idx_transactions_account_date', 'idx_transactions_category',
    'idx_balance_snapshots_account_date', 'idx_terms_snapshots_account_date',
}


def _names(conn, sqlite_type):
    return {
        row['name']
        for row in conn.execute('SELECT name FROM sqlite_master WHERE type = ?', (sqlite_type,))
    }


class _IntegrityChecks:
    """Shared assertions for a fresh, current database. A mixin rather than
    a TestCase subclass, so unittest doesn't try to collect and run it on
    its own (MODULE/DB_FILENAME are unset here) - only the concrete
    per-database classes below, which combine this with unittest.TestCase.
    """

    MODULE = None
    DB_FILENAME = None

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = self.MODULE.connect(os.path.join(self.tmp_dir.name, self.DB_FILENAME))
        self.MODULE.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_integrity_check_passes(self):
        rows = self.conn.execute('PRAGMA integrity_check').fetchall()
        self.assertEqual([row[0] for row in rows], ['ok'])

    def test_foreign_key_check_reports_no_violations(self):
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_foreign_keys_are_enabled_on_this_connection(self):
        """connect() always turns this on - a bare sqlite3.connect() leaves
        it off by default, which would let every ON DELETE rule and every
        REFERENCES clause in the schema silently do nothing."""
        self.assertEqual(self.conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)

    def test_schema_version_is_current(self):
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(version, self.MODULE.SCHEMA_VERSION)

    def test_repeated_init_schema_does_not_break_integrity(self):
        self.MODULE.init_schema(self.conn)
        self.MODULE.init_schema(self.conn)
        rows = self.conn.execute('PRAGMA integrity_check').fetchall()
        self.assertEqual([row[0] for row in rows], ['ok'])
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(version, self.MODULE.SCHEMA_VERSION)


class TestTasksSchemaIntegrity(_IntegrityChecks, unittest.TestCase):
    MODULE = tasks_db
    DB_FILENAME = 'tasks.db'

    def test_expected_tables_exist(self):
        self.assertTrue(TASKS_TABLES <= _names(self.conn, 'table'))

    def test_expected_indexes_exist(self):
        self.assertTrue(TASKS_INDEXES <= _names(self.conn, 'index'))


class TestFinanceSchemaIntegrity(_IntegrityChecks, unittest.TestCase):
    MODULE = finance_db
    DB_FILENAME = 'finance.db'

    def test_expected_tables_exist(self):
        self.assertTrue(FINANCE_TABLES <= _names(self.conn, 'table'))

    def test_expected_views_exist(self):
        self.assertTrue(FINANCE_VIEWS <= _names(self.conn, 'view'))

    def test_expected_indexes_exist(self):
        self.assertTrue(FINANCE_INDEXES <= _names(self.conn, 'index'))


if __name__ == '__main__':
    unittest.main()
