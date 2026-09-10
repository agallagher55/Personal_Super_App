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
2026-07-01,01:00:00,,WK1WPY033CAD,Chequing,Interest,-,Interest received (executed at 2026-07-01),,,,CAD,3.26,,,3.26
2026-07-08,18:05:06,,WK1WPY033CAD,Chequing,MoneyMovement,AFT_IN,Direct deposit received,,,,CAD,2008.53,,,2008.53
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
        self.assertEqual(len(rows), 5)
        self.assertIsNone(rows[0]['category'])
        self.assertIsNone(rows[0]['status'])

    def test_bank_activity_type_uses_the_finer_sub_type(self):
        # activity_type alone (MoneyMovement/BonusPayment/Interest) is too
        # coarse for summary.py's income/expense classification to use -
        # activity_sub_type (AFT_IN, CASHBACK, TRANSFER, ...) is what's
        # actually stored in the `activity_type` field on chequing rows.
        _, _, _, _, rows = import_csv.parse_csv_text(BANK_ACTIVITY_CSV)
        by_description = {r['description']: r for r in rows}
        self.assertEqual(by_description['Interac e-Transfer® Out']['activity_type'], 'E_TRFOUT')
        self.assertEqual(by_description['Cash back - Credit card']['activity_type'], 'CASHBACK')
        self.assertEqual(by_description['Credit card payment']['activity_type'], 'TRANSFER')
        self.assertEqual(by_description['Direct deposit received']['activity_type'], 'AFT_IN')

    def test_bank_activity_type_falls_back_when_sub_type_is_a_dash(self):
        # Interest rows carry activity_sub_type='-', not a real sub-type -
        # falls back to the coarse activity_type ('Interest') instead of
        # storing the meaningless '-'.
        _, _, _, _, rows = import_csv.parse_csv_text(BANK_ACTIVITY_CSV)
        interest_row = next(r for r in rows if 'Interest received' in r['description'])
        self.assertEqual(interest_row['activity_type'], 'Interest')

    def test_income_type_rows_default_to_the_income_category(self):
        # "Direct deposit received should be tagged as income" - AFT_IN,
        # CASHBACK, GIVEAWAY, and Interest rows (summary.CHEQUING_INCOME_TYPES)
        # get a real 'Income' category by default, rather than sitting
        # blank like every other chequing row.
        _, _, _, _, rows = import_csv.parse_csv_text(BANK_ACTIVITY_CSV)
        by_description = {r['description']: r for r in rows}
        self.assertEqual(by_description['Direct deposit received']['category'], 'Income')
        self.assertEqual(by_description['Cash back - Credit card']['category'], 'Income')
        interest_row = next(r for r in rows if 'Interest received' in r['description'])
        self.assertEqual(interest_row['category'], 'Income')

    def test_non_income_chequing_rows_have_no_default_category(self):
        _, _, _, _, rows = import_csv.parse_csv_text(BANK_ACTIVITY_CSV)
        by_description = {r['description']: r for r in rows}
        self.assertIsNone(by_description['Interac e-Transfer® Out']['category'])
        self.assertIsNone(by_description['Credit card payment']['category'])

    def test_expense_type_chequing_rows_default_to_uncategorized(self):
        # SPEND/AFT_OUT/OBP_OUT/P2P rows (summary.CHEQUING_EXPENSE_TYPES) are
        # folded into Spending (ARCHITECTURE.md A5g) alongside credit-card
        # purchases, so they need a real category value to start from too -
        # 'Uncategorized', the same label the credit card export itself uses,
        # rather than sitting NULL like a transfer row does.
        text = (
            'effective_date,effective_time,settlement_date,account_id,account_type,activity_type,'
            'activity_sub_type,description,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount\n'
            '2026-09-01,12:00:00,,WK1WPY033CAD,Chequing,MoneyMovement,AFT_OUT,Rent payment,,,,CAD,-1500,,,-1500\n'
        )
        _, _, _, _, rows = import_csv.parse_csv_text(text)
        self.assertEqual(rows[0]['category'], 'Uncategorized')

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
        self.assertEqual(account['institution'], 'Wealthsimple')
        self.assertEqual(account['kind'], 'credit_card')

    def test_imports_bank_activity_rows_under_their_own_account_id(self):
        summary = import_csv.import_csv_text(self.conn, 'bank.csv', BANK_ACTIVITY_CSV)
        self.assertEqual(summary['account_id'], 'WK1WPY033CAD')
        self.assertEqual(summary['rows_imported'], 5)

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
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'WK1WPY033CAD'), 5)

    def test_creates_one_import_batch_recording_the_file_and_range(self):
        summary = import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        batch = self.conn.execute(
            'SELECT * FROM import_batches WHERE id = ?', (summary['batch_id'],)
        ).fetchone()
        self.assertEqual(batch['kind'], 'csv_credit_card')
        self.assertEqual(batch['source_file'], 'cc.csv')
        self.assertEqual(batch['file_hash'], finance_db.file_hash(CREDIT_CARD_CSV))
        self.assertEqual(batch['row_count'], 5)
        self.assertEqual(batch['date_range_start'], '2026-06-15')
        self.assertEqual(batch['date_range_end'], '2026-09-05')

    def test_every_inserted_row_points_at_that_batch(self):
        summary = import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        batch_ids = {
            r['batch_id'] for r in
            self.conn.execute('SELECT batch_id FROM transactions WHERE account_id = ?', ('main-credit-card',))
        }
        self.assertEqual(batch_ids, {summary['batch_id']})

    def test_reimporting_creates_a_second_batch(self):
        first = import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        second = import_csv.import_csv_text(self.conn, 'cc.csv', CREDIT_CARD_CSV)
        self.assertNotEqual(first['batch_id'], second['batch_id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) AS n FROM import_batches').fetchone()['n'], 2)

    def test_a_failed_import_creates_no_batch(self):
        with self.assertRaises(import_csv.ImportFormatError):
            import_csv.import_csv_text(self.conn, 'bad.csv', 'not,a,recognized,header\n1,2,3,4\n')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) AS n FROM import_batches').fetchone()['n'], 0)


class TestTransactionIdStability(ImportDbTestCase):
    """Ids are derived from row content, not file position (db.transaction_id).

    The positional scheme this replaced numbered rows by their index
    within a date, so a single newly-appearing row shifted every id after
    it on that date - silently re-pointing the category overrides and
    cash flow exclusions keyed to those ids at other transactions.
    """

    HEADER = 'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'

    def cc(self, date_, merchant, amount, category, status='Completed', txn_type='Purchase'):
        return f'{date_},{txn_type},{status},{merchant},{amount},CAD,,{category}\n'

    def ids_by_description(self):
        return {r['description']: r['id'] for r in self.conn.execute('SELECT id, description FROM transactions')}

    def test_a_new_same_day_row_does_not_move_the_other_rows_ids(self):
        first = self.HEADER + self.cc('2026-09-02', 'Coffee Shop', -5.00, 'Coffee') \
            + self.cc('2026-09-02', 'Big Hotel', -450.00, 'Hotels')
        import_csv.import_csv_text(self.conn, 'v1.csv', first)
        before = self.ids_by_description()

        # A charge that was still pending at the first export shows up in
        # the second one, sorted ahead of both existing rows.
        import_csv.import_csv_text(
            self.conn, 'v2.csv',
            self.HEADER + self.cc('2026-09-02', 'Gas Station', -60.00, 'Gas') + first[len(self.HEADER):],
        )
        after = self.ids_by_description()
        self.assertEqual(before['Coffee Shop'], after['Coffee Shop'])
        self.assertEqual(before['Big Hotel'], after['Big Hotel'])

    def test_a_category_override_stays_on_its_own_transaction_across_a_reimport(self):
        # The user-visible form of the bug above: the correction used to
        # jump to whichever row inherited the old positional id.
        first = self.HEADER + self.cc('2026-09-02', 'Coffee Shop', -5.00, 'Coffee') \
            + self.cc('2026-09-02', 'Big Hotel', -450.00, 'Hotels')
        import_csv.import_csv_text(self.conn, 'v1.csv', first)
        finance_db.set_transaction_category_override(
            self.conn, self.ids_by_description()['Big Hotel'], 'Vacation', '2026-09-07T00:00:00Z'
        )

        import_csv.import_csv_text(
            self.conn, 'v2.csv',
            self.HEADER + self.cc('2026-09-02', 'Gas Station', -60.00, 'Gas') + first[len(self.HEADER):],
        )

        categories = {
            r['description']: r['effective_category']
            for r in self.conn.execute('SELECT description, effective_category FROM transactions_effective')
        }
        self.assertEqual(categories['Big Hotel'], 'Vacation')
        self.assertEqual(categories['Coffee Shop'], 'Coffee')

    def test_a_pending_charge_posting_keeps_the_same_id(self):
        import_csv.import_csv_text(self.conn, 'v1.csv', self.HEADER + self.cc('2026-09-05', 'Slow Merchant', -20.00, 'Food', status='Pending'))
        pending_id = self.ids_by_description()['Slow Merchant']

        import_csv.import_csv_text(self.conn, 'v2.csv', self.HEADER + self.cc('2026-09-05', 'Slow Merchant', -20.00, 'Food', status='Completed'))
        self.assertEqual(self.ids_by_description()['Slow Merchant'], pending_id)

    def test_genuinely_identical_same_day_rows_still_get_distinct_ids(self):
        # Two separate $2.94 charges at one merchant on one day are real
        # (ARCHITECTURE.md A3) - content alone can't tell them apart, so
        # the occurrence index has to.
        import_csv.import_csv_text(
            self.conn, 'cc.csv',
            self.HEADER + self.cc('2026-09-08', 'McDonalds', -2.94, 'Food') + self.cc('2026-09-08', 'McDonalds', -2.94, 'Food'),
        )
        ids = [r['id'] for r in self.conn.execute('SELECT id FROM transactions')]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_reimporting_the_identical_file_reproduces_the_identical_ids(self):
        text = self.HEADER + self.cc('2026-09-01', 'Tim Hortons', -6.26, 'Coffee')
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        before = self.ids_by_description()
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        self.assertEqual(self.ids_by_description(), before)


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


class TestResolveCsvPaths(unittest.TestCase):

    def test_plain_file_args_pass_through_unchanged(self):
        self.assertEqual(import_csv._resolve_csv_paths(['a.csv', 'b.csv']), ['a.csv', 'b.csv'])

    def test_directory_expands_to_its_csvs_sorted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            for name in ('activities-2026-09-07.csv', 'activities-2026-09-06.csv', 'notes.txt', 'export.CSV'):
                Path(tmp_dir, name).touch()
            self.assertEqual(
                import_csv._resolve_csv_paths([tmp_dir]),
                [
                    os.path.join(tmp_dir, 'activities-2026-09-06.csv'),
                    os.path.join(tmp_dir, 'activities-2026-09-07.csv'),
                    os.path.join(tmp_dir, 'export.CSV'),
                ],
            )

    def test_empty_directory_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual(import_csv._resolve_csv_paths([tmp_dir]), [])

    def test_mixes_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            Path(tmp_dir, 'bank.csv').touch()
            self.assertEqual(
                import_csv._resolve_csv_paths(['explicit.csv', tmp_dir]),
                ['explicit.csv', os.path.join(tmp_dir, 'bank.csv')],
            )


if __name__ == '__main__':
    unittest.main()
