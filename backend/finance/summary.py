"""Computes the "Spending" and "Cash Flow" sections' data
(finance/ARCHITECTURE.md Part A5) straight from data/finance/finance.db -
no generated cache file. Personal-scale data (a few hundred/thousand rows)
makes a live SQLite query on every GET fast enough that a cache would only
add invalidation to worry about for no real benefit (unlike Part B's Plaid
design, where the cache exists specifically to keep a slow upstream API
call out of the request path).

Pending purchases count the same as Completed ones everywhere here
(decided 2026-09-06, ARCHITECTURE.md A8) - nothing below filters on
`status`.

`Purchase` and `Refund` rows are netted together (a refund reduces that
category's/month's spend); `Payment` and `Uncategorized` rows are excluded
everywhere - they're the credit card bill being paid off, not spend
(ARCHITECTURE.md A2).
"""

from datetime import date, timedelta

# `amount` is negative for Purchase (an outflow) and positive for Refund
# (money back), so `-amount` turns a Purchase into a positive "spent"
# figure and a Refund into a negative one that nets against it.
_SPEND_CASE = "SUM(CASE WHEN activity_type IN ('Purchase', 'Refund') THEN -amount ELSE 0 END)"
_SPEND_FILTER = "category IS NOT NULL AND category != 'Uncategorized' AND activity_type IN ('Purchase', 'Refund')"

# Cash flow (ARCHITECTURE.md Part A, "Cash Flow" / Phase 4): classifies
# chequing rows' `activity_type` (which, per import_csv.py, actually holds
# the export's finer-grained activity_sub_type - AFT_IN, SPEND, CASHBACK,
# E_TRFOUT, ...) into real income, real expense, or neither.
#
# Deliberately NOT classified as either income or expense: E_TRFIN/
# E_TRFOUT (Interac e-Transfers), TRANSFER/TRANSFER_TF, and EFT. These are
# indistinguishable, from the CSV alone, between "money moved to/from
# another person" (real income/expense) and "money moved to/from one of
# your own other accounts" (not real income/expense at all - e.g. sending
# money to an investment account, or TRANSFER rows that are literally the
# credit card bill being paid, already counted as expense on the card
# side). Treating them all as transfers is the conservative default -
# it undercounts real income/expense involving another person, but never
# double-counts your own money moving between your own accounts. Revisit
# if this turns out to hide too much.
CHEQUING_INCOME_TYPES = ('AFT_IN', 'CASHBACK', 'GIVEAWAY', 'Interest')
CHEQUING_EXPENSE_TYPES = ('SPEND', 'AFT_OUT', 'OBP_OUT', 'P2P')

WINDOWS = {
    'month': lambda today: today.replace(day=1),
    '30d': lambda today: today - timedelta(days=30),
    '90d': lambda today: today - timedelta(days=90),
    'all': lambda today: date(1970, 1, 1),
}
DEFAULT_WINDOW = 'month'
TOP_MERCHANTS_LIMIT = 10
MONTHS_OF_TREND = 12


def _placeholders(values):
    return ','.join('?' for _ in values)


def window_start(window, today):
    return WINDOWS.get(window, WINDOWS[DEFAULT_WINDOW])(today).isoformat()


def category_breakdown(conn, start, end):
    rows = conn.execute(
        f'''SELECT category, {_SPEND_CASE} AS total
            FROM transactions
            WHERE {_SPEND_FILTER} AND date >= ? AND date <= ?
            GROUP BY category
            HAVING total > 0
            ORDER BY total DESC''',
        (start, end),
    ).fetchall()
    return [{'category': r['category'], 'total': round(r['total'], 2)} for r in rows]


def monthly_trend(conn, months=MONTHS_OF_TREND):
    rows = conn.execute(
        f'''SELECT substr(date, 1, 7) AS month, {_SPEND_CASE} AS total
            FROM transactions
            WHERE {_SPEND_FILTER}
            GROUP BY month
            ORDER BY month'''
    ).fetchall()
    trend = [{'month': r['month'], 'total': round(max(r['total'], 0), 2)} for r in rows]
    return trend[-months:]


def top_merchants(conn, start, end, limit=TOP_MERCHANTS_LIMIT, category=None):
    if category:
        rows = conn.execute(
            '''SELECT description AS merchant, SUM(-amount) AS total, COUNT(*) AS count
               FROM transactions
               WHERE activity_type = 'Purchase' AND date >= ? AND date <= ? AND category = ?
               GROUP BY description
               ORDER BY total DESC
               LIMIT ?''',
            (start, end, category, limit),
        ).fetchall()
        return [{'merchant': r['merchant'], 'total': round(r['total'], 2), 'count': r['count']} for r in rows]

    rows = conn.execute(
        '''SELECT description AS merchant, SUM(-amount) AS total, COUNT(*) AS count
           FROM transactions
           WHERE activity_type = 'Purchase' AND date >= ? AND date <= ?
           GROUP BY description
           ORDER BY total DESC
           LIMIT ?''',
        (start, end, limit),
    ).fetchall()
    return [{'merchant': r['merchant'], 'total': round(r['total'], 2), 'count': r['count']} for r in rows]


def build_summary(conn, window=DEFAULT_WINDOW, today=None, category=None):
    """`category`, when given, narrows topMerchants to just that category
    (the dashboard's click-a-category-to-filter-merchants interaction) -
    byCategory/byMonth are unaffected, so the donut/legend stay showing the
    whole picture while only the merchants list drills down."""
    if window not in WINDOWS:
        window = DEFAULT_WINDOW
    today = today or date.today()
    start = window_start(window, today)
    end = today.isoformat()

    return {
        'asOf': end,
        'window': window,
        'windowStart': start,
        'windowEnd': end,
        'categoryFilter': category,
        'byCategory': category_breakdown(conn, start, end),
        'byMonth': monthly_trend(conn),
        'topMerchants': top_merchants(conn, start, end, category=category),
    }


# --- Cash flow (income vs expense) ------------------------------------

def chequing_income_total(conn, start, end):
    row = conn.execute(
        f'''SELECT COALESCE(SUM(t.amount), 0) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.kind = 'chequing'
              AND t.activity_type IN ({_placeholders(CHEQUING_INCOME_TYPES)})
              AND t.date >= ? AND t.date <= ?''',
        (*CHEQUING_INCOME_TYPES, start, end),
    ).fetchone()
    return max(row['total'], 0.0)


def chequing_expense_total(conn, start, end):
    row = conn.execute(
        f'''SELECT COALESCE(SUM(-t.amount), 0) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.kind = 'chequing'
              AND t.activity_type IN ({_placeholders(CHEQUING_EXPENSE_TYPES)})
              AND t.date >= ? AND t.date <= ?''',
        (*CHEQUING_EXPENSE_TYPES, start, end),
    ).fetchone()
    return max(row['total'], 0.0)


def credit_card_expense_total(conn, start, end):
    """The same "real spend" figure category_breakdown()/monthly_trend()
    already compute (Purchase netted against Refund, Payment/Uncategorized
    excluded) - reused here as the credit-card side of total expense.
    Clamped at 0 the same way category_breakdown's `HAVING total > 0` and
    monthly_trend's `max(..., 0)` already are: a window where refunds
    outweigh purchases is "no net spend," not negative expense."""
    row = conn.execute(
        f'''SELECT COALESCE({_SPEND_CASE}, 0) AS total FROM transactions
            WHERE {_SPEND_FILTER} AND date >= ? AND date <= ?''',
        (start, end),
    ).fetchone()
    return max(row['total'], 0.0)


def cash_flow_by_month(conn, months=MONTHS_OF_TREND):
    income_rows = conn.execute(
        f'''SELECT substr(t.date, 1, 7) AS month, SUM(t.amount) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_INCOME_TYPES)})
            GROUP BY month''',
        CHEQUING_INCOME_TYPES,
    ).fetchall()
    income_by_month = {r['month']: r['total'] for r in income_rows}

    chequing_expense_rows = conn.execute(
        f'''SELECT substr(t.date, 1, 7) AS month, SUM(-t.amount) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_EXPENSE_TYPES)})
            GROUP BY month''',
        CHEQUING_EXPENSE_TYPES,
    ).fetchall()
    cc_expense_rows = conn.execute(
        f'''SELECT substr(date, 1, 7) AS month, {_SPEND_CASE} AS total
            FROM transactions WHERE {_SPEND_FILTER} GROUP BY month'''
    ).fetchall()

    expense_by_month = {}
    for r in chequing_expense_rows:
        expense_by_month[r['month']] = expense_by_month.get(r['month'], 0.0) + r['total']
    for r in cc_expense_rows:
        expense_by_month[r['month']] = expense_by_month.get(r['month'], 0.0) + r['total']

    months_set = sorted(set(income_by_month) | set(expense_by_month))[-months:]
    return [
        {
            'month': m,
            'income': round(income_by_month.get(m, 0.0), 2),
            'expense': round(max(expense_by_month.get(m, 0.0), 0.0), 2),
        }
        for m in months_set
    ]


def build_cash_flow(conn, window=DEFAULT_WINDOW, today=None):
    if window not in WINDOWS:
        window = DEFAULT_WINDOW
    today = today or date.today()
    start = window_start(window, today)
    end = today.isoformat()

    income = chequing_income_total(conn, start, end)
    expense = chequing_expense_total(conn, start, end) + credit_card_expense_total(conn, start, end)

    return {
        'window': window,
        'windowStart': start,
        'windowEnd': end,
        'income': round(income, 2),
        'expense': round(expense, 2),
        'net': round(income - expense, 2),
        'byMonth': cash_flow_by_month(conn),
    }
