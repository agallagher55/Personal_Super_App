import os
import sys
import tempfile
import threading
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


class TestGetSecret(unittest.TestCase):
    """get_secret()'s generate-and-persist path, which only runs when
    FITNESS_SESSION_SECRET is unset and no secret file exists yet. Each
    test points SECRET_PATH at a temp dir so the real
    data/fitness/session_secret is never read or written.
    """

    def setUp(self):
        self.env_secret = os.environ.pop("FITNESS_SESSION_SECRET", None)
        self.real_path = session.SECRET_PATH
        self.tmp_dir = tempfile.TemporaryDirectory()
        session.SECRET_PATH = Path(self.tmp_dir.name) / "session_secret"
        session._secret_cache = None

    def tearDown(self):
        session.SECRET_PATH = self.real_path
        session._secret_cache = None
        self.tmp_dir.cleanup()

        if self.env_secret is not None:
            os.environ["FITNESS_SESSION_SECRET"] = self.env_secret

    def test_generates_persists_and_reuses_one_secret(self):
        secret = session.get_secret()
        self.assertTrue(secret)
        self.assertEqual(session.SECRET_PATH.read_bytes(), secret)

        # A later cold start adopts the file rather than generating again,
        # otherwise every restart would log every visitor out.
        session._secret_cache = None
        self.assertEqual(session.get_secret(), secret)

    def test_concurrent_cold_start_agrees_on_one_secret(self):
        """Sixteen threads racing the first call must all get the same
        secret and none may raise. Before the lock + atomic publish, the
        losers of the os.open(O_EXCL) race died on FileExistsError, which
        nothing catches, so those requests 500'd."""
        seen = []
        errors = []
        barrier = threading.Barrier(16)

        def worker():
            barrier.wait()

            try:
                seen.append(session.get_secret())
            except Exception as exc:  # noqa: BLE001 - the point of the test
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(16)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(set(seen)), 1)
        self.assertEqual(session.SECRET_PATH.read_bytes(), seen[0])

    def test_adopts_the_winners_secret_when_it_loses_the_publish_race(self):
        """Another process published between our read and our link: its
        secret is the one already signing live cookies, so adopt it."""
        winner = b"the-other-process-secret"
        real_link = os.link

        def losing_link(source, destination):
            Path(destination).write_bytes(winner)
            real_link(source, destination)

        os.link = losing_link

        try:
            self.assertEqual(session.get_secret(), winner)
        finally:
            os.link = real_link

    def test_falls_back_when_hard_links_are_unsupported(self):
        real_link = os.link

        def unsupported_link(source, destination):
            raise OSError("hard links not supported here")

        os.link = unsupported_link

        try:
            secret = session.get_secret()
        finally:
            os.link = real_link

        self.assertTrue(secret)
        self.assertEqual(session.SECRET_PATH.read_bytes(), secret)

    def test_leaves_no_temp_file_behind(self):
        session.get_secret()
        leftovers = [p.name for p in Path(self.tmp_dir.name).iterdir() if p.name != "session_secret"]
        self.assertEqual(leftovers, [])

    def test_env_var_wins_over_the_file(self):
        session.get_secret()
        session._secret_cache = None
        os.environ["FITNESS_SESSION_SECRET"] = "from-the-environment"

        try:
            self.assertEqual(session.get_secret(), b"from-the-environment")
        finally:
            os.environ.pop("FITNESS_SESSION_SECRET", None)


if __name__ == "__main__":
    unittest.main()
