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
        response = self.call("sync_package", {"package_path": str(self.package), "source_id": "fixture", "mode": "live"})
        self.assertFalse(response["result"]["isError"], response)
        return decode_tool(response)

    def test_initialization_discovery_and_lazy_database(self):
        response = self.ready()
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(response["result"]["capabilities"], {"tools": {}})
        listing = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual({tool["name"] for tool in listing}, {
            "sync_package", "source_history", "search_bookmarks", "get_context", "index_status",
            "search_web", "fetch_web", "search_providers", "get_settings", "update_settings",
            "research_start", "research_status", "research_search", "research_fetch",
            "research_source", "research_record", "research_finish", "research_inventory",
            "research_coverage", "research_import_evidence", "research_route", "research_services",
            "research_service_prepare", "research_service_start", "research_service_status",
            "research_service_result", "research_service_cancel", "research_service_attach",
            "research_service_import", "wiki_write", "wiki_get", "wiki_list", "wiki_search",
            "wiki_lint", "evaluate_research"})
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

    def test_research_lifecycle_through_advertised_mcp_tools(self):
        from research import ResearchSessions
        self.ready()
        engine = mock.Mock()
        engine.fetch.return_value = {"provider": "tavily", "urls": ["https://example.test/docs"],
            "tool": "tavily_extract", "request_arguments": {"urls": ["https://example.test/docs"]},
            "requested_max_characters": 12000, "retrieved_at": "2026-09-10T00:00:00Z",
            "result": {"structuredContent": {"results": [
                {"url": "https://example.test/docs", "title": "Docs", "raw_content": "Only search and extract are supported here."}]}}}
        self.server._research_sessions = ResearchSessions(self.base / "research", settings=self.settings, engine=engine)
        started = decode_tool(self.call("research_start", {"brief": "Check supported capabilities", "providers": ["tavily"],
            "questions": [{"id": "q1", "question": "What is supported?"}]}))
        research_id = started["research_id"]
        self.assertFalse(self.db_path.exists())
        self.assertEqual(started["status"], "active")
        failed = self.call("research_finish", {"research_id": research_id, "summary": "No evidence yet"})
        self.assertTrue(failed["result"]["isError"])
        fetched = decode_tool(self.call("research_fetch", {"research_id": research_id, "operation_id": "read-1",
            "question_id": "q1", "urls": ["https://example.test/docs"]}))
        self.assertEqual(fetched["sources"][0]["id"], "s1")
        read = decode_tool(self.call("research_source", {"research_id": research_id, "source_id": "s1"}))
        self.assertEqual(read["text"], "Only search and extract are supported here.")
        claim = self.call("research_record", {"research_id": research_id, "entry": {"kind": "claim", "question_id": "q1",
            "statement": "Search and extract are available.", "citations": [{"source_id": "s1", "quote": read["text"]}]}})
        self.assertFalse(claim["result"]["isError"])
        answer = self.call("research_record", {"research_id": research_id, "entry": {"kind": "answer", "question_id": "q1",
            "answer": "Search and extract.", "claim_ids": ["c1"]}})
        self.assertFalse(answer["result"]["isError"])
        finished = decode_tool(self.call("research_finish", {"research_id": research_id, "summary": "Capabilities checked."}))
        self.assertEqual(finished["status"], "completed")
        self.assertTrue(Path(finished["artifacts"]["report"]).is_file())
        state = decode_tool(self.call("research_status", {"research_id": research_id}))
        self.assertEqual(state["usage"]["fetch_calls"], 1)
        self.assertFalse(self.db_path.exists())

    def test_classified_provider_failures_set_mcp_error_flag(self):
        self.ready()
        self.server._providers = mock.Mock()
        self.server._research_sessions = mock.Mock()
        cases = [
            ("fetch_web", self.server._providers.fetch, {"urls": ["https://example.test/docs"]}),
            ("research_fetch", self.server._research_sessions.fetch,
             {"research_id": "r-1234567890abcdef", "operation_id": "read", "question_id": "q1",
              "urls": ["https://example.test/docs"]}),
            ("research_search", self.server._research_sessions.search,
             {"research_id": "r-1234567890abcdef", "operation_id": "find",
              "queries": [{"question_id": "q1", "query": "docs"}]}),
        ]
        for name, method, arguments in cases:
            for status in ("error", "partial"):
                with self.subTest(tool=name, status=status):
                    method.return_value = {"status": status, "error_kind": "authentication", "usage": {"tool_calls": 0}}
                    response = self.call(name, arguments)
                    self.assertEqual(response["result"]["isError"], status == "error")
                    self.assertEqual(decode_tool(response), method.return_value)
        for successes in (0, 1):
            self.server._providers.search.return_value = {"successful_provider_count": successes, "batches": []}
            response = self.call("search_web", {"targets": [{"target": "docs", "query": "official docs"}]})
            self.assertEqual(response["result"]["isError"], successes == 0)

    def test_large_research_status_pages_and_finish_preserve_full_evidence(self):
        from mcp_server import MAX_RESULT_CHARS
        from research import ResearchSessions
        self.ready()
        quote = "Synthetic long citation: " + "x" * 3972
        self.assertLessEqual(len(quote), 4000)
        engine = mock.Mock()
        engine.fetch.return_value = {"provider": "exa", "urls": ["https://example.test/long"],
            "tool": "web_fetch_exa", "request_arguments": {"urls": ["https://example.test/long"]},
            "requested_max_characters": 12000, "retrieved_at": "2026-09-10T00:00:00Z",
            "result": {"structuredContent": {"results": [
                {"url": "https://example.test/long", "title": "Synthetic long source", "text": quote}]}}}
        sessions = ResearchSessions(self.base / "research", settings=self.settings, engine=engine)
        self.server._research_sessions = sessions
        research_id = sessions.start("Large evidence report", [{"id": "q1", "question": "What was saved?"}])["research_id"]
        sessions.fetch(research_id, "read", "q1", ["https://example.test/long"])
        for number in range(45):
            sessions.record(research_id, {"kind": "claim", "question_id": "q1", "statement": "Finding %s" % number,
                "citations": [{"source_id": "s1", "quote": quote} for _ in range(12)]})
        sessions.record(research_id, {"kind": "answer", "question_id": "q1", "answer": "Evidence retained.", "claim_ids": ["c45"]})
        full_state = (sessions.directory / research_id / "state.json").read_text()
        self.assertGreater(len(full_state), MAX_RESULT_CHARS)

        response = self.call("research_status", {"research_id": research_id})
        self.assertFalse(response["result"]["isError"])
        overview = decode_tool(response)
        self.assertEqual(overview["counts"]["claims"], 45)
        self.assertEqual(len(overview["claims"]), 20)
        self.assertTrue(overview["claims"][0]["citations"][0]["quote_truncated"])
        claims, offset = [], 0
        while offset is not None:
            response = self.call("research_status", {"research_id": research_id, "section": "claims", "offset": offset, "limit": 20})
            self.assertFalse(response["result"]["isError"])
            page = decode_tool(response)
            claims.extend(page["items"])
            if page["next_offset"] is not None:
                self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual([claim["id"] for claim in claims], ["c%s" % number for number in range(1, 46)])
        self.assertTrue(all(citation["quote"] == quote for claim in claims for citation in claim["citations"]))

        response = self.call("research_finish", {"research_id": research_id, "summary": "All saved citations are available."})
        self.assertFalse(response["result"]["isError"])
        finished = decode_tool(response)
        self.assertEqual(finished["status"], "completed")
        manifest = json.loads(Path(finished["artifacts"]["sources"]).read_text())
        self.assertEqual(manifest["claims"], claims)
        report = Path(finished["artifacts"]["report"]).read_text()
        self.assertIn("### Claim c45", report)
        self.assertIn(quote, report)

    def test_incomplete_research_resumes_through_advertised_record_tool(self):
        from research import ResearchSessions
        self.ready()
        self.server._research_sessions = ResearchSessions(self.base / "research", settings=self.settings)
        started = decode_tool(self.call("research_start", {"brief": "Resume a report", "questions": [{"id": "q1", "question": "What is missing?"}]}))
        research_id = started["research_id"]
        self.call("research_finish", {"research_id": research_id, "summary": "No evidence yet.", "status": "incomplete"})
        response = self.call("research_record", {"research_id": research_id,
            "entry": {"kind": "resume", "text": "Continue from the saved question."}})
        self.assertFalse(response["result"]["isError"])
        resumed = decode_tool(response)
        self.assertTrue(Path(resumed["recorded"]["previous_artifacts"]["report"]).is_file())
        self.assertEqual(decode_tool(self.call("research_status", {"research_id": research_id}))["status"], "active")

    def test_research_invalid_schema_is_rejected_before_writes(self):
        self.ready()
        invalid = [
            ("research_start", {"brief": "Test", "questions": []}),
            ("research_start", {"brief": "Test", "questions": [{"id": "q", "question": "Q?"}], "budget": {"max_fetch_calls": True}}),
            ("research_fetch", {"research_id": "r-1234567890abcdef", "question_id": "q", "urls": ["https://example.test"]}),
            ("research_record", {"research_id": "r-1234567890abcdef", "entry": {"kind": "exec", "command": "false"}}),
        ]
        for name, arguments in invalid:
            with self.subTest(name=name):
                self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)
        self.assertIsNone(self.server._research_sessions)

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
