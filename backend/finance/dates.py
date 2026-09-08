"""Canonical date/timestamp formats for data/finance/finance.db (see
csv_schema.sql's classification comment for which columns are which and
why). Two formats, both ISO-8601, both used everywhere they mean what
their name says:

    ISO_DATE      'YYYY-MM-DD'          - a calendar date, no time-of-day,
                                           no timezone (a transaction, an
                                           as-of balance, an account
                                           closure all happen "on a day,"
                                           not at an instant)
    ISO_TIMESTAMP 'YYYY-MM-DDTHH:MM:SSZ' - an instant, always UTC (the
                                           trailing 'Z' is that promise,
                                           not decoration) - when
                                           something was imported,
                                           recorded, or last updated

now_iso()/today_iso() below are the single place that formats "right
now" into either shape - before this module existed, five call sites
across import_csv.py, import_shakepay.py, networth.py, and
categorize_shakepay.py each formatted `datetime.now(timezone.utc))` by
hand, which meant a future format change (or a copy-paste slip) had five
places to get consistently right instead of one.

is_iso_date()/is_iso_timestamp() check the *shape* only (via GLOB - see
csv_schema.sql's CHECK constraints, which use the identical patterns) -
they will happily accept '2026-02-30', which does not exist on any
calendar. That's deliberate: catching a value that isn't even
shaped like a date (wrong format, empty, a stray timestamp where a
date belongs) is cheap and prevents real bugs like a corrupted
range-replace window; rejecting every invalid calendar date needs a
real calendar library and buys little for a personal finance ledger
where the data enters through a handful of trusted import paths.
"""

import re
from datetime import datetime, timezone

_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_ISO_TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


def now_iso():
    """The current instant, as an ISO_TIMESTAMP string."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def today_iso():
    """Today's date (UTC), as an ISO_DATE string."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def is_iso_date(value):
    """Whether `value` is shaped like an ISO_DATE string - see the module
    docstring for exactly what this does and doesn't catch."""
    return isinstance(value, str) and bool(_ISO_DATE_RE.match(value))


def is_iso_timestamp(value):
    """Whether `value` is shaped like an ISO_TIMESTAMP string."""
    return isinstance(value, str) and bool(_ISO_TIMESTAMP_RE.match(value))
