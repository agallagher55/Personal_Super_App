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


CREDIT_CARD_HEADER = 'transaction_date,transaction_type,status,merchant,amount,currency,notes,category\n'


def cc_row(date_, txn_type, merchant, amount, category, status='Completed'):
    return f'{date_},{txn_type},{status},{merchant},{amount},CAD,,{category}\n'


class SummaryTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def load(self, text, source='cc.csv'):
        return import_csv.import_csv_text(self.conn, source, text)


class TestWindowStart(unittest.TestCase):

    def test_month(self):
        self.assertEqual(summary.window_start('month', date(2026, 9, 6)), '2026-09-01')

    def test_30d(self):
        self.assertEqual(summary.window_start('30d', date(2026, 9, 6)), '2026-08-07')

    def test_90d(self):
        self.assertEqual(summary.window_start('90d', date(2026, 9, 6)), '2026-06-08')

    def test_all(self):
        self.assertEqual(summary.window_start('all', date(2026, 9, 6)), '1970-01-01')

    def test_unknown_window_falls_back_to_default(self):
        self.assertEqual(summary.window_start('bogus', date(2026, 9, 6)), summary.window_start('month', date(2026, 9, 6)))


class TestCategoryBreakdown(SummaryTestCase):

    def test_sums_purchases_by_category(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Cafe A', -5.00, 'Coffee')
            + cc_row('2026-09-02', 'Purchase', 'Cafe B', -7.00, 'Coffee')
            + cc_row('2026-09-03', 'Purchase', 'Diner', -20.00, 'Restaurants')
        )
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [
            {'category': 'Restaurants', 'total': 20.0},
            {'category': 'Coffee', 'total': 12.0},
        ])

    def test_refund_nets_against_its_category(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Hotel', -200.00, 'Hotels')
            + cc_row('2026-09-05', 'Refund', 'Hotel Refund', 50.00, 'Hotels')
        )
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Hotels', 'total': 150.0}])

    def test_payment_and_uncategorized_rows_excluded(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Payment', '', 500.00, 'Uncategorized')
            + cc_row('2026-09-02', 'Purchase', 'Cafe', -5.00, 'Coffee')
        )
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Coffee', 'total': 5.0}])

    def test_pending_purchases_count_immediately(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Amazon', -40.00, 'Other shopping', status='Pending')
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Other shopping', 'total': 40.0}])

    def test_rows_outside_the_window_are_excluded(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-08-15', 'Purchase', 'Old', -10.00, 'Coffee')
            + cc_row('2026-09-15', 'Purchase', 'New', -10.00, 'Coffee')
        )
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Coffee', 'total': 10.0}])

    def test_net_negative_category_is_dropped(self):
        # A category where refunds exceed purchases in the window shouldn't
        # produce a nonsensical negative slice.
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Hotel', -50.00, 'Hotels')
            + cc_row('2026-09-05', 'Refund', 'Hotel Refund', 200.00, 'Hotels')
        )
        self.load(text)
        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [])


class TestMonthlyTrend(SummaryTestCase):

    def test_groups_by_month_across_the_full_history(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-07-01', 'Purchase', 'A', -10.00, 'Coffee')
            + cc_row('2026-08-01', 'Purchase', 'B', -20.00, 'Restaurants')
            + cc_row('2026-08-15', 'Purchase', 'C', -5.00, 'Coffee')
            + cc_row('2026-09-01', 'Purchase', 'D', -30.00, 'Groceries')
        )
        self.load(text)
        result = summary.monthly_trend(self.conn)
        self.assertEqual(result, [
            {'month': '2026-07', 'total': 10.0},
            {'month': '2026-08', 'total': 25.0},
            {'month': '2026-09', 'total': 30.0},
        ])

    def test_limits_to_the_requested_number_of_months(self):
        text = CREDIT_CARD_HEADER + ''.join(
            cc_row(f'2026-{m:02d}-01', 'Purchase', 'X', -1.00, 'Coffee') for m in range(1, 10)
        )
        self.load(text)
        result = summary.monthly_trend(self.conn, months=3)
        self.assertEqual([r['month'] for r in result], ['2026-07', '2026-08', '2026-09'])


class TestTopMerchants(SummaryTestCase):

    def test_sums_and_counts_per_merchant(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Mcdonalds', -3.00, 'Restaurants')
            + cc_row('2026-09-02', 'Purchase', 'Mcdonalds', -4.00, 'Restaurants')
            + cc_row('2026-09-03', 'Purchase', 'Starbucks', -6.00, 'Coffee')
        )
        self.load(text)
        result = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [
            {'merchant': 'Mcdonalds', 'total': 7.0, 'count': 2},
            {'merchant': 'Starbucks', 'total': 6.0, 'count': 1},
        ])

    def test_respects_the_limit(self):
        text = CREDIT_CARD_HEADER + ''.join(
            cc_row('2026-09-01', 'Purchase', f'Merchant{i}', -float(i + 1), 'Other shopping') for i in range(5)
        )
        self.load(text)
        result = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30', limit=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['merchant'], 'Merchant4')  # largest amount first

    def test_payment_rows_excluded(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Payment', '', 100.00, 'Uncategorized')
        self.load(text)
        result = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [])

    def test_category_filter_narrows_to_just_that_category(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Mcdonalds', -3.00, 'Restaurants')
            + cc_row('2026-09-02', 'Purchase', 'Starbucks', -6.00, 'Coffee')
            + cc_row('2026-09-03', 'Purchase', 'Dollarama', -2.00, 'Other shopping')
        )
        self.load(text)
        result = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30', category='Coffee')
        self.assertEqual(result, [{'merchant': 'Starbucks', 'total': 6.0, 'count': 1}])

    def test_category_filter_with_no_matches_returns_empty(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Mcdonalds', -3.00, 'Restaurants')
        self.load(text)
        result = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30', category='Coffee')
        self.assertEqual(result, [])


class TestBuildSummary(SummaryTestCase):

    def test_returns_all_expected_keys(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Cafe', -5.00, 'Coffee')
        self.load(text)
        result = summary.build_summary(self.conn, 'month', today=date(2026, 9, 6))
        self.assertEqual(result['window'], 'month')
        self.assertEqual(result['windowStart'], '2026-09-01')
        self.assertEqual(result['windowEnd'], '2026-09-06')
        self.assertIsNone(result['categoryFilter'])
        self.assertEqual(result['byCategory'], [{'category': 'Coffee', 'total': 5.0}])
        self.assertEqual(result['byMonth'], [{'month': '2026-09', 'total': 5.0}])
        self.assertEqual(result['topMerchants'], [{'merchant': 'Cafe', 'total': 5.0, 'count': 1}])

    def test_category_narrows_merchants_but_not_the_category_breakdown(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Cafe', -5.00, 'Coffee')
            + cc_row('2026-09-02', 'Purchase', 'Diner', -20.00, 'Restaurants')
        )
        self.load(text)
        result = summary.build_summary(self.conn, 'month', today=date(2026, 9, 6), category='Coffee')
        self.assertEqual(result['categoryFilter'], 'Coffee')
        self.assertEqual(result['topMerchants'], [{'merchant': 'Cafe', 'total': 5.0, 'count': 1}])
        # byCategory keeps showing the whole picture - only merchants drills down
        self.assertEqual(len(result['byCategory']), 2)

    def test_unknown_window_falls_back_without_raising(self):
        result = summary.build_summary(self.conn, 'not-a-real-window', today=date(2026, 9, 6))
        self.assertEqual(result['window'], 'month')

    def test_empty_database_returns_empty_lists_not_an_error(self):
        result = summary.build_summary(self.conn, 'all', today=date(2026, 9, 6))
        self.assertEqual(result['byCategory'], [])
        self.assertEqual(result['byMonth'], [])
        self.assertEqual(result['topMerchants'], [])


class TestCategoryOverrides(SummaryTestCase):
    """Editing categories (finance/ARCHITECTURE.md): a one-time
    (transaction_category_overrides) and a permanent (merchant_category_overrides)
    fix, both resolved through the transactions_effective view."""

    def test_transaction_override_recolors_just_that_row(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
            + cc_row('2026-09-02', 'Purchase', 'Tim Hortons', -7.98, 'Coffee')
        )
        import_csv.import_csv_text(self.conn, 'cc.csv', text)

        tx_id = 'main-credit-card:2026-09-01:0'
        finance_db.set_transaction_category_override(self.conn, tx_id, 'Food', '2026-09-06T00:00:00Z')

        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [
            {'category': 'Coffee', 'total': 7.98},
            {'category': 'Food', 'total': 6.26},
        ])

    def test_merchant_override_recolors_every_matching_row_past_and_future(self):
        # "Past": already imported before the override is set.
        import_csv.import_csv_text(
            self.conn, 'cc.csv',
            CREDIT_CARD_HEADER + cc_row('2026-08-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee'),
        )
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        # "Future": imported after the override already exists.
        import_csv.import_csv_text(
            self.conn, 'cc2.csv',
            CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -7.98, 'Coffee'),
        )

        result = summary.category_breakdown(self.conn, '2026-08-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Food', 'total': 14.24}])

    def test_transaction_override_takes_precedence_over_merchant_override(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
        import_csv.import_csv_text(self.conn, 'cc.csv', text)

        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_transaction_category_override(
            self.conn, 'main-credit-card:2026-09-01:0', 'Gifts', '2026-09-06T00:00:00Z'
        )

        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Gifts', 'total': 6.26}])

    def test_removing_a_transaction_override_falls_back_to_merchant_override(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        tx_id = 'main-credit-card:2026-09-01:0'

        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_transaction_category_override(self.conn, tx_id, 'Gifts', '2026-09-06T00:00:00Z')
        finance_db.set_transaction_category_override(self.conn, tx_id, '', '2026-09-06T00:00:00Z')  # revert

        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Food', 'total': 6.26}])

    def test_removing_a_merchant_override_falls_back_to_original_category(self):
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
        import_csv.import_csv_text(self.conn, 'cc.csv', text)

        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', '', '2026-09-06T00:00:00Z')  # revert

        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Coffee', 'total': 6.26}])

    def test_top_merchants_category_filter_uses_the_effective_category(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
            + cc_row('2026-09-02', 'Purchase', 'Starbucks', -5.00, 'Coffee')
        )
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        finance_db.set_merchant_category_override(self.conn, 'Tim Hortons', 'Food', '2026-09-06T00:00:00Z')

        coffee = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30', category='Coffee')
        self.assertEqual(coffee, [{'merchant': 'Starbucks', 'total': 5.0, 'count': 1}])

        food = summary.top_merchants(self.conn, '2026-09-01', '2026-09-30', category='Food')
        self.assertEqual(food, [{'merchant': 'Tim Hortons', 'total': 6.26, 'count': 1}])

    def test_merchant_transactions_returns_effective_category(self):
        text = (
            CREDIT_CARD_HEADER
            + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
            + cc_row('2026-09-02', 'Purchase', 'Tim Hortons', -7.98, 'Coffee')
        )
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        finance_db.set_transaction_category_override(
            self.conn, 'main-credit-card:2026-09-01:0', 'Food', '2026-09-06T00:00:00Z'
        )

        result = summary.merchant_transactions(self.conn, 'Tim Hortons', '2026-09-01', '2026-09-30')
        self.assertEqual(result, [
            {'id': 'main-credit-card:2026-09-02:0', 'date': '2026-09-02', 'amount': -7.98, 'category': 'Coffee'},
            {'id': 'main-credit-card:2026-09-01:0', 'date': '2026-09-01', 'amount': -6.26, 'category': 'Food'},
        ])

    def test_range_replace_reimport_keeps_the_transaction_override(self):
        # The whole reason overrides aren't a foreign key with ON DELETE
        # CASCADE (csv_schema.sql): a range-replace re-import deletes and
        # re-inserts every row in the file's date range, and re-uploading
        # the *same* file regenerates the *same* deterministic ids - the
        # override should still apply after that happens.
        text = CREDIT_CARD_HEADER + cc_row('2026-09-01', 'Purchase', 'Tim Hortons', -6.26, 'Coffee')
        import_csv.import_csv_text(self.conn, 'cc.csv', text)
        finance_db.set_transaction_category_override(
            self.conn, 'main-credit-card:2026-09-01:0', 'Food', '2026-09-06T00:00:00Z'
        )

        import_csv.import_csv_text(self.conn, 'cc.csv', text)  # re-upload the identical file

        result = summary.category_breakdown(self.conn, '2026-09-01', '2026-09-30')
        self.assertEqual(result, [{'category': 'Food', 'total': 6.26}])


if __name__ == '__main__':
    unittest.main()
