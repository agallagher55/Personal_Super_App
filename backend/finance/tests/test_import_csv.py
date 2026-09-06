import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import import_csv  # noqa: E402


CREDIT_CARD_CSV = """transaction_date,transaction_type,status,merchant,amount,currency,notes,category
2026-09-05,Purchase,Completed,Sq *Welcome Espresso,-13.42,CAD,,Coffee
2026-09-04,Payment,Completed,,102.88,CAD,,Uncategorized
2026-09-04,Purchase,Pending,Amzn Mktp Ca,-125.34,CAD,,Other shopping
2026-08-30,Purchase,Completed,Air-Serv A An01383,-2.50,CAD,,"Gas, parking, and tolls"
2026-06-15,Refund,Completed,Airbnb * Hmraqed2Kz,445.62,CAD,,Hotels
"""

BANK_ACTIVITY_CSV = """effective_date,effective_time,settlement_date,account_id,account_type,activity_type,activity_sub_type,description,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount
2026-06-06,13:42:46,,WK1WPY033CAD,Chequing,MoneyMovement,E_TRFOUT,Interac e-Transfer® Out,,,,CAD,-75,,,-75
2026-06-08,01:00:00,,WK1WPY033CAD,Chequing,BonusPayment,CASHBACK,Cash back - Credit card,,,,CAD,0.35,,,0.35
2026-06-15,18:07:55,,WK1WPY033CAD,Chequing,MoneyMovement,TRANSFER,Credit card payment,,,,CAD,-1659.23,,,-1659.23
"""


class TestDetectKind(unittest.TestCase):

    def test_credit_card_header(self):
        reader_fields = CREDIT_CARD_CSV.splitlines()[0].split(',')
        self.assertEqual(import_csv.detect_kind(reader_fields), 'credit_card')

    def test_bank_activity_header(self):
        reader_fields = BANK_ACTIVITY_CSV.splitlines()[0].split(',')
        self.assertEqual(import_csv.detect_kind(reader_fields), 'bank_activity')

    def test_unknown_header(self):
        self.assertIsNone(import_csv.detect_kind(['foo', 'bar']))

    def test_none_fieldnames(self):
        self.assertIsNone(import_csv.detect_kind(None))


class TestParseCsvText(unittest.TestCase):

    def test_credit_card_rows(self):
        kind, account_id, label, account_kind, rows = import_csv.parse_csv_text(CREDIT_CARD_CSV)
        self.assertEqual(kind, 'credit_card')
        self.assertEqual(account_id, import_csv.DEFAULT_CREDIT_CARD_ACCOUNT)
        self.assertEqual(account_kind, 'credit_card')
        self.assertEqual(len(rows), 5)

    def test_payment_row_falls_back_to_transaction_type_for_description(self):
        # Payment rows have no merchant (paying the card bill isn't a
        # purchase from anyone) - description should still be non-blank.
        _, _, _, _, rows = import_csv.parse_csv_text(CREDIT_CARD_CSV)
        payment_row = next(r for r in rows if r['activity_type'] == 'Payment')
        self.assertEqual(payment_row['description'], 'Payment')
        self.assertEqual(payment_row['category'], 'Uncategorized')

    def test_category_with_embedded_comma_parses_correctly(self):
        # "Gas, parking, and tolls" is quoted in the source CSV - a naive
        # split(',') would mis-parse it, csv.DictReader should not.
        _, _, _, _, rows = import_csv.parse_csv_text(CREDIT_CARD_CSV)
        gas_row = next(r for r in rows if r['description'] == 'Air-Serv A An01383')
        self.assertEqual(gas_row['category'], 'Gas, parking, and tolls')

    def test_pending_status_is_stored_not_filtered(self):
        # Decided 2026-09-06 (ARCHITECTURE.md A8): pending purchases count
        # immediately, so parsing must not drop or alter them.
        _, _, _, _, rows = import_csv.parse_csv_text(CREDIT_CARD_CSV)
        pending_row = next(r for r in rows if r['status'] == 'Pending')
        self.assertEqual(pending_row['description'], 'Amzn Mktp Ca')
        self.assertEqual(pending_row['amount'], -125.34)

    def test_refund_row_has_positive_amount(self):
        _, _, _, _, rows = import_csv.parse_csv_text(CREDIT_CARD_CSV)
        refund_row = next(r for r in rows if r['activity_type'] == 'Refund')
        self.assertEqual(refund_row['amount'], 445.62)
        self.assertEqual(refund_row['category'], 'Hotels')

    def test_bank_activity_rows(self):
        kind, account_id, label, account_kind, rows = import_csv.parse_csv_text(BANK_ACTIVITY_CSV)
        self.assertEqual(kind, 'bank_activity')
        self.assertEqual(account_id, 'WK1WPY033CAD')
        self.assertEqual(label, 'Chequing')
        self.assertEqual(account_kind, 'chequing')
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[0]['category'])
        self.assertIsNone(rows[0]['status'])

    def test_unrecognized_header_raises(self):
        with self.assertRaises(import_csv.ImportFormatError):
            import_csv.parse_csv_text('foo,bar\n1,2\n')

    def test_header_only_raises(self):
        header_only = CREDIT_CARD_CSV.splitlines()[0] + '\n'
        with self.assertRaises(import_csv.ImportFormatError):
            import_csv.parse_csv_text(header_only)


class ImportDbTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()


class TestImportCsvText(ImportDbTestCase):

    def test_imports_credit_card_rows(self):
        summary = import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        self.assertEqual(summary['kind'], 'credit_card')
        self.assertEqual(summary['account_id'], 'main-credit-card')
        self.assertEqual(summary['rows_imported'], 5)
        self.assertEqual(summary['date_start'], '2026-06-15')
        self.assertEqual(summary['date_end'], '2026-09-05')

        count = finance_db.account_transaction_count(self.conn, 'main-credit-card')
        self.assertEqual(count, 5)

        account = self.conn.execute('SELECT * FROM accounts WHERE id = ?', ('main-credit-card',)).fetchone()
        self.assertEqual(account['label'], 'Credit Card')
        self.assertEqual(account['kind'], 'credit_card')

    def test_imports_bank_activity_rows_under_their_own_account_id(self):
        summary = import_csv.import_csv_text(self.conn, 'bank.csv', BANK_ACTIVITY_CSV)
        self.assertEqual(summary['account_id'], 'WK1WPY033CAD')
        self.assertEqual(summary['rows_imported'], 3)

    def test_reimporting_identical_file_is_idempotent(self):
        import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        count = finance_db.account_transaction_count(self.conn, 'main-credit-card')
        self.assertEqual(count, 5)

    def test_range_replace_only_touches_the_new_files_date_range(self):
        earlier = (
            'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'
            '2026-05-01,Purchase,Completed,Old Merchant,-10.00,CAD,,Restaurants\n'
        )
        import_csv.import_csv_text(self.conn, 'may.csv', earlier)
        import_csv.import_csv_text(self.conn, 'sep.csv', CREDIT_CARD_CSV)

        count = finance_db.account_transaction_count(self.conn, 'main-credit-card')
        self.assertEqual(count, 6)  # 1 from May + 5 from the September-ish export
        may_row = self.conn.execute(
            "SELECT * FROM transactions WHERE date = '2026-05-01'"
        ).fetchone()
        self.assertIsNotNone(may_row)

    def test_reimport_with_a_changed_row_replaces_it_not_duplicates_it(self):
        import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        revised = CREDIT_CARD_CSV.replace('-13.42', '-99.99')
        import_csv.import_csv_text(self.conn, 'cc.csv', revised)

        count = finance_db.account_transaction_count(self.conn, 'main-credit-card')
        self.assertEqual(count, 5)
        row = self.conn.execute(
            "SELECT amount FROM transactions WHERE description LIKE '%Welcome Espresso%'"
        ).fetchone()
        self.assertEqual(row['amount'], -99.99)

    def test_two_accounts_do_not_collide(self):
        import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        import_csv.import_csv_text(self.conn, 'bank.csv', BANK_ACTIVITY_CSV)
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'main-credit-card'), 5)
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'WK1WPY033CAD'), 3)


class TestImportUploadedFile(unittest.TestCase):
    """Exercises the real POST /finance/import entry point end to end,
    including the audit-copy save, against a temp data dir rather than the
    real data/finance/ so the test suite never touches real app data."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp_dir.name, 'data', 'finance')
        self.db_path = os.path.join(self.data_dir, 'finance.db')
        self.patcher = patch.multiple(finance_db, DATA_DIR=self.data_dir, DB_PATH=self.db_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_saves_audit_copy_and_imports(self):
        summary = import_csv.import_uploaded_file('creditcardactivities.csv', CREDIT_CARD_CSV)
        self.assertEqual(summary['rows_imported'], 5)

        imports_dir = os.path.join(self.data_dir, 'imports')
        saved = os.listdir(imports_dir)
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].endswith('creditcardactivities.csv'))

        conn = finance_db.connect(self.db_path)
        try:
            count = finance_db.account_transaction_count(conn, 'main-credit-card')
            self.assertEqual(count, 5)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
