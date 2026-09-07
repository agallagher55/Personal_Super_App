import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import import_shakepay  # noqa: E402


# Fixtures mimic the single-space-joined text pypdf's extract_text() plus
# ' '.join(text.split()) produces (see import_shakepay.extract_text) -
# built from the actual line shapes a real Shakepay statement contains,
# trimmed to the handful of rows each test needs. Real footer/header
# boilerplate is included once in each to exercise _strip_boilerplate.
ACCOUNT_STATEMENT_TEXT = (
    "Alexander Gallagher 1338 Hollis Street Halifax Account type Shaketag "
    "Personal - Order Execution Only @gallagher55 "
    "Balance summary (as of 2026-09-01 00:00 EDT) Cash (CAD) 18.22 1.00 18.22 18.22 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 1 of 18 "
    "Cash transactions (CAD) Date/time (EST) Transaction Description Debit (CA$) Credit (CA$) Balance (CA$) "
    "2026-08-01 Starting balance 1.73 "
    "2026-08-02 13:41:17 Receive cash via Shakepay @rearea +5.00 6.73 "
    "2026-08-05 06:50:50 Send cash via Shakepay @rearea -10.00 19.73 "
    "2026-08-07 16:29:06 Interac e-Transfer agallagher55@gmail.com +79.00 80.27 "
    "2026-08-03 09:14:06 Transfer Transfer from Shakepay Inc. to Shakepay Financial "
    "Inc. for Card purchase -7.33 36.40 "
    "2026-08-03 09:14:10 Round up Bought 0.00002993 BTC @ CA$89,208.15 -2.67 33.73 "
    "2026-08-31 Closing balance 18.22 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 2 of 18 "
    "US Dollar (USD) transactions Date/time (EST) Transaction Description Debit (US$) "
    "Credit (US$) Balance (US$) No account activity "
    "Crypto transactions Date/time (EST) Transaction Description Debit Credit Market value "
    "(CA$)** Original cost (CA$)*** "
    "2026-08-01 Starting balance BTC 0.00716192 BTC 631.91 700.23 ETH 0 ETH 0.00 0.00 "
    "2026-08-01 08:06:46 Shakepay reward ShakingSats +0.0000001 BTC 0.01 0.00 "
    "2026-08-05 10:31:00 Shakepay Interest Interest payout on CAD balance +0.00000003 BTC 0.00 0.00 "
    "2026-08-03 09:14:10 Round up Bought @ CA$89,208.15 +0.00002993 BTC 3.26 2.63 "
    "2026-08-09 16:01:14 Receive Bitcoin Bitcoin address bc1q6lwcmm8cw5dp3vxssqvxspgtns3xeancp6hup3 "
    "+0.00021993 BTC 23.98 19.97 "
    "2026-08-31 Closing balance BTC 0.64866807 BTC 70,748.38 57,412.60 ETH 0 ETH 0.00 0.00 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 18 of 18 "
    "Audit Notice Our annual account audit is being conducted as of August 31, 2026."
)

CARD_STATEMENT_TEXT = (
    "Alexander Gallagher 1338 Hollis Street Halifax Account type Shaketag Personal @gallagher55 "
    "Card transactions Date/time (EST) Transaction Description Debit Credit "
    "2026-08-03 09:14:06 Transfer Transfer from Shakepay Inc. to Shakepay Financial Inc. for "
    "Card purchase +$7.33 "
    "2026-08-03 09:14:06 Card purchase RAMBLERS -$7.33 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Financial Inc. 2004 Sherwood Drive, Sherwood, AB, T8A 1K6 "
    "support@shakepay.com Page 1 of 6 "
    "Bill payments Date/time (EST) Transaction Description Debit Credit No account activity "
    "Pre-authorized debits Date/time (EST) Transaction Description Debit Credit No account activity "
    "Disclosures These services are offered by Shakepay Financial Inc."
)

# Same statements as above, but with the column-boundary spaces missing
# the way some pypdf versions/platforms actually extract them (observed:
# ArcGIS Pro's bundled Python environment) - "09:14:06Transfer",
# "Card purchaseRAMBLERS", "+5.006.73". See _insert_missing_spaces's
# docstring for why this happens and why the fix is keyword/format
# targeted rather than a blanket case-transition heuristic.
ACCOUNT_STATEMENT_TEXT_GLUED = (
    "Alexander Gallagher 1338 Hollis Street Halifax Account type Shaketag "
    "Personal - Order Execution Only @gallagher55 "
    "Balance summary (as of 2026-09-01 00:00 EDT) Cash (CAD) 18.22 1.00 18.22 18.22 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 1 of 18 "
    "Cash transactions (CAD) Date/time (EST)TransactionDescription Debit (CA$)Credit (CA$)Balance (CA$) "
    "2026-08-01Starting balance 1.73 "
    "2026-08-02 13:41:17Receive cash via Shakepay@rearea +5.006.73 "
    "2026-08-05 06:50:50Send cash via Shakepay@rearea -10.00 19.73 "
    "2026-08-07 16:29:06Interac e-Transferagallagher55@gmail.com +79.0080.27 "
    "2026-08-03 09:14:06TransferTransfer from Shakepay Inc. to Shakepay Financial "
    "Inc. for Card purchase-7.33 36.40 "
    "2026-08-03 09:14:10Round upBought 0.00002993 BTC @ CA$89,208.15 -2.67 33.73 "
    "2026-08-31Closing balance 18.22 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 2 of 18 "
    "US Dollar (USD) transactions Date/time (EST)TransactionDescription Debit (US$)"
    "Credit (US$)Balance (US$) No account activity "
    "Crypto transactions Date/time (EST)TransactionDescription DebitCreditMarket value "
    "(CA$)**Original cost (CA$)*** "
    "2026-08-01Starting balanceBTC 0.00716192 BTC 631.91700.23 ETH 0 ETH0.000.00 "
    "2026-08-01 08:06:46Shakepay rewardShakingSats +0.0000001 BTC 0.010.00 "
    "2026-08-05 10:31:00Shakepay InterestInterest payout on CAD balance+0.00000003 BTC0.000.00 "
    "2026-08-03 09:14:10Round upBought @ CA$89,208.15 +0.00002993 BTC 3.262.63 "
    "2026-08-09 16:01:14Receive BitcoinBitcoin address bc1q6lwcmm8cw5dp3v xssqvxspgtns3xeancp6 "
    "hup3+0.00021993 BTC23.9819.97 "
    "2026-08-31Closing balanceBTC 0.64866807 BTC 70,748.3857,412.60 ETH 0 ETH0.000.00 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Inc. 500 Place d'Armes, Suite 1800, Montreal, QC Canada "
    "H2Y 2W2 support@shakepay.com Page 18 of 18 "
    "Audit Notice Our annual account audit is being conducted as of August 31, 2026."
)

CARD_STATEMENT_TEXT_GLUED = (
    "Alexander Gallagher 1338 Hollis Street Halifax Account type Shaketag Personal @gallagher55 "
    "Card transactions Date/time (EST)TransactionDescription DebitCredit "
    "2026-08-03 09:14:06TransferTransfer from Shakepay Inc. to Shakepay Financial Inc. for "
    "Card purchase+$7.33 "
    "2026-08-03 09:14:06Card purchaseRAMBLERS -$7.33 "
    "Monthly account statement 2026-08-01 to 2026-08-31 All figures are in $CAD unless "
    "otherwise specified Shakepay Financial Inc. 2004 Sherwood Drive, Sherwood, AB, T8A 1K6 "
    "support@shakepay.com Page 1 of 6 "
    "Bill payments Date/time (EST)TransactionDescription DebitCredit No account activity "
    "Pre-authorized debits Date/time (EST)TransactionDescription DebitCredit No account activity "
    "Disclosures These services are offered by Shakepay Financial Inc."
)

UNRECOGNIZED_TEXT = "This is not a Shakepay statement at all."


class TestDetectStatementType(unittest.TestCase):

    def test_account_statement(self):
        self.assertEqual(import_shakepay.detect_statement_type(ACCOUNT_STATEMENT_TEXT), 'account')

    def test_card_statement(self):
        self.assertEqual(import_shakepay.detect_statement_type(CARD_STATEMENT_TEXT), 'card')

    def test_unrecognized_returns_none(self):
        self.assertIsNone(import_shakepay.detect_statement_type(UNRECOGNIZED_TEXT))


class TestParseStatementText(unittest.TestCase):

    def test_unrecognized_text_raises(self):
        with self.assertRaises(import_shakepay.ShakepayImportError):
            import_shakepay.parse_statement_text(UNRECOGNIZED_TEXT)

    def test_account_statement_period(self):
        _, period, _, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        self.assertEqual(period, ('2026-08-01', '2026-08-31'))

    def test_p2p_send_is_expense_type_p2p(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        send = next(r for r in rows_by_account['shakepay-cash'] if r['amount'] == -10.0)
        self.assertEqual(send['activity_type'], 'P2P')
        self.assertEqual(send['category'], 'Uncategorized')  # summary.CHEQUING_EXPENSE_TYPES default

    def test_p2p_receive_is_excluded_by_default(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        receive = next(r for r in rows_by_account['shakepay-cash'] if r['amount'] == 5.0)
        self.assertEqual(receive['activity_type'], 'P2P_IN')
        self.assertIsNone(receive['category'])

    def test_interac_in_uses_existing_excluded_type(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        interac = next(r for r in rows_by_account['shakepay-cash'] if r['amount'] == 79.0)
        self.assertEqual(interac['activity_type'], 'E_TRFIN')
        self.assertIsNone(interac['category'])

    def test_roundup_buy_is_recorded_and_excluded(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        roundup = next(r for r in rows_by_account['shakepay-cash'] if r['amount'] == -2.67)
        self.assertEqual(roundup['activity_type'], 'ROUNDUP_BUY')
        self.assertIsNone(roundup['category'])

    def test_card_funding_transfer_is_skipped_not_imported(self):
        _, _, rows_by_account, _, stats = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        amounts = [r['amount'] for r in rows_by_account['shakepay-cash']]
        self.assertNotIn(-7.33, amounts)
        self.assertEqual(stats['skipped_card_funding_transfers'], 1)

    def test_cash_section_row_count(self):
        # Starting/closing balance snapshots are not transactions.
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        self.assertEqual(len(rows_by_account['shakepay-cash']), 4)

    def test_crypto_reward_and_interest_are_excluded_income(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        by_type = {r['activity_type']: r for r in rows_by_account['shakepay-crypto']}
        self.assertEqual(by_type['CRYPTO_REWARD']['amount'], 0.01)
        self.assertIsNone(by_type['CRYPTO_REWARD']['category'])
        self.assertEqual(by_type['CRYPTO_INTEREST']['amount'], 0.0)
        self.assertEqual(by_type['CRYPTO_DEPOSIT']['amount'], 23.98)

    def test_roundup_mirror_in_crypto_table_is_skipped(self):
        _, _, rows_by_account, _, stats = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        self.assertNotIn('ROUNDUP_BUY', {r['activity_type'] for r in rows_by_account['shakepay-crypto']})
        self.assertEqual(stats['skipped_roundup_mirrors'], 1)

    def test_crypto_balance_snapshots_are_not_transactions(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        self.assertEqual(len(rows_by_account['shakepay-crypto']), 3)

    def test_card_purchase_uses_bare_merchant_as_description(self):
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT)
        purchase = rows_by_account['shakepay-card'][0]
        self.assertEqual(purchase['description'], 'RAMBLERS')
        self.assertEqual(purchase['amount'], -7.33)
        self.assertEqual(purchase['activity_type'], 'Purchase')
        self.assertIsNone(purchase['category'])

    def test_card_funding_transfer_skipped_on_card_statement_too(self):
        _, _, rows_by_account, _, stats = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT)
        self.assertEqual(len(rows_by_account['shakepay-card']), 1)
        self.assertEqual(stats['skipped_card_funding_transfers'], 1)

    def test_unrecognized_line_is_surfaced_not_dropped(self):
        text = ACCOUNT_STATEMENT_TEXT.replace(
            '2026-08-02 13:41:17 Receive cash via Shakepay @rearea +5.00 6.73 ',
            '2026-08-02 13:41:17 Some Unrecognized Line Shape +5.00 6.73 ',
        )
        _, _, _, unparsed, _ = import_shakepay.parse_statement_text(text)
        self.assertEqual(len(unparsed), 1)
        self.assertIn('Some Unrecognized Line Shape', unparsed[0])


class TestGluedTextIsRecoveredCorrectly(unittest.TestCase):
    """Regression tests for the pypdf-version-dependent missing-space bug
    (see _insert_missing_spaces) - each assertion mirrors one from
    TestParseStatementText above, run against the glued fixtures instead
    of the cleanly-spaced ones, to prove the two produce identical rows."""

    def test_account_statement_has_zero_unparsed_lines(self):
        _, _, _, unparsed, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT_GLUED)
        self.assertEqual(unparsed, [])

    def test_card_statement_has_zero_unparsed_lines(self):
        _, _, _, unparsed, _ = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT_GLUED)
        self.assertEqual(unparsed, [])

    def test_glued_and_clean_account_statements_produce_identical_rows(self):
        _, period_a, rows_a, _, stats_a = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT)
        _, period_b, rows_b, _, stats_b = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT_GLUED)
        self.assertEqual(period_a, period_b)
        self.assertEqual(rows_a, rows_b)
        self.assertEqual(stats_a, stats_b)

    def test_glued_and_clean_card_statements_produce_identical_rows(self):
        _, period_a, rows_a, _, stats_a = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT)
        _, period_b, rows_b, _, stats_b = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT_GLUED)
        self.assertEqual(period_a, period_b)
        self.assertEqual(rows_a, rows_b)
        self.assertEqual(stats_a, stats_b)

    def test_glued_card_purchase_keeps_bare_merchant_name(self):
        # "Card purchaseRAMBLERS" must recover to merchant "RAMBLERS", not
        # "purchaseRAMBLERS" or anything with the keyword still attached.
        _, _, rows_by_account, _, _ = import_shakepay.parse_statement_text(CARD_STATEMENT_TEXT_GLUED)
        self.assertEqual(rows_by_account['shakepay-card'][0]['description'], 'RAMBLERS')

    def test_mixed_case_merchant_name_is_not_corrupted(self):
        # The fix must be keyword/format-targeted, not a general
        # lower-to-upper-case boundary rule - a rule like that would
        # wrongly split "McDonalds" into "Mc Donalds".
        text = CARD_STATEMENT_TEXT_GLUED.replace(
            '2026-08-03 09:14:06Card purchaseRAMBLERS -$7.33',
            '2026-08-03 09:14:06Card purchaseMcDonalds 40487 -$1.14',
        )
        _, _, rows_by_account, unparsed, _ = import_shakepay.parse_statement_text(text)
        self.assertEqual(unparsed, [])
        self.assertEqual(rows_by_account['shakepay-card'][0]['description'], 'McDonalds 40487')

    def test_btc_quantity_decimal_places_are_not_split(self):
        # A naive "insert a space after any 2-decimal number" rule would
        # wrongly break an 8-decimal BTC quantity like 0.00002993 after
        # its first two decimal digits ("0.00 002993"). Confirm the BTC
        # quantity survives intact and the row still carries the right
        # CAD amount.
        _, _, rows_by_account, unparsed, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT_GLUED)
        self.assertEqual(unparsed, [])
        roundup = next(r for r in rows_by_account['shakepay-cash'] if r['activity_type'] == 'ROUNDUP_BUY')
        self.assertIn('0.00002993 BTC', roundup['description'])
        self.assertEqual(roundup['amount'], -2.67)

    def test_receive_bitcoin_category_glue_is_recovered(self):
        # "Receive BitcoinBitcoin address ..." (category glued straight
        # into the fixed "Bitcoin address" description prefix) plus the
        # address itself glued directly to the signed BTC amount with no
        # space at all ("hup3+0.00021993") and "BTC" glued to the
        # following CAD value ("BTC23.98").
        _, _, rows_by_account, unparsed, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT_GLUED)
        self.assertEqual(unparsed, [])
        deposit = next(r for r in rows_by_account['shakepay-crypto'] if r['activity_type'] == 'CRYPTO_DEPOSIT')
        self.assertEqual(deposit['amount'], 23.98)

    def test_interest_row_survives_amount_glued_straight_onto_balance(self):
        # "CAD balance+0.00000003 BTC0.000.00" - no space at all between
        # the fixed description text and the amount, nor between "BTC"
        # and the CAD value that follows it.
        _, _, rows_by_account, unparsed, _ = import_shakepay.parse_statement_text(ACCOUNT_STATEMENT_TEXT_GLUED)
        self.assertEqual(unparsed, [])
        interest = next(r for r in rows_by_account['shakepay-crypto'] if r['activity_type'] == 'CRYPTO_INTEREST')
        self.assertEqual(interest['amount'], 0.0)


class TestImportShakepayText(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_account_statement_creates_cash_and_crypto_accounts(self):
        summary = import_shakepay.import_shakepay_text(self.conn, 'acct.pdf', ACCOUNT_STATEMENT_TEXT)
        account_ids = {a['account_id'] for a in summary['accounts']}
        self.assertEqual(account_ids, {'shakepay-cash', 'shakepay-crypto'})

        cash_account = finance_db.get_account(self.conn, 'shakepay-cash')
        self.assertEqual(cash_account['kind'], 'chequing')
        crypto_account = finance_db.get_account(self.conn, 'shakepay-crypto')
        self.assertEqual(crypto_account['kind'], 'bitcoin_wallet')

        self.assertEqual(finance_db.account_transaction_count(self.conn, 'shakepay-cash'), 4)
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'shakepay-crypto'), 3)

    def test_card_statement_creates_card_account(self):
        summary = import_shakepay.import_shakepay_text(self.conn, 'card.pdf', CARD_STATEMENT_TEXT)
        self.assertEqual(summary['accounts'], [{
            'account_id': 'shakepay-card', 'rows_imported': 1,
            'date_start': '2026-08-03', 'date_end': '2026-08-03',
        }])
        card_account = finance_db.get_account(self.conn, 'shakepay-card')
        self.assertEqual(card_account['kind'], 'credit_card')
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'shakepay-card'), 1)

    def test_reimporting_identical_text_is_idempotent(self):
        import_shakepay.import_shakepay_text(self.conn, 'card.pdf', CARD_STATEMENT_TEXT)
        import_shakepay.import_shakepay_text(self.conn, 'card.pdf', CARD_STATEMENT_TEXT)
        self.assertEqual(finance_db.account_transaction_count(self.conn, 'shakepay-card'), 1)

    def test_card_purchase_shows_up_in_spending_once_categorized(self):
        # Proves the actual integration point: a Shakepay card purchase,
        # once given a real category (the same pencil-edit path any other
        # uncategorized row uses), is picked up by summary.py with no
        # changes to that module - it's just another Purchase-type row.
        import summary as finance_summary

        import_shakepay.import_shakepay_text(self.conn, 'card.pdf', CARD_STATEMENT_TEXT)
        transaction = self.conn.execute('SELECT id FROM transactions').fetchone()
        finance_db.set_transaction_category_override(self.conn, transaction['id'], 'Restaurants', '2026-08-03T00:00:00Z')

        breakdown = finance_summary.category_breakdown(self.conn, '2026-08-01', '2026-08-31')
        self.assertEqual(breakdown, [{'category': 'Restaurants', 'total': 7.33}])

    def test_only_p2p_send_counts_toward_cash_flow(self):
        # P2P reuses the bank export's own already-counted expense type,
        # so the one $10 send is real Cash Flow expense. Everything else
        # (P2P_IN/E_TRFIN/ROUNDUP_BUY) must never appear in
        # summary.CHEQUING_INCOME_TYPES/CHEQUING_EXPENSE_TYPES, or it
        # would silently start counting too - the contract the "excluded
        # by default" design in the module docstring depends on.
        import summary as finance_summary

        import_shakepay.import_shakepay_text(self.conn, 'acct.pdf', ACCOUNT_STATEMENT_TEXT)
        cash_flow = finance_summary.build_cash_flow(self.conn, window='all')
        self.assertEqual(cash_flow['income'], 0.0)
        self.assertEqual(cash_flow['expense'], 10.0)


class TestResolvePdfPaths(unittest.TestCase):

    def test_plain_file_args_pass_through_unchanged(self):
        self.assertEqual(
            import_shakepay._resolve_pdf_paths(['a.pdf', 'b.pdf']),
            ['a.pdf', 'b.pdf'],
        )

    def test_directory_expands_to_its_pdfs_sorted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            for name in ('shakepay-2026-08 (1).pdf', 'shakepay-2026-08.pdf', 'notes.txt', 'export.CSV'):
                Path(tmp_dir, name).touch()
            self.assertEqual(
                import_shakepay._resolve_pdf_paths([tmp_dir]),
                [
                    os.path.join(tmp_dir, 'shakepay-2026-08 (1).pdf'),
                    os.path.join(tmp_dir, 'shakepay-2026-08.pdf'),
                ],
            )

    def test_uppercase_pdf_extension_is_matched(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            Path(tmp_dir, 'STATEMENT.PDF').touch()
            self.assertEqual(import_shakepay._resolve_pdf_paths([tmp_dir]), [os.path.join(tmp_dir, 'STATEMENT.PDF')])

    def test_empty_directory_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual(import_shakepay._resolve_pdf_paths([tmp_dir]), [])

    def test_mixes_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            Path(tmp_dir, 'card.pdf').touch()
            self.assertEqual(
                import_shakepay._resolve_pdf_paths(['explicit.pdf', tmp_dir]),
                ['explicit.pdf', os.path.join(tmp_dir, 'card.pdf')],
            )


if __name__ == '__main__':
    unittest.main()
