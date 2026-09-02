import base64
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import auth  # noqa: E402

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


def _b64url(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def _make_id_token(claims_override=None, segments=3):
    claims = {
        "aud": CLIENT_ID,
        "iss": "https://accounts.google.com",
        "exp": time.time() + 3600,
        "email_verified": True,
        "sub": "1234567890",
    }
    claims.update(claims_override or {})
    header = _b64url(json.dumps({"alg": "none"}).encode("utf-8"))
    payload = _b64url(json.dumps(claims).encode("utf-8"))
    parts = [header, payload, "sig"][:segments]
    return ".".join(parts)


class TestParseIdTokenClaims(unittest.TestCase):

    def test_valid_token_returns_claims(self):
        token = _make_id_token()
        claims = auth.parse_id_token_claims(token, CLIENT_ID)
        self.assertEqual(claims["sub"], "1234567890")

    def test_wrong_aud_rejected(self):
        token = _make_id_token({"aud": "someone-elses-client-id"})
        with self.assertRaises(ValueError):
            auth.parse_id_token_claims(token, CLIENT_ID)

    def test_wrong_iss_rejected(self):
        token = _make_id_token({"iss": "https://evil.example.com"})
        with self.assertRaises(ValueError):
            auth.parse_id_token_claims(token, CLIENT_ID)

    def test_expired_exp_rejected(self):
        token = _make_id_token({"exp": time.time() - 60})
        with self.assertRaises(ValueError):
            auth.parse_id_token_claims(token, CLIENT_ID)

    def test_unverified_email_rejected(self):
        token = _make_id_token({"email_verified": False})
        with self.assertRaises(ValueError):
            auth.parse_id_token_claims(token, CLIENT_ID)

    def test_non_three_segment_token_rejected(self):
        token = _make_id_token(segments=2)
        with self.assertRaises(ValueError):
            auth.parse_id_token_claims(token, CLIENT_ID)


if __name__ == "__main__":
    unittest.main()
