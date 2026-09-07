import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import categorize_shakepay  # noqa: E402
import db as finance_db  # noqa: E402
import import_shakepay  # noqa: E402


CARD_STATEMENT_TEXT = (
    "Card transactions Date/time (EST) Transaction Description Debit Credit "
    "2026-08-03 09:14:06 Transfer Transfer from Shakepay Inc. to Shakepay Financial Inc. for "
    "Card purchase +$7.33 "
    "2026-08-03 09:14:06 Card purchase RAMBLERS -$7.33 "
    "2026-08-04 12:07:26 Transfer Transfer from Shakepay Inc. to Shakepay Financial Inc. for "
    "Card purchase +$1.14 "
    "2026-08-04 12:07:26 Card purchase McDonalds 40487 -$1.14 "
    "2026-08-05 07:22:37 Transfer Transfer from Shakepay Inc. to Shakepay Financial Inc. for "
    "Card purchase +$9.83 "
    "2026-08-05 07:22:37 Card purchase SQ *FIRST - CENTRAL -$9.83 "
    "Bill payments Date/time (EST) Transaction Description Debit Credit No account activity "
    "Pre-authorized debits Date/time (EST) Transaction Description Debit Credit No account activity "
    "Disclosures These services are offered by Shakepay Financial Inc."
)


class TestGuessCategory(unittest.TestCase):

    def test_known_merchants_match_expected_categories(self):
        cases = [
            ('TIM HORTONS #0476', 'Coffee'),
            ('SQ *WELCOME ESPRESSO', 'Coffee'),
            ('McDonalds 40487', 'Restaurants'),
            ('DQ GRILL & CHILL #7234', 'Restaurants'),
            ('SOBEYS #574', 'Groceries'),
            ('LAWTONS #144', 'Health & pharmacy'),
            ('DOLLARAMA # 657', 'Other shopping'),
            ('SMU - ATHLETICS & RECREAT', 'Fitness'),
            ('DAL ATHLETICS - POS 1', 'Fitness'),
            ('096 HRM ON-LINE PARKING S', 'Gas, parking, and tolls'),
            ('AIR-SERV A AN01383', 'Gas, parking, and tolls'),
            ('UBER CANADA/UBERTRIP', 'Transportation'),
            ('MASABI *HALIFAX', 'Transportation'),
            ('METROLINX - GO TRANSIT', 'Transportation'),
            ('BIRD* PENDING.BIRD.CO', 'Transportation'),
            ('KUBRA/EZ-PAY', 'Bills & utilities'),
            ('NOVA SCOTIA PWR/EZ-PAY', 'Bills & utilities'),
            ('CANADIAN TIRE #44', 'Other shopping'),
            ('NSLC #2107', 'Other shopping'),
            ('DURTY NELLYS IRISH PUB', 'Restaurants'),
            ('SEAHORSE TAVERN', 'Restaurants'),
            ('Garrison Brewing', 'Restaurants'),
            # Truncated merchant descriptions (observed real-world limit:
            # ~25 chars) must still match on their shortened keyword.
            ('SQ *WEIRD HARBOUR ESPRESS', 'Coffee'),
            ("TONY'S DONAIR AND PIZZ", 'Restaurants'),
            # Toast POS always prefixes its own merchant names with
            # "TST-", regardless of what the venue itself is.
            ('TST-The Narrows Public', 'Restaurants'),
            ('TST-Stillwell Beerbar', 'Restaurants'),
        ]
        for description, expected in cases:
            with self.subTest(description=description):
                self.assertEqual(categorize_shakepay.guess_category(description), expected)

    def test_matching_is_case_insensitive(self):
        self.assertEqual(categorize_shakepay.guess_category('tim hortons #0476'), 'Coffee')

    def test_unrecognized_merchant_returns_none(self):
        self.assertIsNone(categorize_shakepay.guess_category('SQ *FIRST - CENTRAL'))

    def test_genuinely_ambiguous_names_are_left_unmatched(self):
        # Names with no reliable signal at all - correctly not guessed at,
        # rather than forced into a category that might be wrong.
        for description in ('ABUNDANT ACES FARM', 'AS YOU LIKE IT', 'PBCDARTMOUTHNS1329',
                             'OPENAI *CHATGPT SUBSCR', 'SQ *POST-SECURITY CONNECT'):
            with self.subTest(description=description):
                self.assertIsNone(categorize_shakepay.guess_category(description))


class TestCategorize(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)
        import_shakepay.import_shakepay_text(self.conn, 'card.pdf', CARD_STATEMENT_TEXT)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_matched_merchants_get_permanent_overrides(self):
        categorized, unmatched, skipped = categorize_shakepay.categorize(self.conn)
        self.assertEqual(dict(categorized), {'RAMBLERS': 'Restaurants', 'McDonalds 40487': 'Restaurants'})
        self.assertEqual(unmatched, ['SQ *FIRST - CENTRAL'])
        self.assertEqual(skipped, [])

        override = self.conn.execute(
            "SELECT category FROM merchant_category_overrides WHERE description = 'RAMBLERS'"
        ).fetchone()
        self.assertEqual(override['category'], 'Restaurants')

    def test_categorized_purchase_now_shows_up_in_spending(self):
        import summary as finance_summary

        categorize_shakepay.categorize(self.conn)
        breakdown = finance_summary.category_breakdown(self.conn, '2026-08-01', '2026-08-31')
        self.assertEqual(
            {row['category']: row['total'] for row in breakdown},
            {'Restaurants': 8.47},  # RAMBLERS 7.33 + McDonalds 1.14
        )

    def test_dry_run_writes_nothing(self):
        categorize_shakepay.categorize(self.conn, dry_run=True)
        count = self.conn.execute('SELECT COUNT(*) AS n FROM merchant_category_overrides').fetchone()['n']
        self.assertEqual(count, 0)

    def test_rerunning_is_idempotent_and_skips_already_categorized(self):
        categorize_shakepay.categorize(self.conn)
        categorized, unmatched, skipped = categorize_shakepay.categorize(self.conn)
        self.assertEqual(categorized, [])
        self.assertEqual(sorted(skipped), ['McDonalds 40487', 'RAMBLERS'])

    def test_never_overwrites_a_manual_override(self):
        # A category you already set by hand via the dashboard's
        # pencil-edit dialog must survive a categorize_shakepay.py run
        # untouched, even if a pattern would have guessed differently.
        finance_db.set_merchant_category_override(self.conn, 'RAMBLERS', 'My Own Category', '2026-08-01T00:00:00Z')
        categorize_shakepay.categorize(self.conn)
        override = self.conn.execute(
            "SELECT category FROM merchant_category_overrides WHERE description = 'RAMBLERS'"
        ).fetchone()
        self.assertEqual(override['category'], 'My Own Category')


if __name__ == '__main__':
    unittest.main()
