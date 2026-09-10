import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import store  # noqa: E402


class TestStoreCache(unittest.TestCase):
    def setUp(self):
        store._cache.clear()

    def tearDown(self):
        store._cache.clear()

    def test_save_store_publishes_saved_data_to_read_cache(self):
        path = Mock()
        path.stat.return_value = SimpleNamespace(st_mtime_ns=123, st_size=456)
        data = {"metrics": {"calories": [{"totalCalories": {"kcalSum": 2100}}]}}

        with (
            patch.object(store, "data_path", return_value=path),
            patch.object(store, "write_json_atomic") as write_json_atomic,
        ):
            store.save_store("user-1", data)

        write_json_atomic.assert_called_once_with(path, data)
        self.assertEqual(store._cache["user-1"], ((123, 456), data))


if __name__ == "__main__":
    unittest.main()
