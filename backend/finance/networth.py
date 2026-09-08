"""Net worth accounts - Cash, Bitcoin, Debt, and Lines of Credit today;
Investments join in Phase 2 (finance/ARCHITECTURE.md Part C, Phase 1).

None of these have a CSV or API - they're a hand-maintained sample JSON
file (static/finance/finance-dashboard.json). Every balance is stored as
a dated, append-only snapshot (account_balance_snapshots) rather than a
mutable column, so "current" is just "the latest one" - the
latest_account_balances view - and history falls out of the same table
for free (ARCHITECTURE.md C2/C5c).
"""

import json
import os
from datetime import datetime, timezone

import db as finance_db

# Which side of net worth a kind counts on - deliberately Python, not a
# database column (ARCHITECTURE.md C5a: an `is_asset` column let a row
# contradict itself, e.g. kind='loan', is_asset=1). Same pattern as
# summary.py's CHEQUING_INCOME_TYPES/CHEQUING_EXPENSE_TYPES living in
# code rather than the schema.
ASSET_KINDS = {'chequing', 'savings', 'investment', 'bitcoin_wallet'}
LIABILITY_KINDS = {'credit_card', 'line_of_credit', 'loan', 'bill'}

# These two sets are meant to exactly partition db.ACCOUNT_KINDS - the
# accounts.kind CHECK constraint's closed domain (see csv_schema.sql). If
# a kind is ever added to one without the other, this catches the drift
# at import time instead of net_worth_sign() silently mis-signing it (or
# the database accepting a kind net worth math doesn't know either side
# of).
assert not (ASSET_KINDS & LIABILITY_KINDS), 'a kind cannot be both an asset and a liability'
assert (ASSET_KINDS | LIABILITY_KINDS) == finance_db.ACCOUNT_KINDS, (
    'ASSET_KINDS/LIABILITY_KINDS must partition db.ACCOUNT_KINDS exactly'
)

SAMPLE_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'static', 'finance', 'finance-dashboard.json',
)


class UnknownAccountKindError(ValueError):
    pass


def net_worth_sign(kind):
    """+1 for an asset kind, -1 for a liability kind - what a balance's
    `kind` (not a stored sign, see ASSET_KINDS above) contributes to net
    worth as."""
    if kind in ASSET_KINDS:
        return 1
    if kind in LIABILITY_KINDS:
        return -1
    raise UnknownAccountKindError(f'Unknown account kind: {kind!r}')


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record_balance(conn, account_id, label, institution, kind, as_of_date, balance_cad,
                    source='manual', interest_rate=None, credit_limit=None, batch_kind='manual_balance'):
    """Upserts the account, records one import_batches row for the audit
    trail, one account_balance_snapshots row, and (only when a term is
    actually given) one account_terms_snapshots row.

    Does not manage its own transaction - callers wrap `with conn:`, same
    convention as import_csv.import_csv_text - so a caller inserting many
    balances (the seed below) can do it as one atomic unit rather than
    one commit per account.

    `balance_cad` must be a positive magnitude (ARCHITECTURE.md C5a) -
    `kind` alone decides which side of net worth it lands on.
    """
    if balance_cad < 0:
        raise ValueError(
            f'balance_cad must be a positive magnitude, not a signed value - kind {kind!r} already '
            f'determines the sign (got {balance_cad})'
        )

    now = _now_iso()
    finance_db.upsert_account(conn, account_id, label, institution, kind)
    batch_id = finance_db.create_import_batch(conn, kind=batch_kind, imported_at=now)
    finance_db.insert_balance_snapshot(conn, account_id, as_of_date, balance_cad, source, batch_id, now)
    if interest_rate is not None or credit_limit is not None:
        finance_db.insert_terms_snapshot(conn, account_id, as_of_date, interest_rate, credit_limit, now)
    return batch_id


def latest_balances(conn, kinds=None):
    """Every open account's latest known balance (ARCHITECTURE.md C6 -
    closed_at accounts drop out here, before any net worth math sees
    them), optionally narrowed to a set of kinds - what each dashboard
    section (C7) will filter to once Phase 3 wires it up."""
    rows = conn.execute(
        '''SELECT a.id, a.label, a.institution, a.kind, a.currency,
                  b.as_of_date, b.balance_cad, b.source
           FROM accounts a
           JOIN latest_account_balances b ON b.account_id = a.id
           WHERE a.closed_at IS NULL
           ORDER BY a.kind, a.label'''
    ).fetchall()
    result = [dict(r) for r in rows]
    if kinds is not None:
        result = [r for r in result if r['kind'] in kinds]
    return result


# --- One-time seed from the hardcoded sample dashboard (ARCHITECTURE.md
# C9.4) - Cash, Bitcoin, Debt, and Lines of Credit only; Investments wait
# for Phase 2's securities/holdings tables. -------------------------------

# Deliberately an explicit, hand-written list rather than a generic
# JSON-to-account inference pass: this seeds one specific, known sample
# file exactly once, not an arbitrary future edit of it, and inferring
# `kind`/ids from free-text fields (e.g. "is 'TD' here the chequing
# account, the credit card, or the line of credit?") is exactly the kind
# of ambiguity a fixed mapping avoids by construction. Confirmed
# 2026-09-07: the "Wealthsimple" debt.creditCards entry is the SAME
# physical card as the existing main-credit-card account (folds in, per
# C5h) - the "Wealthsimple Cash" cashAccounts entry is a DIFFERENT
# account from the real chequing account already tracked via CSV import.
_SEED_ACCOUNTS = [
    # (account_id, label, institution, kind, json_path, extra)
    ('wealthsimple-cash', 'Cash', 'Wealthsimple', 'savings', ('cashAccounts', 0, 'balance'), {}),
    ('td-chequing', 'Chequing', 'TD', 'chequing', ('cashAccounts', 1, 'balance'), {}),
    ('td-savings', 'Savings', 'TD', 'savings', ('cashAccounts', 2, 'balance'), {}),
    ('tangerine-savings', 'Savings', 'Tangerine', 'savings', ('cashAccounts', 3, 'balance'), {}),
    ('shakepay-cad', 'CAD balance', 'Shakepay', 'savings', ('cashAccounts', 4, 'balance'), {}),
    ('shakepay-btc', 'Shakepay', None, 'bitcoin_wallet', ('bitcoinHoldings', 0, 'valueCad'), {}),
    ('cold-storage-btc', 'Hardware wallet (cold storage)', None, 'bitcoin_wallet',
     ('bitcoinHoldings', 1, 'valueCad'), {}),
    ('nslsc-student-loan', 'NSLSC', None, 'loan', ('debt', 'studentLoan', 0, 'balance'), {}),
    ('td-credit-card', 'Credit Card', 'TD', 'credit_card', ('debt', 'creditCards', 0, 'balance'), {}),
    ('rbc-credit-card', 'Credit Card', 'RBC', 'credit_card', ('debt', 'creditCards', 1, 'balance'), {}),
    ('tangerine-credit-card', 'Credit Card', 'Tangerine', 'credit_card',
     ('debt', 'creditCards', 2, 'balance'), {}),
    # debt.creditCards[3] (Wealthsimple, $210) is handled separately below - it
    # folds into main-credit-card rather than appearing in this list (C5h).
    ('bill-hydro', 'Hydro', None, 'bill', ('debt', 'bills', 0, 'balance'), {}),
    ('bill-internet', 'Internet', None, 'bill', ('debt', 'bills', 1, 'balance'), {}),
    ('bill-phone', 'Phone', None, 'bill', ('debt', 'bills', 2, 'balance'), {}),
    ('wealthsimple-loc', 'Line of Credit', 'Wealthsimple', 'line_of_credit', ('linesOfCredit', 0, 'balance'),
     {'terms': ('linesOfCredit', 0)}),
    ('tangerine-loc', 'Line of Credit', 'Tangerine', 'line_of_credit', ('linesOfCredit', 1, 'balance'),
     {'terms': ('linesOfCredit', 1)}),
    ('td-loc', 'Line of Credit', 'TD', 'line_of_credit', ('linesOfCredit', 2, 'balance'),
     {'terms': ('linesOfCredit', 2)}),
]


def _dig(data, path):
    value = data
    for key in path:
        value = value[key]
    return value


def _read_sample_json(path=None):
    with open(path or SAMPLE_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def seed_from_sample_json(conn, path=None, as_of_date=None, sample=None):
    """One-time seed of account_balance_snapshots/account_terms_snapshots
    from static/finance/finance-dashboard.json. `as_of_date` defaults to
    today - there is no earlier real history to backfill, since this has
    always been hand-maintained sample data (ARCHITECTURE.md A1/C9.4).

    Refuses to run against a database that already has balance snapshots,
    mirroring tasks_db.migrate_from_json's guard - this seeds a genuinely
    empty net worth history, not a re-import. Returns a
    {account_id: batch_id} dict.
    """
    existing = conn.execute('SELECT COUNT(*) AS n FROM account_balance_snapshots').fetchone()['n']
    if existing:
        raise RuntimeError(
            'refusing to seed: account_balance_snapshots already has rows. This is a one-time seed '
            'for an empty net worth history, not a re-import - delete existing rows first if you '
            'really mean to reseed.'
        )

    data = sample if sample is not None else _read_sample_json(path)
    as_of_date = as_of_date or datetime.now(timezone.utc).strftime('%Y-%m-%d')

    batch_ids = {}
    with conn:
        for account_id, label, institution, kind, balance_path, extra in _SEED_ACCOUNTS:
            balance = _dig(data, balance_path)
            interest_rate = credit_limit = None
            if 'terms' in extra:
                loc = _dig(data, extra['terms'])
                interest_rate = loc.get('interestRate')
                credit_limit = loc.get('limit')
            batch_ids[account_id] = record_balance(
                conn, account_id, label, institution, kind, as_of_date, balance,
                interest_rate=interest_rate, credit_limit=credit_limit,
            )

        # C5h: the same physical card as the already-imported
        # main-credit-card account, not a second row. Also fills in that
        # account's institution, which import_csv.py leaves NULL (the
        # credit card export has no institution column to read it from).
        wealthsimple_card_balance = _dig(data, ('debt', 'creditCards', 3, 'balance'))
        batch_ids['main-credit-card'] = record_balance(
            conn, 'main-credit-card', 'Credit Card', 'Wealthsimple', 'credit_card',
            as_of_date, wealthsimple_card_balance,
        )

    return batch_ids


def main():
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != 'seed':
        print(__doc__)
        print('Usage: python3 backend/finance/networth.py seed')
        raise SystemExit(1)

    conn = finance_db.connect()
    try:
        finance_db.init_schema(conn)
        try:
            batch_ids = seed_from_sample_json(conn)
        except RuntimeError as exc:
            print('Seed aborted: %s' % exc)
            raise SystemExit(1)
    finally:
        conn.close()

    print(f'Seeded {len(batch_ids)} accounts from {SAMPLE_JSON_PATH}')


if __name__ == '__main__':
    main()
