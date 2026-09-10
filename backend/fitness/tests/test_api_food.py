import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api  # noqa: E402


def civil_time(hour):
    return {
        "date": {"year": 2026, "month": 9, "day": 9},
        "time": {"hours": hour},
    }


def nutrition_log(hour, calories, carbs, protein, fat):
    return {"nutritionLog": {
        "interval": {"civilStartTime": civil_time(hour)},
        "energy": {"kcal": calories},
        "totalCarbohydrate": {"grams": carbs},
        "totalFat": {"grams": fat},
        "nutrients": [
            {"nutrient": "PROTEIN", "quantity": {"grams": protein}},
            {"nutrient": "SODIUM", "quantity": {"grams": 0.5}},
        ],
    }}


class TestReshapeFood(unittest.TestCase):
    def test_sums_meals_by_day(self):
        points = [
            nutrition_log(8, 450, 52, 25, 14),
            nutrition_log(12, "625.5", 71, 31, 22),
        ]

        self.assertEqual(api._reshape_food(points), [{
            "date": "2026-09-09", "calories": 1075.5, "carbs_grams": 123,
            "protein_grams": 56, "fat_grams": 36,
        }])

    def test_ignores_malformed_points(self):
        self.assertEqual(api._reshape_food([{}, {"nutritionLog": None}]), [])


if __name__ == "__main__":
    unittest.main()
