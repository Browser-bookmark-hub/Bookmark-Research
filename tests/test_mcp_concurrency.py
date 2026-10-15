"""Connection-level responsiveness, bounded work and explicit cancellation behavior."""
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mcp_server
from settings import Settings


def request(identifier, name, arguments=None):
    return {"jsonrpc": "2.0", "id": identifier, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


class ScriptInput:
    def __init__(self, messages, gate_at=None, started=None):
        self.lines = [message + "\n" if isinstance(message, str) else json.dumps(message) + "\n" for message in messages]
        self.position, self.gate_at, self.started = 0, gate_at, started

    def readline(self, limit):
        if self.position == self.gate_at and not self.started.wait(3):
            raise TimeoutError("Network work never started")
        if self.position == len(self.lines):
            return ""
        line = self.lines[self.position]
        self.position += 1
        return line[:limit]


class RecordedOutput:
    def __init__(self, release):
        self.messages, self.release = [], release

    def write(self, text):
        message = json.loads(text)
        self.messages.append(message)
        if message.get("id") == "local":
            self.release.set()

    def flush(self):
        pass


class McpConcurrencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.started, self.release = threading.Event(), threading.Event()
        self.output = RecordedOutput(self.release)
        self.stderr = io.StringIO()
        self.engine = Mock()
        self.calls = []
        self.engine.fetch.side_effect = self.fetch
        self.handshake = [
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "concurrency-tests", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ]

    def fetch(self, urls, **options):
        self.calls.extend(urls)
        self.started.set()
        if not self.release.wait(3):
            raise TimeoutError("Local request was blocked behind the network call")
        return {"status": "ok", "urls": urls}

    def serve(self, messages, workers=4, pending=16, gate_at=3):
        with patch.object(mcp_server.StdioMcpServer, "_web", return_value=self.engine), \
                patch.object(mcp_server, "NETWORK_WORKERS", workers), \
                patch.object(mcp_server, "MAX_PENDING_CALLS", pending):
            mcp_server.serve(self.root / "index.sqlite3",
                stdin=ScriptInput(self.handshake + messages, gate_at, self.started),
                stdout=self.output, stderr=self.stderr, settings=Settings(self.root / "settings.json"))
        return self.output.messages

    def test_local_sqlite_request_finishes_while_fetch_waits_and_json_errors_still_recover(self):
        messages = self.serve([
            request("slow", "fetch_web", {"urls": ["https://example.test/slow"]}),
            "{broken-json",
            request("local", "index_status"),
        ])
        ids = [message["id"] for message in messages]
        self.assertLess(ids.index("local"), ids.index("slow"))
        local = next(message for message in messages if message["id"] == "local")
        self.assertFalse(local["result"]["isError"], local)
        self.assertEqual([], local["result"]["structuredContent"]["sources"])
        self.assertEqual(-32700, next(message for message in messages if message["id"] is None)["error"]["code"])
        self.assertFalse(next(message for message in messages if message["id"] == "slow")["result"]["isError"])

    def test_queue_limit_duplicate_ids_and_pending_only_cancellation(self):
        messages = self.serve([
            request(1, "fetch_web", {"urls": ["https://example.test/running"]}),
            request(2, "fetch_web", {"urls": ["https://example.test/queued"]}),
            request(3, "fetch_web", {"urls": ["https://example.test/overflow"]}),
            request(1, "fetch_web", {"urls": ["https://example.test/duplicate"]}),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}},
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
            request("local", "index_status"),
        ], workers=1, pending=2)
        errors = {message["id"]: message["error"]["code"] for message in messages if "error" in message}
        self.assertEqual({1: -32600, 2: -32800, 3: -32000}, errors)
        self.assertEqual(["https://example.test/running"], self.calls)
        self.assertTrue(any(message["id"] == 1 and "result" in message for message in messages))
        self.assertIn("already started", self.stderr.getvalue())

    def test_explicit_serve_arguments_set_queue_limits_without_patching_constants(self):
        # The CLI reads server.network_workers / server.max_pending_calls and
        # passes them to serve(); they must apply without touching the module
        # defaults that tests and embedders rely on.
        with patch.object(mcp_server.StdioMcpServer, "_web", return_value=self.engine):
            mcp_server.serve(self.root / "index.sqlite3",
                stdin=ScriptInput(self.handshake + [
                    request(1, "fetch_web", {"urls": ["https://example.test/running"]}),
                    request(2, "fetch_web", {"urls": ["https://example.test/queued"]}),
                    request(3, "fetch_web", {"urls": ["https://example.test/overflow"]}),
                    {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
                ], 3, self.started),
                stdout=self.output, stderr=self.stderr,
                settings=Settings(self.root / "settings.json"), workers=1, max_pending=2)
        errors = {message["id"]: message["error"]["code"] for message in self.output.messages if "error" in message}
        self.assertEqual(errors.get(3), -32000)

    def test_normal_eof_drains_all_accepted_calls_and_preserves_id_types(self):
        self.release.set()
        identifiers = [1, "1", 2, "second", 3, "third"]
        messages = self.serve([request(identifier, "fetch_web", {"urls": ["https://example.test/%d" % position]})
                               for position, identifier in enumerate(identifiers)], workers=1, gate_at=None)
        self.assertEqual(6, len(self.calls))
        returned = [(type(message["id"]), message["id"]) for message in messages if message["id"] != 0]
        self.assertCountEqual([(type(identifier), identifier) for identifier in identifiers], returned)
        self.assertTrue(all("result" in message and not message["result"].get("isError") for message in messages))

    def test_lazy_provider_initialization_is_shared_across_concurrent_requests(self):
        def create(**options):
            self.started.set()
            if not self.release.wait(3):
                raise TimeoutError("Provider initialization blocked local work")
            return self.engine
        messages = self.handshake + [
            request("first", "fetch_web", {"urls": ["https://example.test/first"]}),
            request("second", "fetch_web", {"urls": ["https://example.test/second"]}),
            request("local", "index_status"),
        ]
        with patch("web_search.SearchProviders", side_effect=create) as factory:
            mcp_server.serve(self.root / "index.sqlite3",
                stdin=ScriptInput(messages, 3, self.started), stdout=self.output,
                stderr=self.stderr, settings=Settings(self.root / "settings.json"))
        self.assertEqual(1, factory.call_count)
        self.assertEqual(2, len(self.calls))
        self.assertTrue(all("result" in message and not message["result"].get("isError")
                            for message in self.output.messages))


if __name__ == "__main__":
    unittest.main()
