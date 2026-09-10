import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import google_health_client  # noqa: E402


class TestGoogleHealthClient(unittest.TestCase):
    @patch.object(google_health_client.http_client, "post_json")
    def test_total_calories_uses_supported_endpoint_and_14_day_chunks(self, post_json):
        post_json.return_value = {"rollupDataPoints": []}

        google_health_client.list_data_points(
            "calories", "2026-08-11", "2026-09-10", "access-token"
        )

        self.assertEqual(post_json.call_count, 3)
        expected_ranges = [
            ("2026-08-11", "2026-08-25"),
            ("2026-08-25", "2026-09-08"),
            ("2026-09-08", "2026-09-11"),
        ]
        for call, (start, end) in zip(post_json.call_args_list, expected_ranges):
            self.assertEqual(
                call.args[0],
                "https://health.googleapis.com/v4/users/me/dataTypes/total-calories/dataPoints:dailyRollUp",
            )
            self.assertEqual(call.args[1]["range"], {
                "start": google_health_client._civil_date(start),
                "end": google_health_client._civil_date(end),
            })

    @patch.object(google_health_client.http_client, "get_json")
    def test_food_uses_nutrition_log_endpoint_and_filter(self, get_json):
        get_json.return_value = {"dataPoints": []}

        google_health_client.list_data_points(
            "food", "2026-09-01", "2026-09-10", "access-token"
        )

        call = get_json.call_args
        self.assertEqual(
            call.args[0],
            "https://health.googleapis.com/v4/users/me/dataTypes/nutrition-log/dataPoints",
        )
        self.assertEqual(
            call.kwargs["params"]["filter"],
            'nutrition_log.interval.civil_start_time >= "2026-09-01T00:00:00" '
            'AND nutrition_log.interval.civil_start_time < "2026-09-11T00:00:00"',
        )


if __name__ == "__main__":
    unittest.main()
