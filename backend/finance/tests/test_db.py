import os
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
        self.assertTrue(finance_db.transaction_exists(self.conn, 'main-credit-card:2026-09-01:0'))


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


if __name__ == '__main__':
    unittest.main()
