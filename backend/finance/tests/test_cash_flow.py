import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import import_csv  # noqa: E402
import summary  # noqa: E402


CC_HEADER = 'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'
BANK_HEADER = (
    'effective_date,effective_time,settlement_date,account_id,account_type,activity_type,'
    'activity_sub_type,description,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount\n'
)


def cc_row(date_, txn_type, merchant, amount, category, status='Completed'):
    return f'{date_},{txn_type},{status},{merchant},{amount},CAD,,{category}\n'


def bank_row(date_, activity_type, sub_type, description, amount, account_id='WK1WPY033CAD'):
    return f'{date_},12:00:00,,{account_id},Chequing,{activity_type},{sub_type},{description},,,,CAD,{amount},,,{amount}\n'


class CashFlowTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def load(self, text, source='x.csv'):
        return import_csv.import_csv_text(self.conn, source, text)


class TestChequingIncomeTotal(CashFlowTestCase):

    def test_sums_recognized_income_types(self):
        text = (
            BANK_HEADER
            + bank_row('2026-09-01', 'MoneyMovement', 'AFT_IN', 'Direct deposit received', 2000.00)
            + bank_row('2026-09-02', 'BonusPayment', 'CASHBACK', 'Cash back', 5.50)
            + bank_row('2026-09-03', 'BonusPayment', 'GIVEAWAY', 'Giveaway received', 10.00)
            + bank_row('2026-09-04', 'Interest', '-', 'Interest received', 3.26)
        )
        self.load(text)
        total = summary.chequing_income_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 2018.76)

    def test_excludes_transfers_and_expenses(self):
        text = (
            BANK_HEADER
            + bank_row('2026-09-01', 'MoneyMovement', 'E_TRFIN', 'Interac e-Transfer received', 100.00)
            + bank_row('2026-09-02', 'MoneyMovement', 'TRANSFER', 'Money transfer in', 500.00)
            + bank_row('2026-09-03', 'MoneyMovement', 'AFT_OUT', 'Pre-authorized debit', -50.00)
        )
        self.load(text)
        total = summary.chequing_income_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 0.0)

    def test_respects_window(self):
        text = BANK_HEADER + bank_row('2026-08-01', 'MoneyMovement', 'AFT_IN', 'Direct deposit received', 2000.00)
        self.load(text)
        total = summary.chequing_income_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 0.0)

    def test_ignores_credit_card_rows(self):
        # A credit card Refund also has a positive amount - must not be
        # picked up by the chequing-scoped income query.
        text = CC_HEADER + cc_row('2026-09-01', 'Refund', 'Airbnb', 50.00, 'Hotels')
        self.load(text)
        total = summary.chequing_income_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 0.0)


class TestChequingExpenseTotal(CashFlowTestCase):

    def test_sums_recognized_expense_types(self):
        text = (
            BANK_HEADER
            + bank_row('2026-09-01', 'MoneyMovement', 'SPEND', 'Spend', -73.50)
            + bank_row('2026-09-02', 'MoneyMovement', 'AFT_OUT', 'Pre-authorized Debit', -95.79)
            + bank_row('2026-09-03', 'MoneyMovement', 'OBP_OUT', 'Online bill payment', -225.00)
            + bank_row('2026-09-04', 'MoneyMovement', 'P2P', 'Cash sent', -50.00)
        )
        self.load(text)
        total = summary.chequing_expense_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 444.29)

    def test_credit_card_payment_transfer_is_not_double_counted(self):
        # The chequing side's mirror of a credit card bill payment
        # (activity_sub_type TRANSFER) must not count as expense - the
        # underlying purchases already do, on the credit card side.
        text = BANK_HEADER + bank_row('2026-09-01', 'MoneyMovement', 'TRANSFER', 'Credit card payment', -1896.62)
        self.load(text)
        total = summary.chequing_expense_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 0.0)


class TestCreditCardExpenseTotal(CashFlowTestCase):

    def test_matches_category_breakdown_total(self):
        text = (
            CC_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Cafe', -5.00, 'Coffee')
            + cc_row('2026-09-02', 'Payment', '', 500.00, 'Uncategorized')
        )
        self.load(text)
        total = summary.credit_card_expense_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 5.0)

    def test_a_large_refund_clamps_to_zero_rather_than_going_negative(self):
        # Regression: a refund bigger than everything else purchased in the
        # window used to make the overall total negative (a bug caught by
        # browser-testing against the real sample data, which has a $445.62
        # refund against a much smaller total of real purchases).
        text = (
            CC_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Cafe', -5.00, 'Coffee')
            + cc_row('2026-09-05', 'Refund', 'Big Refund', 445.62, 'Hotels')
        )
        self.load(text)
        total = summary.credit_card_expense_total(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(total, 0.0)


class TestCashFlowByMonth(CashFlowTestCase):

    def test_combines_chequing_and_credit_card_expense_per_month(self):
        text = (
            BANK_HEADER
            + bank_row('2026-09-01', 'MoneyMovement', 'AFT_IN', 'Direct deposit received', 2000.00)
            + bank_row('2026-09-02', 'MoneyMovement', 'SPEND', 'Spend', -50.00)
        )
        self.load(text, 'bank.csv')
        self.load(CC_HEADER + cc_row('2026-09-03', 'Purchase', 'Cafe', -10.00, 'Coffee'), 'cc.csv')

        result = summary.cash_flow_by_month(self.conn)
        self.assertEqual(result, [{'month': '2026-09', 'income': 2000.0, 'expense': 60.0}])

    def test_months_with_only_income_or_only_expense_still_appear(self):
        self.load(BANK_HEADER + bank_row('2026-07-01', 'MoneyMovement', 'AFT_IN', 'Deposit', 1000.00), 'jul.csv')
        self.load(CC_HEADER + cc_row('2026-08-01', 'Purchase', 'Cafe', -10.00, 'Coffee'), 'aug.csv')

        result = summary.cash_flow_by_month(self.conn)
        self.assertEqual(result, [
            {'month': '2026-07', 'income': 1000.0, 'expense': 0.0},
            {'month': '2026-08', 'income': 0.0, 'expense': 10.0},
        ])

    def test_limits_to_the_requested_number_of_months(self):
        text = BANK_HEADER + ''.join(
            bank_row(f'2026-{m:02d}-01', 'MoneyMovement', 'AFT_IN', 'Deposit', 100.00) for m in range(1, 10)
        )
        self.load(text)
        result = summary.cash_flow_by_month(self.conn, months=3)
        self.assertEqual([r['month'] for r in result], ['2026-07', '2026-08', '2026-09'])


class TestBuildCashFlow(CashFlowTestCase):

    def test_returns_all_expected_keys(self):
        self.load(BANK_HEADER + bank_row('2026-09-01', 'MoneyMovement', 'AFT_IN', 'Deposit', 2000.00), 'bank.csv')
        self.load(CC_HEADER + cc_row('2026-09-02', 'Purchase', 'Cafe', -50.00, 'Coffee'), 'cc.csv')

        result = summary.build_cash_flow(self.conn, 'month', today=date(2026, 9, 6))
        self.assertEqual(result['window'], 'month')
        self.assertEqual(result['windowStart'], '2026-09-01')
        self.assertEqual(result['windowEnd'], '2026-09-06')
        self.assertEqual(result['income'], 2000.0)
        self.assertEqual(result['expense'], 50.0)
        self.assertEqual(result['net'], 1950.0)
        self.assertEqual(result['byMonth'], [{'month': '2026-09', 'income': 2000.0, 'expense': 50.0}])

    def test_negative_net_when_expenses_exceed_income(self):
        self.load(BANK_HEADER + bank_row('2026-09-01', 'MoneyMovement', 'AFT_IN', 'Deposit', 100.00), 'bank.csv')
        self.load(CC_HEADER + cc_row('2026-09-02', 'Purchase', 'Big Purchase', -500.00, 'Other shopping'), 'cc.csv')

        result = summary.build_cash_flow(self.conn, 'month', today=date(2026, 9, 6))
        self.assertEqual(result['net'], -400.0)

    def test_unknown_window_falls_back_without_raising(self):
        result = summary.build_cash_flow(self.conn, 'not-a-real-window', today=date(2026, 9, 6))
        self.assertEqual(result['window'], 'month')

    def test_empty_database_returns_zeros_not_an_error(self):
        result = summary.build_cash_flow(self.conn, 'all', today=date(2026, 9, 6))
        self.assertEqual(result['income'], 0.0)
        self.assertEqual(result['expense'], 0.0)
        self.assertEqual(result['net'], 0.0)
        self.assertEqual(result['byMonth'], [])


if __name__ == '__main__':
    unittest.main()
