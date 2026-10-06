"""Public auth quotas. Optional PostgreSQL checks use QA_AUTH_RATE_DB=1 only."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from flask import Flask
import auth


class AuthRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.conn = MagicMock()
        self.cur = self.conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.cur.fetchone.return_value = (1, 600)
        self.service = auth.AuthService(self.app, lambda: self.conn)
        self.env = patch.dict(os.environ, USER_MFA_KEY_FILE="synthetic-unused-key", AUTH_TRUSTED_PROXY_IPS="")
        self.key = patch("auth.Path.read_bytes", return_value=b"synthetic quota key")
        self.env.start()
        self.key.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.key.stop)

    def quota_key(self, operation="login", address="127.0.0.1", **headers):
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": address}, headers=headers):
            self.service._public_auth_quota(operation)
        return self.cur.execute.call_args.args[1][0]

    def test_transport_peer_only_and_separate_endpoint_buckets(self):
        key = self.quota_key()
        self.assertEqual(key, self.quota_key(**{"X-Forwarded-For": "203.0.113.9", "Forwarded": "for=203.0.113.9"}))
        self.assertNotEqual(key, self.quota_key(address="127.0.0.2"))
        self.assertNotEqual(key, self.quota_key(operation="activation"))
        self.assertNotEqual(key, self.quota_key(operation="recovery_complete"))
        self.assertEqual(len(key), 32)
        self.assertNotIn(b"127.0.0.1", key)

    def test_boundary_and_retry_after_commit_even_when_denied(self):
        with self.app.test_request_context("/"):
            self.cur.fetchone.return_value = (auth.AUTH_RATE_LIMITS["login"], 87)
            self.assertIsNone(self.service._public_auth_quota("login"))
            self.cur.fetchone.return_value = (auth.AUTH_RATE_LIMITS["login"] + 1, 87)
            result = self.service._public_auth_quota("login")
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.headers["Retry-After"], "87")
        self.assertEqual(self.conn.__exit__.call_count, 2)
        self.assertEqual(self.conn.__exit__.call_args.args, (None, None, None))

    def test_trusted_proxy_uses_single_client_ip_and_ignores_untrusted_spoof(self):
        self.app.config["AUTH_TRUSTED_PROXY_IPS"] = "127.0.0.1,192.0.2.10"
        first = self.quota_key(**{"X-Forwarded-For": "203.0.113.1"})
        second = self.quota_key(**{"X-Forwarded-For": "203.0.113.2"})
        self.assertNotEqual(first, second)
        direct = self.quota_key(address="192.0.2.11")
        self.assertEqual(direct, self.quota_key(address="192.0.2.11", **{"X-Forwarded-For": "203.0.113.1"}))

    def test_trusted_proxy_malformed_or_multiple_xff_falls_back_to_peer(self):
        self.app.config["AUTH_TRUSTED_PROXY_IPS"] = ["127.0.0.1"]
        peer = self.quota_key()
        for value in ("", "invalid", "203.0.113.1, 203.0.113.2", "203.0.113.1:80", "203.0.113.0/24"):
            with self.subTest(value=value):
                self.assertEqual(peer, self.quota_key(**{"X-Forwarded-For": value}))
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers=[("X-Forwarded-For", "203.0.113.1"), ("X-Forwarded-For", "203.0.113.2")]):
            self.assertEqual(self.service._quota_client_address(), "127.0.0.1")
        self.cur.fetchone.return_value = (31, 600)
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"X-Forwarded-For": "invalid"}):
            self.assertEqual(self.service._public_auth_quota("login").status_code, 429)

    def test_trust_requires_exact_ip_and_topology_change_uses_transport_bucket(self):
        self.app.config["AUTH_TRUSTED_PROXY_IPS"] = "127.0.0.0/8,invalid,127.0.0.1"
        peer = self.quota_key(address="127.0.0.2")
        self.assertEqual(peer, self.quota_key(address="127.0.0.2", **{"X-Forwarded-For": "203.0.113.1"}))

    def test_key_or_database_unavailable_fails_closed_without_sensitive_details(self):
        for failure in ("key", "empty_key", "database", "commit"):
            with self.subTest(failure=failure):
                self.key.stop()
                self.conn.__exit__.side_effect = RuntimeError("private database failure") if failure == "commit" else None
                service = auth.AuthService(self.app, MagicMock(side_effect=RuntimeError("private database failure")) if failure == "database" else lambda: self.conn, audit_callback=MagicMock(side_effect=RuntimeError("audit unavailable")))
                with self.app.test_request_context("/", method="POST", json={"login": "synthetic", "password": "private-password"}), patch("auth.Path.read_bytes", side_effect=OSError("private key filename") if failure == "key" else None, return_value=b"" if failure == "empty_key" else b"synthetic key"), patch("auth.verify_password") as verify, patch("auth.PASSWORD_HASHER") as hashing:
                    result = service.login()
                self.assertEqual(result.status_code, 503)
                self.assertNotIn("private", result.get_data(as_text=True))
                verify.assert_not_called()
                hashing.hash.assert_not_called()
                service.audit_callback.assert_not_called()
                self.key.start()

    def test_rejected_requests_never_hash_verify_or_lookup_users(self):
        for method, operation in (("login", "login"), ("activate", "activation"), ("complete_recovery", "recovery_complete")):
            with self.subTest(method=method):
                self.cur.reset_mock()
                self.cur.fetchone.return_value = (auth.AUTH_RATE_LIMITS[operation] + 1, 600)
                with self.app.test_request_context("/", method="POST", json={"login": "synthetic", "password": "Synthetic-password!9A", "token": "synthetic-token"}), patch("auth.verify_password") as verify, patch("auth.PASSWORD_HASHER") as hashing:
                    result = getattr(self.service, method)()
                self.assertEqual(result.status_code, 429)
                verify.assert_not_called()
                hashing.hash.assert_not_called()
                self.assertEqual(self.cur.execute.call_count, 1)
                self.assertNotIn("synthetic-token", str(self.cur.execute.call_args))
                self.assertNotIn("Synthetic-password", str(self.cur.execute.call_args))

    def test_quota_transaction_finishes_before_argon2(self):
        quota_conn, login_conn = MagicMock(), MagicMock()
        quota_cur = quota_conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        quota_cur.fetchone.return_value = (1, 600)
        login_cur = login_conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        login_cur.fetchone.return_value = None
        service = auth.AuthService(self.app, MagicMock(side_effect=[quota_conn, login_conn]))
        def verify(*args):
            quota_conn.__exit__.assert_called_once_with(None, None, None)
            return False
        with self.app.test_request_context("/", method="POST", json={"login": "synthetic", "password": "wrong"}), patch("auth._dummy_hash", return_value="synthetic hash"), patch("auth.verify_password", side_effect=verify):
            _, status = service.login()
        self.assertEqual(status, 401)


@unittest.skipUnless(os.environ.get("QA_AUTH_RATE_DB") == "1", "isolated PostgreSQL opt-in")
class AuthRateLimitPostgresTests(unittest.TestCase):
    def test_persists_between_services_and_resets_expired_window(self):
        if not os.environ.get("DB_NAME", "").startswith("sgc_owner_qa_"):
            self.fail("Refusing non-QA database")
        from server import connect
        app = Flask(__name__)
        first, second = auth.AuthService(app, connect), auth.AuthService(app, connect)
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            self.assertEqual(cur.fetchone()[0], os.environ["DB_NAME"])
        # A random synthetic transport address creates an isolated quota row.
        address = "synthetic-rate-" + os.urandom(12).hex()
        with patch("auth.Path.read_bytes", return_value=b"synthetic quota integration key"), app.test_request_context("/", environ_base={"REMOTE_ADDR": address}):
            key = auth.hmac.new(b"synthetic quota integration key", b"sgc:public-auth:v1:login:" + address.encode(), auth.hashlib.sha256).digest()
            try:
                for _ in range(auth.AUTH_RATE_LIMITS["login"]):
                    self.assertIsNone(first._public_auth_quota("login"))
                self.assertEqual(second._public_auth_quota("login").status_code, 429)
                with connect() as conn, conn.cursor() as cur:
                    cur.execute("SELECT hits FROM public_recovery_quotas WHERE key=%s", (key,))
                    self.assertEqual(cur.fetchone()[0], auth.AUTH_RATE_LIMITS["login"] + 1)
                    cur.execute("UPDATE public_recovery_quotas SET window_started_at=now()-interval '601 seconds' WHERE key=%s", (key,))
                self.assertIsNone(second._public_auth_quota("login"))
                with connect() as conn, conn.cursor() as cur:
                    cur.execute("SELECT hits FROM public_recovery_quotas WHERE key=%s", (key,))
                    self.assertEqual(cur.fetchone()[0], 1)
            finally:
                with connect() as conn, conn.cursor() as cur:
                    cur.execute("DELETE FROM public_recovery_quotas WHERE key=%s", (key,))

    def test_concurrent_quota_enforces_exact_limit(self):
        if not os.environ.get("DB_NAME", "").startswith("sgc_owner_qa_"):
            self.fail("Refusing non-QA database")
        from server import connect
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            self.assertEqual(cur.fetchone()[0], os.environ["DB_NAME"])
        app = Flask(__name__)
        app.config["AUTH_TRUSTED_PROXY_IPS"] = ""
        address = "synthetic-concurrent-" + os.urandom(12).hex()
        key = auth.hmac.new(b"synthetic quota concurrency key", b"sgc:public-auth:v1:login:" + address.encode(), auth.hashlib.sha256).digest()
        def attempt(_):
            with app.test_request_context("/", environ_base={"REMOTE_ADDR": address}):
                result = auth.AuthService(app, connect)._public_auth_quota("login")
                return 200 if result is None else result.status_code
        try:
            with patch("auth.Path.read_bytes", return_value=b"synthetic quota concurrency key"), ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(attempt, range(auth.AUTH_RATE_LIMITS["login"] + 10)))
            self.assertEqual(results.count(200), auth.AUTH_RATE_LIMITS["login"])
            self.assertEqual(results.count(429), 10)
            with connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT hits FROM public_recovery_quotas WHERE key=%s", (key,))
                self.assertEqual(cur.fetchone()[0], auth.AUTH_RATE_LIMITS["login"] + 10)
        finally:
            with connect() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM public_recovery_quotas WHERE key=%s", (key,))


if __name__ == "__main__":
    unittest.main()
