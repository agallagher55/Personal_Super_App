"""Issue: canonical date/timestamp validation. Covers dates.py - the
single place that formats "now" into either canonical shape, and the
shape-only validators used by db.replace_transactions_in_range and the
transactions.date/imported_at CHECK constraints.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dates  # noqa: E402


class TestNowIso(unittest.TestCase):

    def test_matches_the_iso_timestamp_shape(self):
        self.assertTrue(dates.is_iso_timestamp(dates.now_iso()))

    def test_matches_the_literal_pattern(self):
        self.assertRegex(dates.now_iso(), r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


class TestTodayIso(unittest.TestCase):

    def test_matches_the_iso_date_shape(self):
        self.assertTrue(dates.is_iso_date(dates.today_iso()))

    def test_matches_the_literal_pattern(self):
        self.assertRegex(dates.today_iso(), r'^\d{4}-\d{2}-\d{2}$')


class TestIsIsoDate(unittest.TestCase):

    def test_accepts_a_well_formed_date(self):
        self.assertTrue(dates.is_iso_date('2026-09-08'))

    def test_rejects_a_slash_separated_date(self):
        self.assertFalse(dates.is_iso_date('09/08/2026'))

    def test_rejects_a_missing_leading_zero(self):
        self.assertFalse(dates.is_iso_date('2026-9-8'))

    def test_rejects_a_timestamp(self):
        self.assertFalse(dates.is_iso_date('2026-09-08T00:00:00Z'))

    def test_rejects_an_empty_string(self):
        self.assertFalse(dates.is_iso_date(''))

    def test_rejects_none(self):
        self.assertFalse(dates.is_iso_date(None))

    def test_does_not_reject_an_impossible_calendar_date(self):
        """Documented, deliberate: shape-only, not a real calendar check -
        see the module docstring."""
        self.assertTrue(dates.is_iso_date('2026-02-30'))


class TestIsIsoTimestamp(unittest.TestCase):

    def test_accepts_a_well_formed_timestamp(self):
        self.assertTrue(dates.is_iso_timestamp('2026-09-08T00:00:00Z'))

    def test_rejects_a_space_separated_timestamp(self):
        self.assertFalse(dates.is_iso_timestamp('2026-09-08 00:00:00Z'))

    def test_rejects_a_missing_utc_marker(self):
        self.assertFalse(dates.is_iso_timestamp('2026-09-08T00:00:00'))

    def test_rejects_a_lowercase_utc_marker(self):
        self.assertFalse(dates.is_iso_timestamp('2026-09-08T00:00:00z'))

    def test_rejects_a_bare_date(self):
        self.assertFalse(dates.is_iso_timestamp('2026-09-08'))

    def test_rejects_none(self):
        self.assertFalse(dates.is_iso_timestamp(None))


if __name__ == '__main__':
    unittest.main()
