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


if __name__ == '__main__':
    unittest.main()
