"""Offline Streamable HTTP behavior tests; no provider or network access."""

from email.message import Message
import io
import json
import socket
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from remote_mcp import McpError, McpHttpClient


class FakeResponse:
    def __init__(self, data=b"", content_type="application/json", status=200, headers=None):
        self.body = io.BytesIO(data)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.read_limits, self.readline_limits = [], []
        self.closed = False

    def read(self, size=-1):
        self.read_limits.append(size)
        return self.body.read(size)

    def readline(self, size=-1):
        self.readline_limits.append(size)
        return self.body.readline(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self.body.close()


def response(result, request_id=1, **kwargs):
    message = {"jsonrpc": "2.0", "id": request_id, "result": result}
    return FakeResponse(json.dumps(message, ensure_ascii=False).encode("utf-8"), **kwargs)


def initialized_responses(final):
    return [response({"protocolVersion": "2025-03-26", "capabilities": {}}),
            FakeResponse(status=202), final]


def headers(request):
    return {key.lower(): value for key, value in request.header_items()}


class McpHttpTransportTests(unittest.TestCase):
    def client(self, **kwargs):
        return McpHttpClient("https://search.example/mcp", **kwargs)

    def test_json_request_and_matching_result(self):
        incoming = response({"content": [{"type": "text", "text": "中文结果"}]})
        with patch("remote_mcp.urllib.request.urlopen", return_value=incoming) as opened:
            result = self.client(timeout=12).request("tools/call", {"name": "search", "arguments": {"query": "公司"}})
        self.assertEqual(result["content"][0]["text"], "中文结果")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        sent = json.loads(request.data)
        self.assertEqual(sent["jsonrpc"], "2.0")
        self.assertEqual(sent["id"], 1)
        self.assertEqual(sent["params"]["arguments"]["query"], "公司")
        self.assertEqual(opened.call_args.kwargs["timeout"], 12)
        self.assertEqual(headers(request)["accept"], "application/json, text/event-stream")
        self.assertEqual(headers(request)["content-type"], "application/json")
        self.assertTrue(incoming.closed)

    def test_initialization_carries_session_protocol_and_notification(self):
        notification_response = FakeResponse(b"ignored notification body", status=202)
        replies = [response({"protocolVersion": "2025-11-25", "capabilities": {}},
                            headers={"Mcp-Session-Id": "session-123"}),
                   notification_response, response({"tools": [{"name": "search"}]}, request_id=2),
                   response({"content": []}, request_id=3)]
        client = self.client(headers={"Authorization": "Bearer test-placeholder"})
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies) as opened:
            self.assertEqual(client.list_tools(), [{"name": "search"}])
            self.assertEqual(client.call_tool("search", {"query": "test"}), {"content": []})
        requests = [call.args[0] for call in opened.call_args_list]
        bodies = [json.loads(request.data) for request in requests]
        self.assertEqual([body["method"] for body in bodies],
                         ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertNotIn("id", bodies[1])
        self.assertEqual([body["id"] for body in bodies if "id" in body], [1, 2, 3])
        self.assertEqual(bodies[0]["params"]["capabilities"], {})
        for request in requests[1:]:
            self.assertEqual(headers(request)["mcp-session-id"], "session-123")
            self.assertEqual(headers(request)["mcp-protocol-version"], "2025-11-25")
            self.assertEqual(headers(request)["authorization"], "Bearer test-placeholder")
        self.assertEqual(notification_response.read_limits, [])
        self.assertEqual(client.protocol, "2025-11-25")
        self.assertEqual(client.session_id, "session-123")

    def test_supported_notification_statuses_do_not_require_json(self):
        for status in (200, 202, 204):
            with self.subTest(status=status):
                accepted = FakeResponse(b"not JSON", status=status)
                replies = [response({"protocolVersion": "2025-06-18"}), accepted]
                with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
                    self.client().initialize()
                self.assertEqual(accepted.read_limits, [])

    def test_unsupported_protocol_does_not_send_initialized_notification(self):
        with patch("remote_mcp.urllib.request.urlopen", return_value=response({"protocolVersion": "2099-01-01"})) as opened:
            with self.assertRaisesRegex(RuntimeError, "unsupported protocol"):
                self.client().initialize()
        self.assertEqual(opened.call_count, 1)

    def test_malformed_protocol_is_reported_without_a_type_error(self):
        for version in ({}, []):
            with self.subTest(version=version):
                with patch("remote_mcp.urllib.request.urlopen", return_value=response({"protocolVersion": version})):
                    with self.assertRaises(RuntimeError):
                        self.client().initialize()

    def test_redirect_does_not_forward_provider_credentials_or_session(self):
        client = self.client(headers={"Authorization": "Bearer placeholder", "x-api-key": "placeholder"})
        client.initialized, client.session_id = True, "session-placeholder"
        with patch("remote_mcp.urllib.request.urlopen", return_value=response({})) as opened:
            client.request("tools/list")
        request = opened.call_args.args[0]
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, "Found", Message(), "https://different.example/mcp")
        self.assertIn("authorization", headers(request))
        for header in ("authorization", "x-api-key", "mcp-session-id"):
            self.assertNotIn(header, headers(redirected))

    def test_response_ids_must_match_and_boolean_id_is_not_integer_id(self):
        for request_id in (99, "1", True, None):
            with self.subTest(response_id=request_id):
                with patch("remote_mcp.urllib.request.urlopen", return_value=response({}, request_id=request_id)):
                    with self.assertRaises(RuntimeError):
                        self.client().request("tools/list")

    def test_response_requires_jsonrpc_2_envelope(self):
        for version in (None, "1.0"):
            with self.subTest(version=version):
                message = {"id": 1, "result": {}}
                if version is not None:
                    message["jsonrpc"] = version
                reply = FakeResponse(json.dumps(message).encode())
                with patch("remote_mcp.urllib.request.urlopen", return_value=reply):
                    with self.assertRaises(RuntimeError):
                        self.client().request("tools/list")

    def test_rpc_error_reports_code_without_echoing_untrusted_message(self):
        message = {"jsonrpc": "2.0", "id": 1,
                   "error": {"code": -32602, "message": "secret credential reflected here"}}
        for content_type, raw in [
            ("application/json", json.dumps(message).encode()),
            ("text/event-stream", ("data: " + json.dumps(message) + "\n\n").encode()),
        ]:
            with self.subTest(content_type=content_type):
                with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(raw, content_type)):
                    with self.assertRaisesRegex(RuntimeError, "-32602") as caught:
                        self.client().request("tools/list")
                self.assertNotIn("secret credential", str(caught.exception))

    def test_sse_ignores_notifications_and_other_ids_and_joins_data_lines(self):
        progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}}
        other = {"jsonrpc": "2.0", "id": 99, "result": {"wrong": True}}
        payload = ": heartbeat\r\n\r\nevent: message\r\n"
        payload += "data: " + json.dumps(progress) + "\r\n\r\n"
        payload += "data: " + json.dumps(other) + "\r\n\r\n"
        payload += 'data: {"jsonrpc": "2.0",\r\ndata: "id": 1, "result": {"text": "中文"}}\r\n\r\n'
        reply = FakeResponse(payload.encode("utf-8"), "text/event-stream; charset=utf-8")
        with patch("remote_mcp.urllib.request.urlopen", return_value=reply):
            self.assertEqual(self.client().request("tools/list"), {"text": "中文"})
        self.assertTrue(reply.closed)

    def test_sse_final_event_is_read_at_eof(self):
        payload = b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
        with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(payload, "text/event-stream")):
            self.assertEqual(self.client().request("tools/list"), {"ok": True})

    def test_sse_empty_priming_event_precedes_the_response(self):
        payload = (b'id: resume-1\ndata: \n\n'
                   b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n')
        with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(payload, "text/event-stream")):
            self.assertEqual(self.client().request("tools/list"), {"ok": True})

    def test_sse_ping_is_acknowledged_without_abandoning_the_tool_response(self):
        payload = (b'data: {"jsonrpc":"2.0","id":"server-ping","method":"ping"}\n\n'
                   b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n')
        replies = [FakeResponse(payload, "text/event-stream"), FakeResponse(status=202)]
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies) as opened:
            self.assertEqual(self.client().request("tools/list"), {"ok": True})
        self.assertEqual(json.loads(opened.call_args_list[1].args[0].data),
                         {"jsonrpc": "2.0", "id": "server-ping", "result": {}})

    def test_failed_initialization_notification_cannot_leave_a_ready_client(self):
        replies = [response({"protocolVersion": "2025-11-25"},
                            headers={"Mcp-Session-Id": "old-session"}),
                   urllib.error.HTTPError("https://search.example/mcp", 500, "error", {}, None)]
        client = self.client()
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
            with self.assertRaises(RuntimeError):
                client.initialize()
        self.assertFalse(client.initialized)
        self.assertIsNone(client.session_id)

    def test_invalid_rpc_error_code_is_not_echoed(self):
        message = {"jsonrpc": "2.0", "id": 1,
                   "error": {"code": "reflected-secret", "message": "error"}}
        with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(json.dumps(message).encode())):
            with self.assertRaises(RuntimeError) as caught:
                self.client().request("tools/list")
        self.assertNotIn("reflected-secret", str(caught.exception))

    def test_sse_without_matching_response_or_with_server_request_fails(self):
        payloads = [b": heartbeat\n\n", b'data: {"jsonrpc":"2.0","id":99,"result":{}}\n\n',
                    b'data: {"jsonrpc":"2.0","id":20,"method":"sampling/createMessage","params":{}}\n\n']
        for payload in payloads:
            with self.subTest(payload=payload):
                with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(payload, "text/event-stream")):
                    with self.assertRaises(RuntimeError):
                        self.client().request("tools/list")

    def test_json_and_sse_have_bounded_reads(self):
        variants = [("application/json", b"x" * 129),
                    ("text/event-stream", b"data: " + b"x" * 129),
                    ("text/event-stream", (b": " + b"x" * 70 + b"\n\n") * 2)]
        for content_type, data in variants:
            with self.subTest(content_type=content_type, size=len(data)):
                reply = FakeResponse(data, content_type)
                with patch.object(McpHttpClient, "MAX_BYTES", 128):
                    with patch("remote_mcp.urllib.request.urlopen", return_value=reply):
                        with self.assertRaisesRegex(RuntimeError, "size limit"):
                            self.client().request("tools/list")
                limits = reply.readline_limits if content_type == "text/event-stream" else reply.read_limits
                self.assertTrue(limits)
                self.assertTrue(all(size == 129 for size in limits))

    def test_sse_deadline_stops_before_late_result_without_sleeping(self):
        payload = b': heartbeat\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        reply = FakeResponse(payload, "text/event-stream")
        with patch("remote_mcp.urllib.request.urlopen", return_value=reply):
            with patch("remote_mcp.time.monotonic", side_effect=[100, 100, 131]):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    self.client(timeout=30).request("tools/list")
        self.assertEqual(len(reply.readline_limits), 1)

    def test_invalid_json_or_utf8_is_reported_for_both_encodings(self):
        for content_type, data in [("application/json", b"not json"), ("application/json", b"\xff"),
                                   ("text/event-stream", b"data: not json\n\n"),
                                   ("text/event-stream", b"data: \xff\n\n")]:
            with self.subTest(content_type=content_type, data=data):
                with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(data, content_type)):
                    with self.assertRaisesRegex(RuntimeError, "invalid JSON or text"):
                        self.client().request("tools/list")

    def test_transport_errors_do_not_echo_credentials_or_upstream_body(self):
        secret = "should-not-appear"
        failures = [urllib.error.HTTPError("https://example.com/?token=" + secret, 401, secret, {}, io.BytesIO(secret.encode())),
                    urllib.error.URLError(secret), TimeoutError(secret)]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                with patch("remote_mcp.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(RuntimeError) as caught:
                        self.client().request("tools/list")
                self.assertNotIn(secret, str(caught.exception))

    def test_tool_catalog_rejects_invalid_shape_or_cursor(self):
        for catalog in ({"tools": {}}, {"tools": [], "nextCursor": 1},
                        {"tools": [{"name": "search"}, {"name": "search"}]}):
            with self.subTest(catalog=catalog):
                replies = initialized_responses(response(catalog, request_id=2))
                with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
                    with self.assertRaises(RuntimeError):
                        self.client().list_tools()

    def test_tool_catalog_follows_pages_and_accounts_for_metadata(self):
        replies = initialized_responses(response({"tools": [{"name": "search"}], "nextCursor": "page-2"}, request_id=2))
        replies.append(response({"tools": [{"name": "extract"}]}, request_id=3))
        client = self.client()
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies) as opened:
            self.assertEqual([tool["name"] for tool in client.list_tools()], ["search", "extract"])
        self.assertEqual(json.loads(opened.call_args_list[-1].args[0].data)["params"], {"cursor": "page-2"})
        self.assertEqual(client.snapshot_usage(), {"http_requests": 4, "initialize_requests": 1,
                         "list_requests": 2, "tool_calls": 0, "session_recoveries": 0})

    def test_repeated_cursor_and_catalog_limits_stop_metadata_work(self):
        client = self.client()
        client.initialized = True
        replies = [response({"tools": [], "nextCursor": "same"}),
                   response({"tools": [], "nextCursor": "same"}, request_id=2)]
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies) as opened:
            with self.assertRaisesRegex(McpError, "repeated"):
                client.list_tools()
        self.assertEqual(opened.call_count, 2)
        client = self.client()
        client.initialized = True
        with patch.object(client, "MAX_TOOL_PAGES", 1), patch("remote_mcp.urllib.request.urlopen",
                return_value=response({"tools": [], "nextCursor": "more"})):
            with self.assertRaisesRegex(McpError, "pagination limit"):
                client.list_tools()
        client = self.client()
        client.initialized = True
        with patch.object(client, "MAX_TOOLS", 1), patch("remote_mcp.urllib.request.urlopen",
                return_value=response({"tools": [{"name": "a"}, {"name": "b"}]})):
            with self.assertRaisesRegex(McpError, "size limit"):
                client.list_tools()

    def test_expired_session_restarts_entire_catalog_once(self):
        client = self.client()
        client.initialized, client.session_id = True, "old"
        replies = [response({"tools": [{"name": "stale"}], "nextCursor": "page-2"}),
                   urllib.error.HTTPError(client.url, 404, "expired", {}, io.BytesIO()),
                   response({"protocolVersion": "2025-03-26"}, request_id=3, headers={"Mcp-Session-Id": "new"}),
                   FakeResponse(status=202), response({"tools": [{"name": "current"}]}, request_id=4)]
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
            self.assertEqual(client.list_tools(), [{"name": "current"}])
        self.assertEqual(client.session_id, "new")
        self.assertEqual(client.snapshot_usage()["session_recoveries"], 1)
        self.assertEqual(client.snapshot_usage()["list_requests"], 3)
        self.assertEqual(client.snapshot_usage()["tool_calls"], 0)

    def test_expired_tool_call_is_not_replayed_and_next_action_reinitializes(self):
        client = self.client()
        client.initialized, client.session_id = True, "old"
        first = urllib.error.HTTPError(client.url, 404, "expired", {}, io.BytesIO())
        with patch("remote_mcp.urllib.request.urlopen", side_effect=first) as opened:
            with self.assertRaises(McpError) as caught:
                client.call_tool("search", {"query": "first"})
        self.assertEqual(caught.exception.kind, "session_expired")
        self.assertEqual(opened.call_count, 1)
        self.assertFalse(client.initialized)
        self.assertIsNone(client.session_id)
        replies = [response({"protocolVersion": "2025-03-26"}, request_id=2), FakeResponse(status=202),
                   response({"content": []}, request_id=3)]
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
            client.call_tool("search", {"query": "second"})
        self.assertEqual(client.snapshot_usage()["tool_calls"], 2)
        self.assertEqual(client.snapshot_usage()["initialize_requests"], 1)

    def test_http_failure_classes_and_retry_after_never_trigger_tool_retry(self):
        for code, kind, retryable in ((401, "authentication_required", False), (402, "quota_exhausted", False),
                (403, "authentication_required", False), (404, "http_error", False),
                (429, "rate_limited", True), (503, "transient_http", True)):
            with self.subTest(code=code):
                client = self.client()
                client.initialized = True
                failure = urllib.error.HTTPError(client.url, code, "reflected-secret", {"Retry-After": "7"}, io.BytesIO())
                with patch("remote_mcp.urllib.request.urlopen", side_effect=failure) as opened:
                    with self.assertRaises(McpError) as caught:
                        client.call_tool("search", {"query": "test"})
                self.assertEqual(caught.exception.kind, kind)
                self.assertEqual(caught.exception.retryable, retryable)
                self.assertEqual(caught.exception.retry_after, 7)
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(client.snapshot_usage()["tool_calls"], 1)
                self.assertNotIn("reflected-secret", json.dumps(caught.exception.details()))

    def test_tool_change_notification_invalidates_catalog_version(self):
        client = self.client()
        initial_version = client.catalog_version
        payload = (b'data: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n\n'
                   b'data: {"jsonrpc":"2.0","id":1,"result":{"content":[]}}\n\n')
        with patch("remote_mcp.urllib.request.urlopen", return_value=FakeResponse(payload, "text/event-stream")):
            client.request("tools/call", {"name": "search", "arguments": {}})
        self.assertEqual(client.catalog_version, initial_version + 1)

    def test_socket_timeouts_are_classified_on_supported_python_versions(self):
        for failure in (socket.timeout("private"), urllib.error.URLError(socket.timeout("private"))):
            with self.subTest(failure=type(failure).__name__):
                client = self.client()
                client.initialized = True
                with patch("remote_mcp.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(McpError) as caught:
                        client.call_tool("search", {"query": "test"})
                self.assertEqual(caught.exception.kind, "timeout")
                self.assertEqual(client.snapshot_usage()["tool_calls"], 1)
                self.assertNotIn("private", str(caught.exception))

    def test_invalid_session_header_is_not_forwarded(self):
        for session in ("with space", "control\x01", "非ASCII", "x" * 4097):
            with self.subTest(session=session[:20]):
                reply = response({"protocolVersion": "2025-03-26"}, headers={"Mcp-Session-Id": session})
                with patch("remote_mcp.urllib.request.urlopen", return_value=reply) as opened:
                    with self.assertRaisesRegex(McpError, "invalid session"):
                        self.client().initialize()
                self.assertEqual(opened.call_count, 1)

    def test_tool_level_errors_are_not_reported_as_successful_results(self):
        replies = initialized_responses(response({"isError": True, "content": [{"type": "text", "text": "provider failure"}]}, request_id=2))
        with patch("remote_mcp.urllib.request.urlopen", side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, "tool returned an error"):
                self.client().call_tool("search", {"query": "test"})


if __name__ == "__main__":
    unittest.main()
