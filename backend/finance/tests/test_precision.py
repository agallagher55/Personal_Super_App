"""Issue: exact-storage strategy for financial values. Covers the
containment policy documented in db.py/csv_schema.sql - round_cad()/
round_btc() applied at every write boundary (import_csv.py,
import_shakepay.py, networth.record_balance) - with the precision edge
cases the review specifically called out: 0.01, repeated fractional
additions, refunds, large balances, and eight-decimal-place Bitcoin
quantities.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import import_csv  # noqa: E402
import networth  # noqa: E402


CC_HEADER = 'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'


class TestRoundHelpers(unittest.TestCase):

    def test_round_cad_contains_a_cent(self):
        self.assertEqual(finance_db.round_cad(0.01), 0.01)

    def test_round_cad_passes_none_through(self):
        self.assertIsNone(finance_db.round_cad(None))

    def test_round_cad_contains_repeated_fractional_addition_drift(self):
        # 0.1 + 0.2 != 0.3 in binary floating point without rounding.
        total = 0.0
        for _ in range(3):
            total += 0.1
        self.assertNotEqual(total, 0.3)
        self.assertEqual(finance_db.round_cad(total), 0.3)

    def test_round_cad_preserves_a_refund_sign(self):
        self.assertEqual(finance_db.round_cad(-45.999999999999995), -46.0)

    def test_round_cad_handles_a_large_balance(self):
        self.assertEqual(finance_db.round_cad(1234567.895), 1234567.9)

    def test_round_btc_contains_to_eight_decimals(self):
        self.assertEqual(finance_db.round_btc(0.123456789), 0.12345679)

    def test_round_btc_passes_none_through(self):
        self.assertIsNone(finance_db.round_btc(None))


class TestImportCsvRoundsAmounts(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_a_one_cent_amount_round_trips_exactly(self):
        text = CC_HEADER + '2026-09-01,Purchase,Completed,Vending machine,-0.01,CAD,,Snacks\n'
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        row = self.conn.execute('SELECT amount FROM transactions').fetchone()
        self.assertEqual(row['amount'], -0.01)

    def test_a_refund_and_its_purchase_round_trip_exactly(self):
        text = (
            CC_HEADER
            + '2026-09-01,Purchase,Completed,Store,-19.99,CAD,,Shopping\n'
            + '2026-09-03,Refund,Completed,Store,19.99,CAD,,Shopping\n'
        )
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        amounts = sorted(r['amount'] for r in self.conn.execute('SELECT amount FROM transactions'))
        self.assertEqual(amounts, [-19.99, 19.99])

    def test_a_large_amount_round_trips_exactly(self):
        text = CC_HEADER + '2026-09-01,Payment,Completed,,9999.99,CAD,,\n'
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        row = self.conn.execute('SELECT amount FROM transactions').fetchone()
        self.assertEqual(row['amount'], 9999.99)


class TestRecordBalanceRoundsValues(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = finance_db.connect(os.path.join(self.tmp_dir.name, 'finance.db'))
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_balance_cad_is_rounded_to_two_decimals(self):
        with self.conn:
            networth.record_balance(
                self.conn, 'acc1', 'Savings', None, 'savings', '2026-09-01', 100.005
            )
        row = self.conn.execute('SELECT balance_cad FROM account_balance_snapshots').fetchone()
        self.assertEqual(row['balance_cad'], 100.0)  # banker's rounding, matching round()

    def test_a_large_balance_round_trips_exactly(self):
        with self.conn:
            networth.record_balance(
                self.conn, 'acc1', 'Line of Credit', None, 'line_of_credit', '2026-09-01', 123456.78
            )
        row = self.conn.execute('SELECT balance_cad FROM account_balance_snapshots').fetchone()
        self.assertEqual(row['balance_cad'], 123456.78)

    def test_interest_rate_and_credit_limit_are_rounded(self):
        with self.conn:
            networth.record_balance(
                self.conn, 'acc1', 'Line of Credit', None, 'line_of_credit', '2026-09-01', 500.0,
                interest_rate=6.999, credit_limit=10000.001,
            )
        row = self.conn.execute('SELECT interest_rate, credit_limit FROM account_terms_snapshots').fetchone()
        self.assertEqual(row['interest_rate'], 7.0)
        self.assertEqual(row['credit_limit'], 10000.0)


class TestTransactionIdStableAcrossFloatNoise(unittest.TestCase):
    """transaction_id()'s fingerprint formats amount with `.2f`, so an id
    doesn't depend on binary noise past two decimal places - the write-
    boundary rounding above is a second, independent layer of the same
    protection for the *stored* amount value, not just the hash."""

    def test_ids_match_for_amounts_that_differ_only_past_two_decimals(self):
        exact = finance_db.transaction_id('acc1', '2026-09-01', 'Coffee', -5.0, 'Purchase', 0)
        noisy = finance_db.transaction_id('acc1', '2026-09-01', 'Coffee', -4.999999999999996, 'Purchase', 0)
        self.assertEqual(exact, noisy)


if __name__ == '__main__':
    unittest.main()
