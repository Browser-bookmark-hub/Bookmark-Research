"""One HTTP request, fixed origins, bounded responses and credential-safe errors."""

import http.client
import io
import json
import os
import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from service_http import ResearchHttp, ServiceError, _NoRedirect


class Response(io.BytesIO):
    pass


class ServiceHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = ResearchHttp(timeout=7)
        self.secret = "synthetic-credential-never-persist"
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": self.secret, "PARALLEL_API_KEY": self.secret})
        environment.start()
        self.addCleanup(environment.stop)
        self.opener = Mock()
        builder = patch("service_http.urllib.request.build_opener", return_value=self.opener)
        self.builder = builder.start()
        self.addCleanup(builder.stop)

    def request(self, **changes):
        arguments = {"provider": "openai", "method": "POST", "path": "/v1/responses", "payload": {"input": "Public question", "background": True}}
        arguments.update(changes)
        return self.client.request(**arguments)

    def test_documented_origins_authentication_and_single_attempt(self):
        for provider, path, auth in (("openai", "/v1/responses", "Authorization"), ("parallel", "/v1/tasks/runs", "X-api-key")):
            with self.subTest(provider=provider):
                self.opener.reset_mock()
                self.opener.open.return_value = Response(b'{"status":"queued"}')
                self.assertEqual(self.request(provider=provider, path=path), {"status": "queued"})
                self.assertEqual(self.opener.open.call_count, 1)
                sent = self.opener.open.call_args[0][0]
                self.assertTrue(sent.full_url.startswith(ResearchHttp.PROVIDERS[provider]["origin"] + "/v1/"))
                self.assertIn(self.secret, sent.get_header(auth))
                self.assertNotIn(self.secret.encode(), sent.data)
                self.assertEqual(json.loads(sent.data)["input"], "Public question")
                self.assertEqual(self.opener.open.call_args[1]["timeout"], 7)
                self.assertIsInstance(self.builder.call_args[0][0], _NoRedirect)

    def test_http_errors_never_expose_body_reason_or_credentials_or_retry(self):
        for status, expected in ((400, "invalid_request"), (401, "authentication_required"), (403, "authentication_required"),
                                 (404, "run_unavailable"), (408, "result_pending"), (422, "invalid_request"),
                                 (429, "rate_limited"), (500, "http_error"), (503, "http_error")):
            with self.subTest(status=status):
                self.opener.reset_mock()
                body = io.BytesIO((self.secret + " private body").encode())
                self.opener.open.side_effect = urllib.error.HTTPError("https://api.openai.com/", status, self.secret,
                                                                     {"Retry-After": "5"}, body)
                with self.assertRaises(ServiceError) as caught:
                    self.request()
                detail = caught.exception.details()
                self.assertEqual(detail["error_kind"], expected)
                self.assertEqual(detail["retry_after_seconds"], 5)
                self.assertEqual(detail["request_outcome_unknown"], status == 408 or status >= 500)
                self.assertNotIn(self.secret, json.dumps(detail))
                self.assertNotIn("private body", json.dumps(detail))
                self.assertTrue(body.closed)
                self.assertEqual(self.opener.open.call_count, 1)

    def test_redirects_cannot_forward_provider_credentials(self):
        handler = _NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 307, "redirect", {}, "https://unrelated.example.test/"))
        self.opener.open.side_effect = urllib.error.HTTPError("https://api.openai.com/", 307, "moved",
                                                             {"Location": "https://unrelated.example.test/"}, io.BytesIO())
        with self.assertRaises(ServiceError) as caught:
            self.request()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.opener.open.call_count, 1)

    def test_timeouts_truncated_reads_and_socket_errors_are_sanitized(self):
        failures = [TimeoutError(self.secret), socket.timeout(self.secret), urllib.error.URLError(self.secret),
                    http.client.IncompleteRead(self.secret.encode(), 100), http.client.RemoteDisconnected(self.secret), OSError(self.secret)]
        for error in failures:
            with self.subTest(error=type(error).__name__):
                self.opener.reset_mock()
                self.opener.open.side_effect = error
                with self.assertRaises(ServiceError) as caught:
                    self.request()
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn(self.secret, str(caught.exception))
                self.assertEqual(self.opener.open.call_count, 1)

    def test_response_size_json_shape_and_invalid_numbers_are_explicit_errors(self):
        for payload in (b"not JSON", b"[]", b"null", b'{"id":NaN}', b'{"usage":{"value":1e999}}',
                        b'{"usage":{"value":-1e999}}', b'{"id":"first","id":"second"}', b"\xff"):
            with self.subTest(payload=payload):
                self.opener.open.return_value = Response(payload)
                with self.assertRaises(ServiceError) as caught:
                    self.request()
                self.assertEqual(caught.exception.kind, "result_format")
                self.assertTrue(caught.exception.uncertain)
        self.opener.open.return_value = Response(b"x" * 33)
        with patch.object(self.client, "MAX_RESPONSE_BYTES", 32):
            with self.assertRaises(ServiceError) as caught:
                self.request()
        self.assertEqual(caught.exception.kind, "response_too_large")

    def test_missing_invalid_keys_payloads_and_paths_fail_before_network(self):
        for key in ("", "\n" + self.secret, " key with spaces"):
            with self.subTest(key_present=bool(key)), patch.dict(os.environ, {"OPENAI_API_KEY": key}):
                with self.assertRaises(ServiceError) as caught:
                    self.request()
                self.assertFalse(caught.exception.uncertain)
                self.assertNotIn(self.secret, str(caught.exception))
        bad = [
            {"provider": "unknown"}, {"method": "DELETE"}, {"path": "https://unrelated.example.test/v1/responses"},
            {"path": "//unrelated.example.test/v1/responses"}, {"path": "/v1/../secrets"},
            {"path": "/v1/responses?api_key=private"}, {"path": "/v1/responses#fragment"},
            {"path": "/v1/responses\nInjected: header"}, {"payload": {"invalid": float("nan")}},
            {"method": "GET", "path": "/v1/responses/resp_fixture", "payload": {}},
            {"provider": "parallel", "path": "/v1/tasks/runs/trun_fixture/cancel", "payload": {}},
        ]
        for arguments in bad:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.request(**arguments)
        self.opener.open.assert_not_called()

    def test_poll_and_cancel_shapes_are_explicit(self):
        for provider, method, path, payload in (
            ("openai", "GET", "/v1/responses/resp_fixture", None),
            ("openai", "POST", "/v1/responses/resp_fixture/cancel", {}),
            ("parallel", "GET", "/v1/tasks/runs/trun_fixture", None),
            ("parallel", "GET", "/v1/tasks/runs/trun_fixture/result?timeout=1", None),
        ):
            with self.subTest(path=path):
                self.opener.open.return_value = Response(b"{}")
                self.request(provider=provider, method=method, path=path, payload=payload)
        self.assertEqual(self.opener.open.call_count, 4)


if __name__ == "__main__":
    unittest.main()
