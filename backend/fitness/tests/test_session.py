import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Set before importing session so get_secret() never touches the real
# data/fitness/session_secret file on disk.
os.environ.setdefault("FITNESS_SESSION_SECRET", "test-secret-do-not-use-in-prod")

import session  # noqa: E402


class TestSignVerify(unittest.TestCase):

    def test_round_trips_the_payload(self):
        cookie = session.sign({"user_id": "abc123", "exp": time.time() + 60})
        payload = session.verify(cookie)
        self.assertEqual(payload["user_id"], "abc123")

    def test_flipped_signature_character_fails(self):
        cookie = session.sign({"user_id": "abc123", "exp": time.time() + 60})
        encoded, signature = cookie.split(".", 1)
        flipped = "a" if signature[0] != "a" else "b"
        tampered = f"{encoded}.{flipped}{signature[1:]}"
        self.assertIsNone(session.verify(tampered))

    def test_flipped_payload_character_fails(self):
        cookie = session.sign({"user_id": "abc123", "exp": time.time() + 60})
        encoded, signature = cookie.split(".", 1)
        flipped = "a" if encoded[0] != "a" else "b"
        tampered = f"{flipped}{encoded[1:]}.{signature}"
        self.assertIsNone(session.verify(tampered))

    def test_expired_exp_fails(self):
        cookie = session.sign({"user_id": "abc123", "exp": time.time() - 1})
        self.assertIsNone(session.verify(cookie))

    def test_garbage_input_returns_none(self):
        self.assertIsNone(session.verify("not-a-real-cookie"))
        self.assertIsNone(session.verify(""))
        self.assertIsNone(session.verify("no-dot-here"))
        self.assertIsNone(session.verify("..."))

    def test_b64url_decode_handles_no_padding(self):
        for raw in (b"a", b"ab", b"abc", b"abcd", b"hello world"):
            encoded = session.b64url_encode(raw)
            self.assertNotIn("=", encoded)
            self.assertEqual(session.b64url_decode(encoded), raw)


if __name__ == "__main__":
    unittest.main()
