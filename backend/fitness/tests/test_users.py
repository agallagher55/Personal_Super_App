import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import users  # noqa: E402


class TestUserIdForSub(unittest.TestCase):

    def test_deterministic_and_16_hex_chars(self):
        first = users.user_id_for_sub("1234567890")
        second = users.user_id_for_sub("1234567890")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        int(first, 16)  # raises ValueError if not hex

    def test_different_subs_differ(self):
        self.assertNotEqual(users.user_id_for_sub("a"), users.user_id_for_sub("b"))


class TestIsAllowed(unittest.TestCase):

    def setUp(self):
        self._env_backup = {
            k: os.environ.get(k) for k in ("FITNESS_ALLOWED_EMAILS", "FITNESS_OWNER_EMAIL")
        }
        for k in self._env_backup:
            os.environ.pop(k, None)
        self._allowed_path_backup = users.ALLOWED_USERS_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        users.ALLOWED_USERS_PATH = Path(self._tmpdir.name) / "allowed_users.json"

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        users.ALLOWED_USERS_PATH = self._allowed_path_backup
        self._tmpdir.cleanup()

    def test_nothing_configured_returns_false(self):
        self.assertFalse(users.is_allowed("anyone@example.com"))

    def test_owner_email_alone_is_case_insensitive_and_trims(self):
        os.environ["FITNESS_OWNER_EMAIL"] = "Owner@Example.com"
        self.assertTrue(users.is_allowed("  owner@example.com  "))
        self.assertTrue(users.is_allowed("OWNER@EXAMPLE.COM"))
        self.assertFalse(users.is_allowed("someone-else@example.com"))

    def test_allowed_emails_env_var_case_insensitive(self):
        os.environ["FITNESS_ALLOWED_EMAILS"] = "a@example.com, B@Example.com"
        self.assertTrue(users.is_allowed("a@example.com"))
        self.assertTrue(users.is_allowed("b@example.com"))
        self.assertFalse(users.is_allowed("c@example.com"))

    def test_empty_email_is_false(self):
        os.environ["FITNESS_OWNER_EMAIL"] = "owner@example.com"
        self.assertFalse(users.is_allowed(""))
        self.assertFalse(users.is_allowed(None))


class TestUpsertFromClaims(unittest.TestCase):

    def setUp(self):
        self._users_root_backup = users.USERS_ROOT
        self._tmpdir = tempfile.TemporaryDirectory()
        users.USERS_ROOT = Path(self._tmpdir.name) / "users"

    def tearDown(self):
        users.USERS_ROOT = self._users_root_backup
        self._tmpdir.cleanup()

    def test_keeps_refresh_token_when_response_omits_one(self):
        claims = {"sub": "sub-1", "email": "a@example.com", "name": "A"}
        user_id = users.upsert_from_claims(claims, {"access_token": "tok1", "refresh_token": "refresh-1"})

        second_response = {"access_token": "tok2"}  # no refresh_token, as Google omits on re-consent skip
        users.upsert_from_claims(claims, second_response)

        tokens = users.load_tokens(user_id)
        self.assertEqual(tokens["access_token"], "tok2")
        self.assertEqual(tokens["refresh_token"], "refresh-1")

    def test_keeps_original_created_timestamp(self):
        claims = {"sub": "sub-2", "email": "b@example.com", "name": "B"}
        user_id = users.upsert_from_claims(claims, {"access_token": "tok1", "refresh_token": "r1"})
        first_created = users.load_user(user_id)["created"]

        users.upsert_from_claims(claims, {"access_token": "tok2", "refresh_token": "r2"})
        second_created = users.load_user(user_id)["created"]

        self.assertEqual(first_created, second_created)


if __name__ == "__main__":
    unittest.main()
