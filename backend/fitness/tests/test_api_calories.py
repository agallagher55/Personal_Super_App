import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api  # noqa: E402


def rollup(date, value):
    year, month, day = (int(part) for part in date.split("-"))
    return {
        "civilStartTime": {"date": {"year": year, "month": month, "day": day}},
        "totalCalories": {"kcalSum": value},
    }


class TestReshapeCalories(unittest.TestCase):
    def test_reads_and_sums_daily_rollups(self):
        records = api._reshape_calories([
            rollup("2026-09-09", 2100),
            rollup("2026-09-09", "125.5"),
        ])
        self.assertEqual(records, [{"date": "2026-09-09", "value": 2225.5}])

    def test_ignores_malformed_points(self):
        self.assertEqual(api._reshape_calories([{}, {"totalCalories": None}]), [])


if __name__ == "__main__":
    unittest.main()
