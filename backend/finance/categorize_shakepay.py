"""One-time bulk categorization for Shakepay card purchases (see
finance/README.md's "Shakepay: PDF import" section). New purchases land
with category=None ("Uncategorized" in the dashboard) same as any
issuer-blank credit card row, which means clicking through the
dashboard's pencil-edit dialog once per merchant to get them showing up
in Spending - tedious once there are a few dozen distinct merchants
across several months' statements.

This sets the same "permanent" merchant_category_override
(db.set_merchant_category_override) that pencil-edit dialog writes
through, for every shakepay-card merchant description that matches a
keyword pattern below - no dashboard changes, no new mechanism, just
applying the existing one in bulk.

Deliberately keyword/pattern-based, not a fixed list of exact merchant
strings: new merchants show up every month, and matching on a keyword
("MCDONALD", "PARKING", "ATHLETICS", ...) generalizes to merchants this
script has never seen, unlike hardcoding August's own merchant list.
Category names mostly follow the taxonomy the existing credit card
export already uses (Coffee, Restaurants, Groceries, "Gas, parking, and
tolls", Health & pharmacy, Other shopping, Fitness) so Shakepay spend
merges into the same Spending categories instead of fragmenting into
new ones; Transportation and Bills & utilities are added here since
nothing in the credit card sample covered rideshare/transit or
third-party utility bill-pay merchants - see CATEGORY_RULES below to
extend or rename any of them.

Only sets an override where one doesn't already exist for that exact
description - never silently overwrites a category you already assigned
by hand via the dashboard. Prints what it categorized, what it left
alone, and - the useful part - which merchants matched nothing, so you
know exactly what's worth a pattern (or a one-off pencil-edit) next.

Usage:
    python3 backend/finance/categorize_shakepay.py            # apply
    python3 backend/finance/categorize_shakepay.py --dry-run  # preview only
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dates  # noqa: E402
import db as finance_db  # noqa: E402

# Ordered (pattern, category) - first match wins, case-insensitive
# substring/regex search against the merchant description. Extend this
# list as new merchants show up in an "unmatched" report rather than
# hardcoding one-off exact-string cases.
CATEGORY_RULES = [
    # Coffee / bakery / cafe. ESPRESS(O)/PIZZ(A) rather than the full
    # word below - merchant descriptions get truncated at a fixed width
    # (observed: ~25 chars, e.g. "SQ *WEIRD HARBOUR ESPRESS", "TONY'S
    # DONAIR AND PIZZ"), and the shorter form still matches the
    # untruncated word too since it's a substring of it either way.
    (r'TIM HORTONS', 'Coffee'),
    (r'STARBUCKS', 'Coffee'),
    (r'ESPRESS', 'Coffee'),
    (r'CAPPUC', 'Coffee'),
    (r'BAKERY', 'Coffee'),
    (r'\bCAFE\b', 'Coffee'),
    (r'COFFEE', 'Coffee'),
    (r'DINEEN', 'Coffee'),  # Dineen Coffee Co.
    (r'EAST CUP', 'Coffee'),
    # Restaurants / fast food / food vendors / bars & pubs (folded into
    # Restaurants rather than a separate "Alcohol & bars" category - a
    # pub/tavern/brewery match here is "eating and drinking out" same as
    # a restaurant, and splitting it risks bar-type merchants landing in
    # different categories depending on which rule happened to exist
    # when they were first seen).
    (r'MCDONALD', 'Restaurants'),
    (r'\bDQ\b|DAIRY QUEEN|GRILL', 'Restaurants'),
    (r'PIZZ', 'Restaurants'),
    (r'SUBWAY', 'Restaurants'),
    (r'WENDY', 'Restaurants'),
    (r'BURGER', 'Restaurants'),
    (r'\bTACO\b', 'Restaurants'),
    (r'SUSHI', 'Restaurants'),
    (r'KITCHEN', 'Restaurants'),
    (r'DONAIR', 'Restaurants'),
    (r'RAMBLERS', 'Restaurants'),
    (r'DOGS ON WHEELS', 'Restaurants'),
    (r'MAMA GRATTIS', 'Restaurants'),
    (r'SBARRO', 'Restaurants'),
    (r'MONTANA', 'Restaurants'),
    (r"PJ O'?BRIEN", 'Restaurants'),
    (r'OSPREY', 'Restaurants'),
    (r'CRAFT ADELAIDE', 'Restaurants'),
    (r'GOOD ROBOT', 'Restaurants'),
    (r'SKETTI', 'Restaurants'),
    (r'DINER|RESTAURANT|TAVERN|\bLOUNGE\b|BREW(ING|ERY)?|\bBAR\b|\bPUB\b', 'Restaurants'),
    # Groceries
    (r'SOBEYS', 'Groceries'),
    (r'SUPERSTORE|LOBLAWS|FRESHCO|NO FRILLS|\bMETRO\b|SAVE.ON.FOODS', 'Groceries'),
    (r'FOOD MART', 'Groceries'),
    # Health & pharmacy
    (r'LAWTONS', 'Health & pharmacy'),
    (r'SHOPPERS DRUG MART', 'Health & pharmacy'),
    # Retail
    (r'DOLLARAMA', 'Other shopping'),
    (r'CANADIAN TIRE', 'Other shopping'),
    (r'CHAPTERS|INDIGO', 'Other shopping'),
    (r'MOUNTAIN EQUIPMENT', 'Other shopping'),
    (r'\bNSLC\b', 'Other shopping'),  # Nova Scotia Liquor Corporation
    # Fitness
    (r'ATHLETICS|RECREATION|\bGYM\b|FITNESS', 'Fitness'),
    # Gas, parking, and tolls
    (r'PARKING', 'Gas, parking, and tolls'),
    (r'AIR-SERV', 'Gas, parking, and tolls'),
    (r'\bESSO\b|PETRO|\bSHELL\b|\bIRVING\b', 'Gas, parking, and tolls'),
    # Transportation (rideshare/transit/micromobility)
    (r'\bUBER\b', 'Transportation'),
    (r'MASABI', 'Transportation'),  # transit-agency mobile ticketing app
    (r'METROLINX|GO TRANSIT', 'Transportation'),
    (r'BIRD\*|BIRD\.CO', 'Transportation'),  # e-scooter rental
    # Bills & utilities
    (r'KUBRA', 'Bills & utilities'),  # third-party utility bill-pay processor
    (r'NOVA SCOTIA PWR', 'Bills & utilities'),
    (r'EZ-PAY', 'Bills & utilities'),
    # Fallback: Toast (restaurant/bar point-of-sale) always prefixes its
    # own merchant descriptions with "TST-", so anything starting with it
    # is a restaurant/bar regardless of what follows - placed last so a
    # more specific match above (e.g. a coffee shop that happens to also
    # run on Toast) still wins first.
    (r'^TST-', 'Restaurants'),
]
_COMPILED_RULES = [(re.compile(pattern, re.IGNORECASE), category) for pattern, category in CATEGORY_RULES]


def guess_category(description):
    for pattern, category in _COMPILED_RULES:
        if pattern.search(description):
            return category
    return None


def categorize(conn, dry_run=False):
    rows = conn.execute(
        "SELECT DISTINCT description FROM transactions "
        "WHERE account_id = 'shakepay-card' AND activity_type = 'Purchase'"
    ).fetchall()
    already_set = {
        r['description'] for r in conn.execute('SELECT description FROM merchant_category_overrides').fetchall()
    }

    categorized, unmatched, skipped = [], [], []
    now = dates.now_iso()
    with conn:
        for row in rows:
            description = row['description']
            if description in already_set:
                skipped.append(description)
                continue
            category = guess_category(description)
            if category is None:
                unmatched.append(description)
                continue
            categorized.append((description, category))
            if not dry_run:
                finance_db.set_merchant_category_override(conn, description, category, now)
    return categorized, unmatched, skipped


def main():
    dry_run = '--dry-run' in sys.argv
    conn = finance_db.connect()
    try:
        finance_db.init_schema(conn)
        categorized, unmatched, skipped = categorize(conn, dry_run=dry_run)
    finally:
        conn.close()

    prefix = '[dry-run] ' if dry_run else ''
    for description, category in sorted(categorized):
        print(f'{prefix}{description!r} -> {category}')

    if skipped:
        print(f'\n{len(skipped)} merchant(s) already categorized, left untouched:')
        for description in sorted(skipped):
            print(f'  {description}')

    if unmatched:
        print(f'\n{len(unmatched)} merchant(s) matched no pattern - categorize by hand '
              f'via the dashboard, or add a pattern to CATEGORY_RULES and re-run:')
        for description in sorted(unmatched):
            print(f'  {description}')

    print(f'\n{len(categorized)} merchant(s) categorized' + (' (dry run, nothing written).' if dry_run else '.'))


if __name__ == '__main__':
    main()
