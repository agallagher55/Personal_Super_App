import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api  # noqa: E402


def sleep_point(date, minutes):
    return {
        "sleep": {
            "interval": {"endTime": f"{date}T12:00:00Z", "endUtcOffset": "+00:00"},
            "summary": {"minutesAsleep": minutes, "stagesSummary": []},
        }
    }


class TestReshapeSleep(unittest.TestCase):
    def test_filters_short_nap_sessions(self):
        records = api._reshape_sleep([
            sleep_point("2026-09-08", 72),
            sleep_point("2026-09-09", 441),
        ])

        self.assertEqual(records, [{
            "date": "2026-09-09",
            "duration_minutes": 441,
            "stages": {"light": 0, "deep": 0, "rem": 0, "awake": 0},
        }])

    def test_keeps_only_longest_main_session_per_date(self):
        records = api._reshape_sleep([
            sleep_point("2026-09-09", 360),
            sleep_point("2026-09-09", 420),
        ])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["duration_minutes"], 420)


if __name__ == "__main__":
    unittest.main()
