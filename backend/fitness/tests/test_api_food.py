import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api  # noqa: E402


class TestReshapeFood(unittest.TestCase):
    def test_sums_meals_by_day(self):
        points = [
            {"nutrition": {"interval": {"civilStartTime": "2026-09-09T08:00:00"}, "nutrients": {
                "caloriesKcal": 450, "totalCarbohydrateGrams": 52, "proteinGrams": 25, "totalFatGrams": 14,
            }}},
            {"nutrition": {"interval": {"civilStartTime": "2026-09-09T12:00:00"}, "nutrients": {
                "energyKilocalories": {"value": "625.5"}, "carbohydrateGrams": 71,
                "protein": {"grams": 31}, "fatGrams": 22,
            }}},
        ]

        self.assertEqual(api._reshape_food(points), [{
            "date": "2026-09-09", "calories": 1075.5, "carbs_grams": 123,
            "protein_grams": 56, "fat_grams": 36,
        }])

    def test_ignores_malformed_points(self):
        self.assertEqual(api._reshape_food([{}, {"nutrition": None}]), [])


if __name__ == "__main__":
    unittest.main()
