"""Protocol and integration tests for the bounded stdio MCP tools server."""

import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_server import PROTOCOLS, StdioMcpServer, serve
from settings import Settings


def request(method, params=None, request_id=1):
    result = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        result["params"] = params
    return result


def initialize(protocol="2025-11-25", request_id=1):
    return request("initialize", {"protocolVersion": protocol, "capabilities": {},
        "clientInfo": {"name": "bookmark-tests", "version": "1.0"}}, request_id)


def decode_tool(response):
    return json.loads(response["result"]["content"][0]["text"])


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bookmark-mcp-test-")
        self.base = Path(self.temp.name)
        self.db_path = self.base / "index.sqlite3"
        self.stderr = io.StringIO()
        self.settings = Settings(self.base / "settings.json")
        self.server = StdioMcpServer(self.db_path, stderr=self.stderr, settings=self.settings)
        self.package = self.base / "Package"
        self.section_path = self.package / "临时栏目" / "常规链式" / "A-1 demo.json"
        self.section_path.parent.mkdir(parents=True)
        self.document = {"format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "temp-section-A-1", "label": "A-1", "title": "测试",
            "items": [{"id": "temp-one", "sectionId": "temp-section-A-1", "type": "bookmark",
                "title": "示例公司甲文档", "url": "https://example.test/docs", "note": "初始笔记"}]}
        self.write_document()

    def tearDown(self):
        self.server.close()
        self.temp.cleanup()

    def write_document(self):
        self.section_path.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")

    def ready(self, protocol="2025-11-25"):
        response = self.server.handle(initialize(protocol))
        self.assertNotIn("error", response)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        return response

    def call(self, name, arguments=None):
        return self.server.handle(request("tools/call", {"name": name, "arguments": arguments or {}}))

    def sync(self):
        response = self.call("sync_package", {"package_path": str(self.package), "source_id": "fixture"})
        self.assertFalse(response["result"]["isError"], response)
        return decode_tool(response)

    def test_initialization_discovery_and_lazy_database(self):
        response = self.ready()
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(response["result"]["capabilities"], {"tools": {}})
        listing = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual({tool["name"] for tool in listing}, {
            "sync_package", "search_bookmarks", "get_context", "index_status",
            "search_web", "fetch_web", "search_providers", "get_settings", "update_settings"})
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in listing))
        self.assertFalse(self.db_path.exists())
        self.assertIsNone(self.server._providers)
        self.assertEqual(self.server.handle(request("ping"))["result"], {})

    def test_all_protocols_and_version_specific_content(self):
        for protocol in PROTOCOLS:
            server = StdioMcpServer(self.base / (protocol + ".sqlite3"), stderr=self.stderr)
            try:
                self.assertEqual(server.handle(initialize(protocol))["result"]["protocolVersion"], protocol)
                server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
                result = server.handle(request("tools/call", {"name": "index_status"}))["result"]
                self.assertEqual("structuredContent" in result, protocol in ("2025-06-18", "2025-11-25"))
                self.assertFalse(result["isError"])
                self.assertEqual(json.loads(result["content"][0]["text"])["sources"], [])
            finally:
                server.close()
        response = self.server.handle(initialize("2099-01-01"))
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOLS[-1])
        self.assertEqual(self.server.handle(initialize())["error"]["code"], -32600)

    def test_local_sync_search_refresh_and_snapshot_opt_out(self):
        self.ready()
        self.assertEqual(self.sync()["counts"]["bookmarks"], 1)
        response = self.call("search_bookmarks", {"source_id": "fixture", "targets": ["示例公司甲"]})
        data = decode_tool(response)
        self.assertEqual(data["total"], 1)
        self.assertTrue(data["refresh"]["performed"])
        self.assertEqual(data["refresh"]["sync"]["changed_files"], 0)
        self.document["items"][0]["note"] = "新备注"
        self.write_document()
        old = decode_tool(self.call("search_bookmarks", {"source_id": "fixture", "targets": ["新备注"], "refresh": False}))
        self.assertEqual(old["total"], 0)
        self.assertEqual(old["refresh"]["mode"], "saved_snapshot")
        current = decode_tool(self.call("search_bookmarks", {"source_id": "fixture", "targets": ["新备注"]}))
        self.assertEqual(current["total"], 1)
        self.assertEqual(current["refresh"]["sync"]["items_updated"], 1)
        context = decode_tool(self.call("get_context", {"source_id": "fixture", "item_id": "temp-one"}))
        self.assertEqual(context["items"][0]["note"], "新备注")
        self.assertEqual(decode_tool(self.call("index_status", {"source_id": "fixture"}))["bookmarks"], 1)

    def test_bad_package_is_tool_error_without_silent_stale_success(self):
        self.ready()
        self.sync()
        self.section_path.write_text("{broken JSON", encoding="utf-8")
        response = self.call("search_bookmarks", {"source_id": "fixture"})
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("Invalid package file", decode_tool(response)["error"])
        old = self.call("search_bookmarks", {"source_id": "fixture", "refresh": False})
        self.assertFalse(old["result"]["isError"])
        self.assertEqual(decode_tool(old)["total"], 1)
        self.assertIn("Tool failed: search_bookmarks", self.stderr.getvalue())

    def test_unknown_tools_methods_and_invalid_arguments_never_execute(self):
        self.ready()
        self.assertEqual(self.call("execute_sql", {"sql": "DROP TABLE items"})["error"]["code"], -32602)
        self.assertEqual(self.server.handle(request("resources/list"))["error"]["code"], -32601)
        cases = [
            ("update_settings", {"changes": {"api_key": "not-supported"}}),
            ("update_settings", {"changes": {"archive": {"enabled": "false"}}}),
            ("sync_package", {"package_path": str(self.package), "command": "echo untrusted"}),
            ("search_bookmarks", {"source_id": "fixture", "sql": "SELECT * FROM items"}),
            ("search_bookmarks", {"source_id": "fixture", "limit": True}),
            ("search_bookmarks", {"source_id": "fixture", "limit": 1001}),
            ("search_bookmarks", {"source_id": "fixture", "targets": "示例公司甲"}),
            ("search_bookmarks", {"source_id": "fixture", "offset": -1}),
            ("search_bookmarks", {"source_id": "fixture", "refresh": "false"}),
            ("sync_package", {}),
            ("index_status", {"source_id": None}),
            ("search_web", {"targets": [{"target": "公司"}]}),
            ("search_web", {"targets": [{"target": "公司", "query": "公司官网", "command": "bad"}]}),
            ("search_web", {"targets": [{"target": "公司", "query": "公司官网"}] * 13}),
            ("fetch_web", {"urls": []}),
            ("search_providers", {"providers": ["exa", "exa"]}),
            ("search_providers", {"providers": ["arbitrary-server"]}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)
        self.assertFalse(self.db_path.exists())
        self.assertIsNone(self.server._providers)

    def test_lifecycle_invalid_rpc_and_notifications(self):
        self.assertEqual(self.server.handle(request("ping"))["result"], {})
        self.assertEqual(self.server.handle(request("tools/list"))["error"]["code"], -32002)
        bad = request("ping")
        bad["params"] = None
        self.assertEqual(self.server.handle(bad)["error"]["code"], -32602)
        self.assertEqual(self.server.handle([request("ping")])["error"]["code"], -32600)
        self.assertEqual(self.server.handle(request("ping", request_id=True))["error"]["code"], -32600)
        self.ready()
        notification = {"jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "sync_package", "arguments": {"package_path": str(self.package)}}}
        self.assertIsNone(self.server.handle(notification))
        self.assertFalse(self.db_path.exists())
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/unknown"}))
        self.assertEqual(self.server.handle(request("tools/list", {"cursor": "unknown"}))["error"]["code"], -32602)

    def test_web_dispatch_uses_lazy_provider_interface(self):
        calls = []

        class FakeProviders:
            def __init__(self, settings=None):
                calls.append(("init", settings.path))

            def describe(self, providers=None):
                calls.append(("describe", providers))
                return {"probe_performed": False, "providers": providers or ["exa", "parallel"]}

            def probe(self, providers=None):
                calls.append(("probe", providers))
                return {"probe_performed": True}

            def search(self, targets, providers=None, limit_per_target=5):
                calls.append(("search", targets, providers, limit_per_target))
                return {"targets": targets}

            def fetch(self, urls, provider="exa"):
                calls.append(("fetch", urls, provider))
                return {"urls": urls, "provider": provider}

        module = types.ModuleType("web_search")
        module.SearchProviders = FakeProviders
        self.ready()
        with mock.patch.dict(sys.modules, {"web_search": module}):
            self.assertFalse(decode_tool(self.call("search_providers"))["probe_performed"])
            self.assertTrue(decode_tool(self.call("search_providers", {"probe": True, "providers": ["exa"]}))["probe_performed"])
            targets = [{"target": "示例公司甲", "query": "示例公司甲 官方 API"}]
            self.assertFalse(self.call("search_web", {"targets": targets, "providers": ["parallel"], "limit_per_target": 3})["result"]["isError"])
            self.assertFalse(self.call("fetch_web", {"urls": ["https://example.test/"]})["result"]["isError"])
        self.assertEqual(calls, [("init", self.settings.path), ("describe", None), ("probe", ["exa"]),
            ("search", targets, ["parallel"], 3), ("fetch", ["https://example.test/"], "exa")])
        self.assertFalse(self.db_path.exists())

    def test_settings_and_fetch_archive_work_through_mcp_without_creating_index(self):
        self.ready()
        current = decode_tool(self.call("get_settings"))
        self.assertFalse(current["config_exists"])
        self.assertFalse(self.settings.path.exists())
        changed = self.call("update_settings", {"changes": {
            "search": {"providers": ["exa"]}, "archive": {"directory": str(self.base / "knowledge")},
            "fetch": {"max_characters": 20000}}})
        self.assertFalse(changed["result"]["isError"], changed)
        client = mock.Mock()
        client.list_tools.return_value = [{"name": "web_fetch_exa", "inputSchema": {
            "properties": {"urls": {}, "maxCharacters": {}}, "required": ["urls"]}}]
        client.call_tool.return_value = {"content": [{"type": "text",
            "text": "# Page\nURL: https://example.test/page\n\nActual page body"}]}
        with mock.patch("web_search.SearchProviders._client", return_value=client):
            fetched = decode_tool(self.call("fetch_web", {"urls": ["https://example.test/page"]}))
            self.assertEqual(fetched["archive"]["status"], "saved")
            self.assertEqual(Path(fetched["archive"]["pages"][0]["body_path"]).read_text(), "Actual page body")
            self.assertEqual(client.call_tool.call_args.args[1]["maxCharacters"], 20000)
            self.call("update_settings", {"changes": {"archive": {"enabled": False}}})
            disabled = decode_tool(self.call("fetch_web", {"urls": ["https://example.test/page"]}))
            self.assertEqual(disabled["archive"]["status"], "disabled")
        self.assertFalse(self.db_path.exists())

    def test_web_protocol_boundaries_match_provider_limits(self):
        self.ready()
        provider = mock.Mock()
        provider.search.return_value = {"ok": True}
        provider.fetch.return_value = {"ok": True}
        self.server._providers = provider
        targets = [{"target": "公" * 200, "query": "查" * 2000}]
        targets.extend({"target": "company-%s" % number, "query": "official website"} for number in range(11))
        for count in (1, 12):
            with self.subTest(accepted_targets=count):
                result = self.call("search_web", {"targets": targets[:count]})
                self.assertFalse(result["result"]["isError"])
        urls = ["https://example.test/%s" % number for number in range(8)]
        for count in (1, 8):
            with self.subTest(accepted_urls=count):
                result = self.call("fetch_web", {"urls": urls[:count]})
                self.assertFalse(result["result"]["isError"])
        invalid = [
            ("search_web", {"targets": []}),
            ("search_web", {"targets": targets + [{"target": "thirteenth", "query": "website"}]}),
            ("search_web", {"targets": [{"target": "公" * 201, "query": "website"}]}),
            ("search_web", {"targets": [{"target": "company", "query": "查" * 2001}]}),
            ("fetch_web", {"urls": []}),
            ("fetch_web", {"urls": urls + ["https://example.test/ninth"]}),
        ]
        for name, arguments in invalid:
            with self.subTest(rejected_tool=name, argument_count=len(next(iter(arguments.values())))):
                self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)
        # Invalid calls fail at the advertised protocol boundary, before a
        # provider can perform network work or return a less useful tool error.
        self.assertEqual(provider.search.call_count, 2)
        self.assertEqual(provider.fetch.call_count, 2)

    def test_line_transport_only_emits_json_and_recovers_from_parse_errors(self):
        messages = [initialize(), {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request("tools/list", request_id=2), request("ping", request_id="p"),
            request("tools/call", {"name": "sync_package", "arguments": {"package_path": "missing"}}, request_id=3)]
        stdin = io.StringIO("{broken\n" + "\n".join(json.dumps(value, ensure_ascii=False) for value in messages) + "\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        serve(self.db_path, stdin=stdin, stdout=stdout, stderr=stderr)
        rows = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["error"]["code"], -32700)
        self.assertEqual([row["id"] for row in rows], [None, 1, 2, "p", 3])
        self.assertTrue(rows[-1]["result"]["isError"])
        self.assertIn("Tool failed", stderr.getvalue())
        self.assertNotIn("bookmark-research MCP:", stdout.getvalue())

    def test_oversized_and_duplicate_key_messages_are_rejected(self):
        stdout = io.StringIO()
        with mock.patch("mcp_server.MAX_MESSAGE_CHARS", 64):
            serve(self.db_path, stdin=io.StringIO("x" * 65 + "\n"), stdout=stdout, stderr=self.stderr)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32700)
        stdout = io.StringIO()
        serve(self.db_path, stdin=io.StringIO('{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n'), stdout=stdout, stderr=self.stderr)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], -32700)

    def test_independent_packages_through_mcp_tools(self):
        from test_bookmark_index import make_package

        self.ready()
        self.sync()
        other_package = self.base / "AnotherPackage"
        make_package(other_package)
        report = decode_tool(self.call("sync_package", {"package_path": str(other_package), "source_id": "another-source"}))
        self.assertEqual(report["counts"]["bookmarks"], 5)
        self.assertEqual(report["counts"]["unique_urls"], 4)
        search = decode_tool(self.call("search_bookmarks", {"source_id": "another-source", "group_id": "group-one", "limit": 1}))
        self.assertEqual(search["total"], 2)
        self.assertEqual(len(search["results"]), 1)
        self.assertEqual(search["refresh"]["sync"]["changed_files"], 0)
        self.assertEqual(decode_tool(self.call("search_bookmarks", {"source_id": "fixture"}))["total"], 1)
        sources = decode_tool(self.call("index_status"))["sources"]
        self.assertEqual({source["source_id"] for source in sources}, {"fixture", "another-source"})


if __name__ == "__main__":
    unittest.main()
