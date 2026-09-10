import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db as finance_db  # noqa: E402
import networth  # noqa: E402


SAMPLE = {
    'cashAccounts': [
        {'institution': 'Wealthsimple', 'name': 'Cash', 'balance': 4250.18},
        {'institution': 'TD', 'name': 'Chequing', 'balance': 1830.52},
        {'institution': 'TD', 'name': 'Savings', 'balance': 6400.0},
        {'institution': 'Tangerine', 'name': 'Savings', 'balance': 12150.75},
        {'institution': 'Shakepay', 'name': 'CAD balance', 'balance': 320.4},
    ],
    'bitcoinHoldings': [
        {'location': 'Shakepay', 'btc': 0.085, 'valueCad': 7854.0},
        {'location': 'Hardware wallet (cold storage)', 'btc': 0.041, 'valueCad': 3788.4},
    ],
    'linesOfCredit': [
        {'institution': 'Wealthsimple', 'interestRate': 6.7, 'limit': 15000, 'balance': 0},
        {'institution': 'Tangerine', 'interestRate': 9.6, 'limit': 10000, 'balance': 3500.0},
        {'institution': 'TD', 'interestRate': 7.95, 'limit': 20000, 'balance': 0},
    ],
    'debt': {
        'studentLoan': [{'name': 'NSLSC', 'balance': 8200.0}],
        'creditCards': [
            {'institution': 'TD', 'balance': 1240.55},
            {'institution': 'RBC', 'balance': 560.2},
            {'institution': 'Tangerine', 'balance': 85.3},
            {'institution': 'Wealthsimple', 'balance': 210.0},
        ],
        'bills': [
            {'name': 'Hydro', 'balance': 145.0},
            {'name': 'Internet', 'balance': 85.0},
            {'name': 'Phone', 'balance': 60.0},
        ],
    },
}


class NetworthTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'finance.db')
        self.conn = finance_db.connect(self.db_path)
        finance_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()


class TestAccountsMigration(unittest.TestCase):
    """Migration 2 (db._add_networth_account_columns): extends an
    existing accounts table without disturbing what's already there."""

    def test_a_fresh_database_already_has_the_new_columns(self):
        tmp = tempfile.TemporaryDirectory()
        conn = finance_db.connect(os.path.join(tmp.name, 'finance.db'))
        finance_db.init_schema(conn)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(accounts)')}
        self.assertIn('currency', columns)
        self.assertIn('closed_at', columns)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], finance_db.SCHEMA_VERSION)
        conn.close()
        tmp.cleanup()

    def test_an_existing_pre_phase_1_database_gets_the_columns_added(self):
        tmp = tempfile.TemporaryDirectory()
        conn = finance_db.connect(os.path.join(tmp.name, 'finance.db'))
        finance_db.init_schema(conn)

        # Simulate a database from before Part C: drop back to the old
        # accounts shape and an existing row, at schema version 1.
        conn.execute('DROP TABLE accounts')
        conn.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY, label TEXT NOT NULL, institution TEXT, kind TEXT NOT NULL)")
        conn.execute("INSERT INTO accounts VALUES ('main-credit-card', 'Credit Card', NULL, 'credit_card')")
        conn.execute('PRAGMA user_version = 1')
        conn.commit()

        finance_db.migrate(conn)

        columns = {row[1] for row in conn.execute('PRAGMA table_info(accounts)')}
        self.assertIn('currency', columns)
        self.assertIn('closed_at', columns)
        row = finance_db.get_account(conn, 'main-credit-card')
        self.assertEqual(row['label'], 'Credit Card')
        self.assertEqual(row['currency'], 'CAD')
        self.assertIsNone(row['closed_at'])
        conn.close()
        tmp.cleanup()

    def test_migrating_twice_does_not_fail(self):
        tmp = tempfile.TemporaryDirectory()
        conn = finance_db.connect(os.path.join(tmp.name, 'finance.db'))
        finance_db.init_schema(conn)
        finance_db.migrate(conn)  # already at SCHEMA_VERSION - must be a no-op, not an error
        columns = {row[1] for row in conn.execute('PRAGMA table_info(accounts)')}
        self.assertIn('currency', columns)
        conn.close()
        tmp.cleanup()


class TestNetWorthSign(unittest.TestCase):

    def test_asset_kinds_are_positive(self):
        for kind in ('chequing', 'savings', 'investment', 'bitcoin_wallet'):
            self.assertEqual(networth.net_worth_sign(kind), 1)

    def test_liability_kinds_are_negative(self):
        for kind in ('credit_card', 'line_of_credit', 'loan', 'bill'):
            self.assertEqual(networth.net_worth_sign(kind), -1)

    def test_unknown_kind_raises(self):
        with self.assertRaises(networth.UnknownAccountKindError):
            networth.net_worth_sign('not-a-real-kind')


class TestRecordBalance(NetworthTestCase):

    def test_creates_the_account_and_a_snapshot(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6400.0)

        account = finance_db.get_account(self.conn, 'td-savings')
        self.assertEqual(account['label'], 'Savings')
        self.assertEqual(account['kind'], 'savings')

        balances = networth.latest_balances(self.conn)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0]['balance_cad'], 6400.0)
        self.assertEqual(balances[0]['source'], 'manual')

    def test_records_an_import_batch_for_the_audit_trail(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6400.0)
        batch = self.conn.execute('SELECT kind FROM import_batches').fetchone()
        self.assertEqual(batch['kind'], 'manual_balance')

    def test_negative_balance_is_rejected(self):
        # balance_cad is always a positive magnitude (ARCHITECTURE.md
        # C5a) - kind alone decides the sign, so a negative value here
        # would double-apply the sign.
        with self.assertRaises(ValueError):
            with self.conn:
                networth.record_balance(self.conn, 'nslsc', 'NSLSC', None, 'loan', '2026-09-07', -8200.0)

    def test_terms_are_recorded_only_when_given(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-loc', 'Line of Credit', 'TD', 'line_of_credit', '2026-09-07', 0.0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) AS n FROM account_terms_snapshots').fetchone()['n'], 0)

        with self.conn:
            networth.record_balance(
                self.conn, 'wealthsimple-loc', 'Line of Credit', 'Wealthsimple', 'line_of_credit',
                '2026-09-07', 0.0, interest_rate=6.7, credit_limit=15000,
            )
        terms = self.conn.execute('SELECT * FROM account_terms_snapshots').fetchone()
        self.assertEqual(terms['interest_rate'], 6.7)
        self.assertEqual(terms['credit_limit'], 15000)

    def test_a_later_entry_becomes_the_latest_balance(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-01', 6000.0)
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6400.0)

        balances = networth.latest_balances(self.conn)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0]['as_of_date'], '2026-09-07')
        self.assertEqual(balances[0]['balance_cad'], 6400.0)

    def test_a_same_day_correction_wins_over_the_earlier_entry(self):
        # Both share as_of_date - latest_account_balances (csv_schema.sql)
        # must break the tie on recorded_at, not just as_of_date, or the
        # view would arbitrarily pick one.
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6000.0)
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6400.0)

        balances = networth.latest_balances(self.conn)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0]['balance_cad'], 6400.0)

    def test_history_is_never_overwritten(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-08-01', 6000.0)
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-01', 6400.0)

        history = self.conn.execute(
            'SELECT as_of_date, balance_cad FROM account_balance_snapshots ORDER BY as_of_date'
        ).fetchall()
        self.assertEqual([(r['as_of_date'], r['balance_cad']) for r in history],
                          [('2026-08-01', 6000.0), ('2026-09-01', 6400.0)])


class TestLatestBalances(NetworthTestCase):

    def test_closed_accounts_are_excluded(self):
        with self.conn:
            networth.record_balance(self.conn, 'old-account', 'Old', None, 'savings', '2026-01-01', 100.0)
        self.conn.execute("UPDATE accounts SET closed_at = '2026-06-01' WHERE id = 'old-account'")
        self.conn.commit()

        self.assertEqual(networth.latest_balances(self.conn), [])

    def test_filters_by_kind(self):
        with self.conn:
            networth.record_balance(self.conn, 'td-savings', 'Savings', 'TD', 'savings', '2026-09-07', 6400.0)
            networth.record_balance(self.conn, 'nslsc', 'NSLSC', None, 'loan', '2026-09-07', 8200.0)

        savings_only = networth.latest_balances(self.conn, kinds={'savings'})
        self.assertEqual([r['id'] for r in savings_only], ['td-savings'])


class TestSeedFromSampleJson(NetworthTestCase):

    def test_seeds_every_account_from_the_sample_data(self):
        counts = networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)
        # 5 cash + 2 bitcoin + 1 loan + 3 non-Wealthsimple credit cards +
        # 3 bills + 3 lines of credit + main-credit-card = 18
        self.assertEqual(len(counts), 18)

    def test_the_wealthsimple_credit_card_folds_into_main_credit_card(self):
        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)

        account = finance_db.get_account(self.conn, 'main-credit-card')
        self.assertEqual(account['institution'], 'Wealthsimple')

        balance = next(b for b in networth.latest_balances(self.conn) if b['id'] == 'main-credit-card')
        self.assertEqual(balance['balance_cad'], 210.0)

        # No second account was created for it.
        wealthsimple_cards = [
            r for r in self.conn.execute("SELECT id FROM accounts WHERE institution = 'Wealthsimple' AND kind = 'credit_card'")
        ]
        self.assertEqual(len(wealthsimple_cards), 1)

    def test_wealthsimple_cash_is_a_separate_account_from_main_credit_card(self):
        # Confirmed 2026-09-07: unlike the credit card, "Wealthsimple
        # Cash" is a different product from any already-imported account.
        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)
        cash = finance_db.get_account(self.conn, 'wealthsimple-cash')
        self.assertIsNotNone(cash)
        self.assertEqual(cash['kind'], 'savings')

    def test_lines_of_credit_get_their_terms_recorded(self):
        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)
        terms = {
            r['account_id']: (r['interest_rate'], r['credit_limit'])
            for r in self.conn.execute('SELECT account_id, interest_rate, credit_limit FROM account_terms_snapshots')
        }
        self.assertEqual(terms['wealthsimple-loc'], (6.7, 15000))
        self.assertEqual(terms['tangerine-loc'], (9.6, 10000))
        self.assertEqual(terms['td-loc'], (7.95, 20000))

    def test_balances_match_the_sample_values_exactly(self):
        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)
        balances = {r['id']: r['balance_cad'] for r in networth.latest_balances(self.conn)}
        self.assertEqual(balances['wealthsimple-cash'], 4250.18)
        self.assertEqual(balances['td-chequing'], 1830.52)
        self.assertEqual(balances['shakepay-btc'], 7854.0)
        self.assertEqual(balances['nslsc-student-loan'], 8200.0)
        self.assertEqual(balances['bill-hydro'], 145.0)

    def test_refuses_to_reseed_an_already_seeded_database(self):
        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)
        with self.assertRaises(RuntimeError):
            networth.seed_from_sample_json(self.conn, as_of_date='2026-09-08', sample=SAMPLE)

    def test_does_not_disturb_an_already_imported_chequing_account(self):
        # The real chequing account from a CSV import (import_csv.py)
        # must survive the seed untouched - it has no balance snapshot of
        # its own, and the seed must not invent one for it.
        finance_db.upsert_account(self.conn, 'WK1WPY033CAD', 'Chequing', None, 'chequing')
        self.conn.commit()

        networth.seed_from_sample_json(self.conn, as_of_date='2026-09-07', sample=SAMPLE)

        account = finance_db.get_account(self.conn, 'WK1WPY033CAD')
        self.assertEqual(account['label'], 'Chequing')
        balances = [b['id'] for b in networth.latest_balances(self.conn)]
        self.assertNotIn('WK1WPY033CAD', balances)


if __name__ == '__main__':
    unittest.main()
