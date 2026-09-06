"""Computes the "Spending" section's data (finance/ARCHITECTURE.md Part A5)
straight from data/finance/finance.db - no generated cache file. Personal-
scale data (a few hundred/thousand rows) makes a live SQLite query on every
GET fast enough that a cache would only add invalidation to worry about
for no real benefit (unlike Part B's Plaid design, where the cache exists
specifically to keep a slow upstream API call out of the request path).

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

WINDOWS = {
    'month': lambda today: today.replace(day=1),
    '30d': lambda today: today - timedelta(days=30),
    '90d': lambda today: today - timedelta(days=90),
    'all': lambda today: date(1970, 1, 1),
}
DEFAULT_WINDOW = 'month'
TOP_MERCHANTS_LIMIT = 10
MONTHS_OF_TREND = 12


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


def top_merchants(conn, start, end, limit=TOP_MERCHANTS_LIMIT):
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


def build_summary(conn, window=DEFAULT_WINDOW, today=None):
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
        'byCategory': category_breakdown(conn, start, end),
        'byMonth': monthly_trend(conn),
        'topMerchants': top_merchants(conn, start, end),
    }
