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

`Purchase`/`Refund` (credit card) and the chequing expense types below are
all netted together within Spending (a refund, or a reversed debit,
reduces that category's/month's spend); `Payment` and `Uncategorized`
rows are excluded everywhere - they're the credit card bill being paid
off, not spend (ARCHITECTURE.md A2).

Every query that touches category reads `effective_category` from the
`transactions_effective` view (csv_schema.sql), never `transactions.category`
directly - that view is where the "Editing categories" one-time/permanent
override system (db.py, ARCHITECTURE.md) actually takes effect, so a
correction is reflected everywhere uniformly without each query
reimplementing the same resolution logic.
"""

from datetime import date, timedelta

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

# `amount` is negative for an outflow (credit card Purchase, or a chequing
# expense-type row) and positive for money back (credit card Refund, or a
# reversed debit), so `-amount` turns an outflow into a positive "spent"
# figure and money back into a negative one that nets against it.
#
# Two different scopes share this shape, kept as two separate constants
# rather than one, because conflating them would double-count in Cash Flow:
#
#   _CC_SPEND_CASE/_CC_SPEND_FILTER - credit card only (Purchase/Refund).
#     Used by Cash Flow's credit_card_expense_total() and
#     cash_flow_by_month()/cash_flow_month_transactions()'s credit-card
#     side, which are always added to chequing_expense_total()'s own,
#     separately-queried chequing rows - widening this one would count
#     chequing expense rows twice.
#   _SPENDING_CASE/_SPENDING_FILTER - credit card PLUS chequing expense
#     types (ARCHITECTURE.md A5g: folding chequing spend, e.g. rent paid
#     by pre-authorized debit, into Spending so it can be categorized the
#     same way credit-card purchases are). Used only by category_breakdown()
#     and monthly_trend() - Cash Flow's own totals never read this one.
_CC_ACTIVITY_TYPES_SQL = "'Purchase','Refund'"
_CC_SPEND_CASE = f"SUM(CASE WHEN activity_type IN ({_CC_ACTIVITY_TYPES_SQL}) THEN -amount ELSE 0 END)"
_CC_SPEND_FILTER = (
    "effective_category IS NOT NULL AND effective_category != 'Uncategorized' "
    f"AND activity_type IN ({_CC_ACTIVITY_TYPES_SQL})"
)

_SPENDING_ACTIVITY_TYPES = ('Purchase', 'Refund') + CHEQUING_EXPENSE_TYPES
_SPENDING_ACTIVITY_TYPES_SQL = ','.join(f"'{t}'" for t in _SPENDING_ACTIVITY_TYPES)
_SPENDING_CASE = f"SUM(CASE WHEN activity_type IN ({_SPENDING_ACTIVITY_TYPES_SQL}) THEN -amount ELSE 0 END)"
_SPENDING_FILTER = (
    "effective_category IS NOT NULL AND effective_category != 'Uncategorized' "
    f"AND activity_type IN ({_SPENDING_ACTIVITY_TYPES_SQL})"
)

# Friendly labels for the income dialog's "by type" breakdown (below) -
# groups rows like "Cash back - Credit card" and "Interest received"
# under the same bucket their raw activity_type already sorts them into,
# rather than inventing a separate description-keyword classifier.
INCOME_TYPE_LABELS = {
    'AFT_IN': 'Deposits',
    'CASHBACK': 'Cashback',
    'GIVEAWAY': 'Giveaways',
    'Interest': 'Interest',
}

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
        f'''SELECT effective_category AS category, {_SPENDING_CASE} AS total
            FROM transactions_effective
            WHERE {_SPENDING_FILTER} AND date >= ? AND date <= ?
            GROUP BY effective_category
            HAVING total > 0
            ORDER BY total DESC''',
        (start, end),
    ).fetchall()
    return [{'category': r['category'], 'total': round(r['total'], 2)} for r in rows]


def monthly_trend(conn, months=MONTHS_OF_TREND):
    rows = conn.execute(
        f'''SELECT substr(date, 1, 7) AS month, {_SPENDING_CASE} AS total
            FROM transactions_effective
            WHERE {_SPENDING_FILTER}
            GROUP BY month
            ORDER BY month'''
    ).fetchall()
    trend = [{'month': r['month'], 'total': round(max(r['total'], 0), 2)} for r in rows]
    return trend[-months:]


def monthly_trend_by_source(conn, months=MONTHS_OF_TREND):
    """Same figure as monthly_trend(), broken down by which account each
    row came from - what the Spend by Month chart's colour-per-source
    stacked bars read (finance/README.md). `source` is
    accounts.institution when set (e.g. "Shakepay" - already shared
    across all three shakepay-* accounts, so they merge into one
    series, per import_shakepay.py's ACCOUNTS table) falling back to the
    account's own label otherwise (e.g. bank chequing accounts, which
    import_csv.py doesn't set an institution for)."""
    rows = conn.execute(
        f'''SELECT substr(t.date, 1, 7) AS month,
                   COALESCE(a.institution, a.label) AS source,
                   {_SPENDING_CASE} AS total
            FROM transactions_effective t
            JOIN accounts a ON a.id = t.account_id
            WHERE {_SPENDING_FILTER}
            GROUP BY month, source
            HAVING total > 0
            ORDER BY month'''
    ).fetchall()

    by_month = {}
    for r in rows:
        by_month.setdefault(r['month'], {})[r['source']] = round(r['total'], 2)

    months_sorted = sorted(by_month)[-months:]
    return [{'month': m, 'bySource': by_month[m]} for m in months_sorted]


def top_merchants(conn, start, end, limit=TOP_MERCHANTS_LIMIT, category=None):
    if category:
        rows = conn.execute(
            f'''SELECT description AS merchant, SUM(-amount) AS total, COUNT(*) AS count
               FROM transactions_effective
               WHERE activity_type IN ({_SPENDING_ACTIVITY_TYPES_SQL}) AND date >= ? AND date <= ? AND effective_category = ?
               GROUP BY description
               ORDER BY total DESC
               LIMIT ?''',
            (start, end, category, limit),
        ).fetchall()
        return [{'merchant': r['merchant'], 'total': round(r['total'], 2), 'count': r['count']} for r in rows]

    rows = conn.execute(
        f'''SELECT description AS merchant, SUM(-amount) AS total, COUNT(*) AS count
           FROM transactions
           WHERE activity_type IN ({_SPENDING_ACTIVITY_TYPES_SQL}) AND date >= ? AND date <= ?
           GROUP BY description
           ORDER BY total DESC
           LIMIT ?''',
        (start, end, limit),
    ).fetchall()
    return [{'merchant': r['merchant'], 'total': round(r['total'], 2), 'count': r['count']} for r in rows]


def merchant_transactions(conn, description, start, end):
    """Individual spend transactions for one merchant, newest first - what
    the "Edit category" dialog's one-time-fix picker lists (ARCHITECTURE.md
    "Editing categories"). Covers credit card Purchase/Refund rows and
    chequing expense-type rows alike (ARCHITECTURE.md A5g), same
    `_SPENDING_ACTIVITY_TYPES` scope as top_merchants(). `category` in the
    response is already the effective (post-override) one."""
    rows = conn.execute(
        f'''SELECT id, date, amount, effective_category AS category
           FROM transactions_effective
           WHERE activity_type IN ({_SPENDING_ACTIVITY_TYPES_SQL}) AND description = ? AND date >= ? AND date <= ?
           ORDER BY date DESC, id DESC''',
        (description, start, end),
    ).fetchall()
    return [{'id': r['id'], 'date': r['date'], 'amount': round(r['amount'], 2), 'category': r['category']} for r in rows]


def btc_accumulated_by_month(conn, months=MONTHS_OF_TREND):
    """BTC bought via Shakepay's round-up-your-purchase feature, per
    month (finance/README.md) - transactions.btc_quantity, set only on
    import_shakepay.py's ROUNDUP_BUY rows. Round-ups aren't spend or
    income (they convert CAD you already have into BTC you keep - see
    import_shakepay.py's module docstring), so this is independent of
    _SPENDING_FILTER/category entirely - a round-up counts here whether
    or not its (nonexistent) category has ever been set. Same
    all-history-then-slice shape as monthly_trend()."""
    rows = conn.execute(
        '''SELECT substr(date, 1, 7) AS month, SUM(btc_quantity) AS btc
           FROM transactions
           WHERE activity_type = 'ROUNDUP_BUY' AND btc_quantity IS NOT NULL
           GROUP BY month
           ORDER BY month'''
    ).fetchall()
    trend = [{'month': r['month'], 'btcQuantity': round(r['btc'], 8)} for r in rows]
    return trend[-months:]


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
        'byMonthBySource': monthly_trend_by_source(conn),
        'topMerchants': top_merchants(conn, start, end, category=category),
    }


# --- Cash flow (income vs expense) ------------------------------------

def chequing_income_total(conn, start, end):
    row = conn.execute(
        f'''SELECT COALESCE(SUM(t.amount), 0) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE a.kind = 'chequing'
              AND t.activity_type IN ({_placeholders(CHEQUING_INCOME_TYPES)})
              AND t.date >= ? AND t.date <= ?
              AND e.transaction_id IS NULL''',
        (*CHEQUING_INCOME_TYPES, start, end),
    ).fetchone()
    return max(row['total'], 0.0)


def chequing_expense_total(conn, start, end):
    row = conn.execute(
        f'''SELECT COALESCE(SUM(-t.amount), 0) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE a.kind = 'chequing'
              AND t.activity_type IN ({_placeholders(CHEQUING_EXPENSE_TYPES)})
              AND t.date >= ? AND t.date <= ?
              AND e.transaction_id IS NULL''',
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
        f'''SELECT COALESCE({_CC_SPEND_CASE}, 0) AS total
            FROM transactions_effective t
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE {_CC_SPEND_FILTER} AND date >= ? AND date <= ? AND e.transaction_id IS NULL''',
        (start, end),
    ).fetchone()
    return max(row['total'], 0.0)


def cash_flow_by_month(conn, months=MONTHS_OF_TREND):
    income_rows = conn.execute(
        f'''SELECT substr(t.date, 1, 7) AS month, SUM(t.amount) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_INCOME_TYPES)})
              AND e.transaction_id IS NULL
            GROUP BY month''',
        CHEQUING_INCOME_TYPES,
    ).fetchall()
    income_by_month = {r['month']: r['total'] for r in income_rows}

    chequing_expense_rows = conn.execute(
        f'''SELECT substr(t.date, 1, 7) AS month, SUM(-t.amount) AS total
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_EXPENSE_TYPES)})
              AND e.transaction_id IS NULL
            GROUP BY month''',
        CHEQUING_EXPENSE_TYPES,
    ).fetchall()
    cc_expense_rows = conn.execute(
        f'''SELECT substr(date, 1, 7) AS month, {_CC_SPEND_CASE} AS total
            FROM transactions_effective t
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE {_CC_SPEND_FILTER} AND e.transaction_id IS NULL GROUP BY month'''
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


def cash_flow_month_transactions(conn, month, kind):
    """The individual transactions behind one month's income or expense bar
    on the Cash Flow chart (finance/ARCHITECTURE.md) - what clicking a bar
    shows. `month` is 'YYYY-MM'; `kind` is 'income' or 'expense' (anything
    else falls back to 'income'). `amount` in the response follows the
    same "positive = contributes to this total" convention the stat tiles
    use - for expense, a credit-card Refund row (which nets against
    spend) comes back negative, same as it does in every expense total
    elsewhere in this module.

    Every matching transaction is returned, including ones excluded from
    Cash Flow (csv_schema.sql's cash_flow_exclusions, ARCHITECTURE.md A5f) -
    each row carries `excluded`/`reason` rather than being filtered out, so
    the dialog can show the full picture with a per-row toggle. Callers that
    need a total should sum only the non-excluded rows (see server.py's
    /finance/cash-flow-transactions.json)."""
    if kind != 'expense':
        rows = conn.execute(
            f'''SELECT t.id AS id, t.date, t.description, t.amount, t.activity_type AS activity_type,
                       e.transaction_id IS NOT NULL AS excluded, e.reason AS reason
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
                WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_INCOME_TYPES)})
                  AND substr(t.date, 1, 7) = ?
                ORDER BY t.date DESC, t.id DESC''',
            (*CHEQUING_INCOME_TYPES, month),
        ).fetchall()
        return [_cash_flow_tx_row(r) for r in rows]

    chequing_rows = conn.execute(
        f'''SELECT t.id AS id, t.date, t.description, -t.amount AS amount,
                   e.transaction_id IS NOT NULL AS excluded, e.reason AS reason
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE a.kind = 'chequing' AND t.activity_type IN ({_placeholders(CHEQUING_EXPENSE_TYPES)})
              AND substr(t.date, 1, 7) = ?''',
        (*CHEQUING_EXPENSE_TYPES, month),
    ).fetchall()
    cc_rows = conn.execute(
        f'''SELECT t.id AS id, t.date, t.description, -t.amount AS amount,
                   e.transaction_id IS NOT NULL AS excluded, e.reason AS reason
            FROM transactions_effective t
            LEFT JOIN cash_flow_exclusions e ON e.transaction_id = t.id
            WHERE {_CC_SPEND_FILTER} AND substr(date, 1, 7) = ?''',
        (month,),
    ).fetchall()

    combined = [_cash_flow_tx_row(r) for r in chequing_rows] + [_cash_flow_tx_row(r) for r in cc_rows]
    combined.sort(key=lambda r: r['date'], reverse=True)
    return combined


def _cash_flow_tx_row(r):
    row = {
        'id': r['id'],
        'date': r['date'],
        'description': r['description'],
        'amount': round(r['amount'], 2),
        'excluded': bool(r['excluded']),
        'reason': r['reason'],
    }
    if 'activity_type' in r.keys():
        row['type'] = INCOME_TYPE_LABELS.get(r['activity_type'], r['activity_type'])
    return row


def cash_flow_income_by_type(transactions):
    """Aggregates an income month's transactions (as returned by
    cash_flow_month_transactions) into per-type totals - e.g. all "Cash
    back - Credit card" and "Interest received" rows collapse into single
    Cashback/Interest lines instead of listing every transaction
    individually. Only non-excluded rows count, same "what counts" rule
    as the dialog's overall total. Rows with no `type` (expense rows,
    which this is never called with) fall under 'Other'."""
    totals = {}
    counts = {}
    order = []
    for t in transactions:
        if t['excluded']:
            continue
        label = t.get('type') or 'Other'
        if label not in totals:
            totals[label] = 0.0
            counts[label] = 0
            order.append(label)
        totals[label] += t['amount']
        counts[label] += 1
    order.sort(key=lambda label: totals[label], reverse=True)
    return [{'type': label, 'total': round(totals[label], 2), 'count': counts[label]} for label in order]


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
