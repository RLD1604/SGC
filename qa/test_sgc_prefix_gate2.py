"""Gate 2 tests for running the application below /SGC without a database."""

import hashlib
import importlib
import json
import os
import sys
import unittest
from pathlib import Path

from flask import Flask, Response, jsonify, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_server(base_path="/SGC", secure=True):
    os.environ["APP_BASE_PATH"] = base_path
    os.environ["AUTH_COOKIE_SECURE"] = "true" if secure else "false"
    # server registers module-level Flask blueprints. Reload those factories as
    # well so each configuration receives a pristine application graph.
    for name in ("server", "ai_review", "editorial_api"):
        sys.modules.pop(name, None)
    return importlib.import_module("server")


class PrefixRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()
        cls.app = cls.server.app

        @cls.app.post("/__gate2_echo")
        def gate2_echo():
            return jsonify(request.get_json())

        cls.artifact = b"official-artifact\x00unchanged\xff"

        @cls.app.get("/__gate2_artifact")
        def gate2_artifact():
            return Response(cls.artifact, mimetype="application/octet-stream")

        cls.client = cls.app.test_client()

    def test_sgc_without_slash_redirects_to_canonical_mount(self):
        response = self.client.get("/SGC")
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["Location"], "/SGC/")

    def test_html_assets_and_links_remain_below_mount(self):
        response = self.client.get("/SGC/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('<base href="/SGC/">', body)
        self.assertIn('<meta name="sqa-base-path" content="/SGC">', body)
        self.assertIn('src="/SGC/base-path.js"', body)
        self.assertRegex(body, r'href="/SGC/style\.css(?:\?v=\d+)?"')
        self.assertIn('src="/SGC/vendor/tinymce/tinymce.min.js"', body)
        self.assertNotIn("/SGC/SGC", body)
        for path in ("base-path.js", "style.css", "vendor/tinymce/tinymce.min.js", "photo-editor.js", "word-processor.js"):
            with self.subTest(path=path):
                asset = self.client.get("/SGC/" + path)
                try:
                    self.assertEqual(asset.status_code, 200)
                    self.assertGreater(len(asset.data), 0)
                finally:
                    asset.close()

    def test_static_json_is_streamed_unchanged_with_cache_validation(self):
        plain = self.client.get('/version.json')
        mounted = self.client.get('/SGC/version.json')
        try:
            self.assertEqual(plain.status_code, 200)
            self.assertEqual(mounted.status_code, 200)
            self.assertEqual(plain.data, mounted.data)
            self.assertEqual(mounted.data, (ROOT / 'public/version.json').read_bytes())
            self.assertEqual(mounted.headers['ETag'], plain.headers['ETag'])
            cached = self.client.get('/SGC/version.json', headers={'If-None-Match': mounted.headers['ETag']})
            try:
                self.assertEqual(cached.status_code, 304)
                self.assertEqual(cached.data, b'')
            finally:
                cached.close()
        finally:
            plain.close()
            mounted.close()

    def test_api_is_mounted_and_anonymous_access_is_denied_normally(self):
        response = self.client.get("/SGC/api/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("/SGC/SGC", response.get_data(as_text=True))

    def test_media_is_prefixed_only_at_http_boundary(self):
        digest = "a" * 64
        canonical = {"document": {"cover": "/images/jardim.jpg", "photos": [{"src": "/api/media/" + digest, "caption": "/api/untouched"}]}}
        outbound = self.server._rewrite_media_urls(canonical, "/SGC")
        self.assertEqual(outbound["document"]["cover"], "/SGC/images/jardim.jpg")
        self.assertEqual(outbound["document"]["photos"][0]["src"], "/SGC/api/media/" + digest)
        self.assertEqual(outbound["document"]["photos"][0]["caption"], "/api/untouched")
        inbound = self.server._rewrite_media_urls(outbound, "/SGC", inbound=True)
        self.assertEqual(inbound, canonical)

        response = self.client.post("/SGC/__gate2_echo", json=outbound)
        self.assertEqual(response.status_code, 200)
        # The request is canonicalized before application code and prefixed
        # again only in the JSON response, proving no /SGC/SGC accumulation.
        self.assertEqual(response.get_json(), outbound)
        self.assertNotIn("/SGC/SGC", response.get_data(as_text=True))

    def test_binary_artifact_bytes_and_hash_are_never_rewritten(self):
        plain = self.client.get("/__gate2_artifact")
        mounted = self.client.get("/SGC/__gate2_artifact")
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(mounted.status_code, 200)
        self.assertEqual(plain.data, self.artifact)
        self.assertEqual(mounted.data, self.artifact)
        self.assertEqual(hashlib.sha256(plain.data).digest(), hashlib.sha256(mounted.data).digest())

    def test_static_artifact_matches_unprefixed_mode_byte_for_byte(self):
        plain = self.client.get("/base-path.js")
        mounted = self.client.get("/SGC/base-path.js")
        try:
            self.assertEqual(plain.status_code, 200)
            self.assertEqual(mounted.status_code, 200)
            self.assertEqual(hashlib.sha256(plain.data).digest(), hashlib.sha256(mounted.data).digest())
        finally:
            plain.close()
            mounted.close()

    def test_directory_traversal_is_rejected(self):
        for path in ("/SGC/../server.py", "/SGC/%2e%2e/server.py", "/SGC/%2e%2e%2fserver.py"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"Transactional PostgreSQL persistence", response.data)


class CookieContractTests(unittest.TestCase):
    def test_prefixed_cookie_names_and_security_attributes(self):
        server = load_server()
        service = server.app.extensions["sqa_auth"]
        with server.app.test_request_context("/SGC/api/auth/login", base_url="https://sgc.test"):
            response = jsonify(ok=True)
            service._set_cookies(response, "session-secret", "csrf-secret")
        cookies = response.headers.getlist("Set-Cookie")
        self.assertEqual(len(cookies), 2)
        session = next(value for value in cookies if value.startswith("sqa_sgc_session="))
        csrf = next(value for value in cookies if value.startswith("sqa_sgc_csrf="))
        for value in cookies:
            self.assertIn("Path=/SGC", value)
            self.assertIn("Secure", value)
            self.assertIn("SameSite=Lax", value)
        self.assertIn("HttpOnly", session)
        self.assertNotIn("HttpOnly", csrf)


class UnprefixedCompatibilityTests(unittest.TestCase):
    def test_unprefixed_mode_keeps_original_routes_and_cookie_scope(self):
        server = load_server("")
        client = server.app.test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn('name="sqa-base-path"', body)
        self.assertRegex(body, r'href="/style\.css(?:\?v=\d+)?"')
        self.assertEqual(server.app.config["AUTH_COOKIE_PATH"], "/")
        self.assertNotIn("AUTH_COOKIE_NAME", server.app.config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
