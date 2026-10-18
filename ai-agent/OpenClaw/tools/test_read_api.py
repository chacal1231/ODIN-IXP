import io
import os
import unittest
import urllib.error
from contextlib import redirect_stderr
from unittest.mock import patch

import read_api


class ClientSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GRAYLOG_URL": "https://logs.example.invalid/api",
            "GRAYLOG_TOKEN": "test-only-token",
            "LIBRENMS_URL": "https://nms.example.invalid/api/v0",
            "LIBRENMS_TOKEN": "test-only-token",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rejects_unsafe_origins_before_network(self):
        for url in ["http://logs.invalid", "https://user:pass@logs.invalid",
                    "https://logs.invalid/?next=x", "https://logs.invalid/#x"]:
            with self.subTest(url=url), patch.dict(os.environ, {"GRAYLOG_URL": url}), \
                    patch("urllib.request.build_opener") as opener:
                with self.assertRaises(ValueError):
                    read_api.request("graylog", "search/universal/relative", {})
                opener.assert_not_called()

    def test_rejects_path_escape_and_unknown_endpoints(self):
        for path in ["../devices", "/devices", "devices/../admin", "https://evil.invalid", "admin"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_api.request("librenms", path, {})

    def test_get_auth_encoding_timeout_and_valid_json(self):
        with patch("urllib.request.build_opener") as factory:
            opener = factory.return_value
            opener.open.return_value.__enter__.return_value.read.return_value = b'{"messages":[]}'
            result = read_api.request("graylog", "search/universal/relative", {"query": "a&b#c"})
            req = opener.open.call_args.args[0]
            self.assertEqual(req.method, "GET")
            self.assertIn("query=a%26b%23c", req.full_url)
            self.assertNotIn("test-only-token", req.full_url)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
            self.assertEqual(result, {"messages": []})
            self.assertTrue(any(isinstance(h, read_api.NoRedirect) for h in factory.call_args.args))

    def test_redirect_not_followed(self):
        self.assertIsNone(read_api.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    def test_rejects_header_injection(self):
        with patch.dict(os.environ, {"GRAYLOG_TOKEN": "token\r\nInjected: x"}):
            with self.assertRaises(ValueError):
                read_api.request("graylog", "search/universal/relative", {})

    def test_oversize_and_invalid_json(self):
        for body in [b'x' * 2_000_001, b'not-json']:
            with self.subTest(size=len(body)), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value.__enter__.return_value.read.return_value = body
                with self.assertRaises(ValueError):
                    read_api.request("librenms", "devices", {})

    def test_errors_do_not_expose_response_or_secret(self):
        for error in [urllib.error.HTTPError("https://private.invalid", 401, "test-only-token", {}, None),
                      TimeoutError("test-only-token")]:
            output = io.StringIO()
            with patch("sys.argv", ["read_api.py", "librenms", "devices"]), \
                    patch("read_api.request", side_effect=error), redirect_stderr(output):
                self.assertEqual(read_api.main(), 1)
            self.assertNotIn("test-only-token", output.getvalue())
            self.assertNotIn("private.invalid", output.getvalue())

    def test_graylog_limits_fail_before_network(self):
        for param in ["range=86401", "limit=101", "range=-1"]:
            with patch("sys.argv", ["read_api.py", "graylog", "search/universal/relative", "--param", param]), \
                    patch("read_api.request") as request, redirect_stderr(io.StringIO()):
                self.assertEqual(read_api.main(), 1)
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
