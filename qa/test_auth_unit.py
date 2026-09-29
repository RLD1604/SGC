"""Pure unit tests for auth primitives; no Docker or PostgreSQL required."""

import hashlib
import unittest

from flask import Flask, g

import auth


class AuthPrimitiveTests(unittest.TestCase):
    def test_normalize_login_is_nfkc_trimmed_and_casefolded(self):
        self.assertEqual(auth.normalize_login("  Usua\u0301RIO@EXEMPLO.COM  "), "usuário@exemplo.com")
        self.assertEqual(auth.normalize_login("ＦＵＮＣＩＯＮＡＲＩＯ"), "funcionario")

    def test_normalize_login_rejects_empty_and_internal_spaces(self):
        for value in ("", "   ", "duas pessoas", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                auth.normalize_login(value)

    def test_password_policy_enforces_requested_complexity_and_technical_maximum(self):
        for value in (
            "Aa1!aaa",
            "Senha!abc",
            "senha1!a",
            "Senha123",
            "Senha 123",
            "A1!" + "x" * 1022,
            None,
        ):
            with self.subTest(length=None if value is None else len(value)), self.assertRaises(ValueError):
                auth.validate_password(value)
        auth.validate_password("Senha1!a")
        auth.validate_password("Árvore9!x")
        auth.validate_password("A1!" + "x" * 1021)

    def test_argon2_hash_round_trip_and_wrong_password(self):
        encoded = auth.hash_password("Uma frase muito segura!2026")
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertTrue(auth.verify_password(encoded, "Uma frase muito segura!2026"))
        self.assertFalse(auth.verify_password(encoded, "Uma frase muito errada!2026"))
        self.assertFalse(auth.verify_password("hash-inválido", "Uma frase muito segura!2026"))

    def test_opaque_token_persists_only_sha256_digest(self):
        raw, digest = auth.generate_token()
        self.assertGreaterEqual(len(raw), 40)
        self.assertEqual(digest, hashlib.sha256(raw.encode("utf-8")).digest())
        self.assertNotIn(raw.encode("utf-8"), digest)
        self.assertTrue(auth.tokens_match(raw, digest))
        self.assertFalse(auth.tokens_match(raw + "x", digest))

    def test_current_principal_never_adds_csrf(self):
        app = Flask(__name__)
        expected = {
            "user_id": "u1",
            "session_id": "s1",
            "memberships": ["c1"],
            "grants": [{"condominium_id": "c1", "role": "supervisor"}],
        }
        with app.test_request_context("/"):
            g.principal = expected
            g.auth_session = {"csrf_hash": b"secret"}
            self.assertIs(auth.current_principal(), expected)
            self.assertNotIn("csrf_token", auth.current_principal())

    def test_require_session_denies_anonymous_request(self):
        app = Flask(__name__)

        @app.get("/protected")
        @auth.require_session
        def protected():
            return {"ok": True}

        response = app.test_client().get("/protected")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Entre novamente", response.get_json()["error"])

    def test_register_auth_exposes_expected_routes_without_connecting(self):
        app = Flask(__name__)

        def forbidden_connect():
            raise AssertionError("registration must not access the database")

        service = auth.register_auth(app, forbidden_connect, None)
        self.assertIs(app.extensions["sqa_auth"], service)
        rules = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
        expected = {
            "/api/auth/login",
            "/api/auth/session",
            "/api/auth/me",
            "/api/auth/logout",
            "/api/auth/invitations",
            "/api/auth/activate",
            "/api/auth/recovery/request",
            "/api/auth/recovery/complete",
            "/api/auth/users/<user_id>/disable",
        }
        self.assertTrue(expected.issubset(rules))

    def test_session_constants_match_product_contract(self):
        self.assertEqual(auth.COOKIE_NAME, "sqa_session")
        self.assertEqual(auth.IDLE_TIMEOUT.total_seconds(), 30 * 60)
        self.assertEqual(auth.ABSOLUTE_TIMEOUT.total_seconds(), 12 * 60 * 60)
        self.assertEqual(auth.INVITATION_TIMEOUT.total_seconds(), 48 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
