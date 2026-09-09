import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api  # noqa: E402


def rollup(date, value, payload_key="caloriesBurned", value_key="kilocaloriesSum"):
    year, month, day = (int(part) for part in date.split("-"))
    return {
        "civilStartTime": {"date": {"year": year, "month": month, "day": day}},
        payload_key: {value_key: value},
    }


class TestReshapeCalories(unittest.TestCase):
    def test_reads_and_sums_daily_rollups(self):
        records = api._reshape_calories([
            rollup("2026-09-09", 2100),
            rollup("2026-09-09", "125.5", "calories", "caloriesKcalSum"),
        ])
        self.assertEqual(records, [{"date": "2026-09-09", "value": 2225.5}])

    def test_ignores_malformed_points(self):
        self.assertEqual(api._reshape_calories([{}, {"caloriesBurned": None}]), [])


if __name__ == "__main__":
    unittest.main()
