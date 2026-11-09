"""Protocol and integration tests for the bounded stdio MCP tools server."""

import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_server import (DEPRECATED_TOOL_TARGETS, PROTOCOLS, StdioMcpServer, TOOL_SCHEMAS,
                        _legacy_compatibility_expired, serve)
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
        self.release_patch = mock.patch("mcp_server.release_version", return_value="0.6.2")
        self.release_patch.start()
        self.addCleanup(self.release_patch.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="bookmark-mcp-test-")
        self.base = Path(self.temp.name)
        self.db_path = self.base / "index.sqlite3"
        self.stderr = io.StringIO()
        self.settings = Settings(self.base / "settings.json")
        self.settings.update({"tool_scope_preset": "all"})
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
            "sync_package", "source_history", "locate", "search_bookmarks", "lookup_url", "traverse_graph", "get_context", "plan_research", "discovery_bundle", "index_status",
            "source_remove", "source_merge",
            "search_web", "search", "agentic_search", "fetch_web", "fetch", "search_providers", "search_archive", "merge_search_results", "ingest", "get_settings", "update_settings", "research_readiness",
            "research_start", "research_status", "research_search", "research_fetch",
            "research_source", "research_record", "research_finish", "research_inventory",
            "research_coverage", "research_import_evidence", "research_route", "research_services",
            "research_service_prepare", "research_service_start", "research_service_status",
            "research_service_result", "research_service_cancel", "research_service_attach", "read", "walk", "save",
            "research_service_import", "spawn", "job", "health", "wiki_write", "wiki_get", "wiki_list", "wiki_search",
            "wiki_lint", "wiki_acknowledge", "wiki_refresh", "wiki_work", "wiki_compile"})
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False for tool in listing))
        tools = {tool["name"]: tool for tool in listing}
        plan = tools["plan_research"]
        self.assertEqual(plan["inputSchema"]["properties"]["max_cards"]["maximum"], 3)
        self.assertEqual(plan["inputSchema"]["properties"]["max_urls"]["maximum"], 8)
        self.assertIn("max_cards accepts 1–3", plan["description"])
        self.assertIn("max_urls accepts 1–8", plan["description"])
        search_description = tools["search_web"]["description"]
        self.assertIn("10-second default search.deadline_seconds", search_description)
        self.assertIn("quota_exhausted providers enter cooldown", search_description)
        self.assertFalse(self.db_path.exists())
        self.assertIsNone(self.server._providers)
        self.assertEqual(self.server.handle(request("ping"))["result"], {})

    def test_custom_agentic_search_uses_separate_configured_answer_channel(self):
        self.ready()
        self.settings.update({"custom_agentic": {"enabled": True, "base_url": "https://gateway.example/v1",
            "model": "search-model", "api_mode": "responses", "search_mode": "native"}})
        expected = {"provider": "custom", "model": "search-model", "answer": "Answer", "citations": []}
        with mock.patch("grok_search.OpenAICompatibleAgenticSearch.search", return_value=expected) as search:
            response = self.call("agentic_search", {"provider": "custom", "query": "question"})
        self.assertFalse(response["result"]["isError"], response)
        self.assertEqual(decode_tool(response), expected)
        search.assert_called_once_with(query="question")

    def test_p0b_primitive_aliases_are_discoverable_and_health_is_bounded(self):
        self.ready()
        listing = self.server.handle(request("tools/list"))["result"]["tools"]
        names = {tool["name"] for tool in listing}
        self.assertTrue({"search", "fetch", "ingest", "spawn", "job", "health"} <= names)
        health = decode_tool(self.call("health"))
        self.assertEqual("ok", health["status"])
        self.assertLessEqual(len(json.dumps(health, ensure_ascii=False)), 200)
        self.assertIn("sources", health)

    def test_health_reports_observed_host_search_only_when_asked(self):
        self.ready()
        bounded = decode_tool(self.call("health"))
        self.assertNotIn("host_search", bounded)
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False)), 200)
        host_only = decode_tool(self.call("health", {"host": "codex"}))
        self.assertNotIn("host_search", host_only)
        report = decode_tool(self.call("health", {"host": "codex", "observed_tools": ["tools.web__run"]}))
        self.assertEqual("tools.web__run", report["host_search"]["tool"])
        self.assertEqual("ingest", report["host_search"]["backflow_tool"])
        absent = decode_tool(self.call("health", {"host": "codex", "observed_tools": ["mcp__other__web_search"]}))
        self.assertFalse(absent["host_search"]["available"])

    def test_disabled_wiki_hides_tools_and_rejects_wiki_scope_calls(self):
        self.ready()
        changed = self.call("update_settings", {"changes": {"wiki": {"enabled": False}}})
        self.assertFalse(changed["result"]["isError"], changed)
        listing = {tool["name"] for tool in self.server.handle(request("tools/list"))["result"]["tools"]}
        self.assertNotIn("save", listing)
        for name in ("wiki_get", "wiki_lint", "wiki_compile"):
            self.assertNotIn(name, listing)
        self.assertIn("locate", listing)
        self.assertIn("read", listing)
        for name, arguments in (("read", {"page_id": "alpha"}),
                                ("locate", {"in": ["wiki"], "text": "alpha"}),
                                ("wiki_compile", {"action": "plan", "source_id": "fixture"})):
            response = self.call(name, arguments)
            self.assertTrue(response["result"]["isError"], response)
            self.assertIn("Wiki is disabled", json.dumps(response, ensure_ascii=False))
        self.sync()
        planned = decode_tool(self.call("plan_research", {"question": "示例", "source_id": "fixture"}))
        self.assertEqual([], planned.get("wiki", []))

    def test_wiki_compile_plans_and_reports_status_without_writing_pages(self):
        self.document["items"].append({"id": "gap-only", "sectionId": "temp-section-A-1",
            "type": "bookmark", "title": "Gap fixture", "url": "https://mcp-gap.test/only"})
        self.write_document()
        self.ready()
        self.sync()
        plan = decode_tool(self.call("wiki_compile", {"action": "plan", "source_id": "fixture",
            "max_pages": 4, "min_cluster_size": 1, "include_covered": True}))
        self.assertTrue(plan["plan_id"])
        self.assertEqual("fixture", plan["source_id"])
        before = len(self.server._wiki().list(limit=100)["pages"])
        url = next(item["url"] for cluster in plan["clusters"] for item in cluster["items"]
                   if item["url"] == "https://mcp-gap.test/only")
        gap = decode_tool(self.call("wiki_compile", {"action": "gap", "plan_id": plan["plan_id"],
            "urls": [url], "reason": "provider returned no content"}))
        self.assertEqual(1, gap["recorded"])
        status = decode_tool(self.call("wiki_compile", {"action": "status", "plan_id": plan["plan_id"]}))
        self.assertEqual(plan["plan_id"], status["plan_id"])
        self.assertGreaterEqual(status["summary"]["gap_items"], 1)
        self.assertEqual(before, len(self.server._wiki().list(limit=100)["pages"]))

    def test_ingest_alias_enforces_inline_batch_budget(self):
        self.ready()
        batches = [{"target": "q", "provider": "host", "query": "q", "status": "error", "error": "x"}
                   for _ in range(17)]
        response = self.call("ingest", {"batches": batches})
        self.assertEqual(-32602, response["error"]["code"])
        self.assertIn("batches", response["error"]["message"])



    def test_quick_tool_scope_preset_exposes_the_everyday_surface(self):
        self.ready()
        changed = self.call("update_settings", {"changes": {"tool_scope_preset": "quick"}})
        self.assertIn("result", changed)
        self.assertFalse(changed["result"]["isError"], changed)
        listing = self.server.handle(request("tools/list"))["result"]["tools"]
        names = {tool["name"] for tool in listing}
        self.assertEqual(set(Settings.QUICK_TOOLS), names)
        self.assertNotIn("research_source", names)
        self.assertEqual({"locate", "read", "walk", "search", "fetch", "ingest", "save", "spawn", "job", "health"}, names)
        self.assertNotIn("search_bookmarks", names)
        self.assertNotIn("search_web", names)
        self.sync()
        compatible = self.call("get_context", {"source_id": "fixture", "item_id": "temp-one",
                                                "refresh": False})
        self.assertFalse(compatible["result"]["isError"], compatible)

    def test_replaced_legacy_tools_are_labeled_but_remain_in_all_catalog(self):
        self.ready()
        listing = {tool["name"]: tool for tool in self.server.handle(request("tools/list"))["result"]["tools"]}
        for old, replacement in (("search_bookmarks", "locate"), ("get_context", "read"),
                                 ("traverse_graph", "walk"), ("search_web", "search"),
                                 ("fetch_web", "fetch"), ("merge_search_results", "ingest"),
                                 ("wiki_write", "save"), ("wiki_get", "read"),
                                 ("research_source", "read"), ("research_service_start", "spawn")):
            self.assertIn(old, listing)
            self.assertTrue(listing[old]["description"].startswith("[deprecated→%s]" % replacement))

    def test_legacy_catalog_and_calls_expire_at_070(self):
        self.assertFalse(_legacy_compatibility_expired("0.8.0-rc.1"))
        self.assertTrue(_legacy_compatibility_expired("0.8.0"))
        self.assertTrue(_legacy_compatibility_expired("0.8.1"))
        self.assertFalse(_legacy_compatibility_expired("0+unknown"))

        self.ready()
        with mock.patch("mcp_server.release_version", return_value="0.8.0"):
            listing = {tool["name"] for tool in self.server.handle(request("tools/list"))["result"]["tools"]}
            self.assertFalse(DEPRECATED_TOOL_TARGETS.keys() & listing)
            self.assertTrue(set(Settings.QUICK_TOOLS) <= listing)
            removed = self.call("get_context", {"source_id": "fixture", "refresh": False})
        self.assertEqual(-32602, removed["error"]["code"])
        self.assertIn("Unknown tool: get_context", removed["error"]["message"])

    def test_explicit_tool_scope_narrows_catalog_and_rejects_hidden_calls(self):
        self.ready()
        changed = self.call("update_settings", {"changes": {"tool_scope": ["get_context", "plan_research"]}})
        self.assertIn("result", changed, changed)
        self.assertFalse(changed["result"]["isError"], changed)
        listing = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual(["get_context", "plan_research"], [tool["name"] for tool in listing])
        hidden = self.call("fetch_web", {"urls": ["https://example.test/"]})
        self.assertEqual(-32602, hidden["error"]["code"])
        self.assertIn("tool_scope", hidden["error"]["message"])

    def test_environment_tool_scope_overrides_the_saved_preference(self):
        self.ready()
        self.call("update_settings", {"changes": {"tool_scope": ["get_context"]}})
        with mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_TOOL_SCOPE": "plan_research, search_web"}):
            listing = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual(["plan_research", "search_web"], [tool["name"] for tool in listing])

    def test_all_protocols_and_version_specific_content(self):
        for protocol in PROTOCOLS:
            protocol_settings = Settings(self.base / (protocol + ".json"))
            protocol_settings.update({"tool_scope_preset": "all"})
            server = StdioMcpServer(self.base / (protocol + ".sqlite3"), stderr=self.stderr,
                                    settings=protocol_settings)
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

    def test_compact_search_keeps_full_default_and_live_source_state(self):
        self.ready()
        self.sync()
        self.server._source_watcher.close()
        arguments = {"source_id": "fixture", "targets": ["docs"], "refresh": False}
        full = decode_tool(self.call("search_bookmarks", arguments))
        explicit_full = decode_tool(self.call("search_bookmarks", {**arguments, "compact": False}))
        self.assertEqual(full, explicit_full)
        self.assertIn("raw_json", full["results"][0])
        compact = decode_tool(self.call("search_bookmarks", {**arguments, "compact": True}))
        self.assertEqual("bookmark-search-v1", compact["_compact"]["format"])
        self.assertNotIn("results", compact)
        row = compact["rows"][compact["result_refs"][0]]
        self.assertEqual("temp-one", row["item_id"])
        self.assertEqual(full["results"][0]["url"], row["url"])
        self.assertEqual(compact["result_refs"], compact["targets"][0]["result_refs"])
        for field in ("counts", "source", "refresh", "query_scope", "next_offset"):
            self.assertEqual(full[field], compact[field])
        self.document["items"][0]["note"] = "fresh compact evidence"
        self.write_document()
        refreshed = decode_tool(self.call("search_bookmarks", {
            "source_id": "fixture", "targets": ["fresh compact evidence"], "compact": True}))
        self.assertTrue(refreshed["refresh"]["performed"])
        current = refreshed["rows"][refreshed["result_refs"][0]]
        self.assertEqual("fresh compact evidence", current["note"])
        context = decode_tool(self.call("get_context", {
            "source_id": "fixture", "item_id": "temp-one", "refresh": False}))
        self.assertIn("raw_json", context["items"][0])

    def test_search_bookmarks_combines_metadata_filters_and_date_sort(self):
        self.ready()
        self.document["items"].extend([
            {"id": "tagged", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "Tagged entry", "url": "https://example.test/tagged", "tags": [{"color": "green", "text": "keep"}]},
            {"id": "plain", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "Plain entry", "url": "https://example.test/plain"},
        ])
        self.write_document()
        self.sync()

        response = self.call("search_bookmarks", {"source_id": "fixture", "has_note": True,
            "has_tags": True, "metadata_match": "any", "sort_by": "added_at_desc",
            "compact": True, "refresh": False})
        self.assertFalse(response["result"]["isError"], response)
        result = decode_tool(response)
        rows = [result["rows"][key] for key in result["result_refs"]]
        self.assertEqual({row["item_id"] for row in rows}, {"temp-one", "tagged"})
        self.assertEqual(result["query_scope"]["metadata_match"], "any")
        self.assertEqual(result["query_scope"]["sort_by"], "added_at_desc")

    def test_local_queries_return_source_state_without_full_index_statistics(self):
        self.ready()
        self.sync()
        self.server._source_watcher.close()
        expected = decode_tool(self.call("index_status", {"source_id": "fixture"}))["source"]
        with mock.patch.object(self.server._local(), "status", side_effect=AssertionError(
                "Local queries must not repeat full index statistics")):
            for name in ("search_bookmarks", "get_context"):
                with self.subTest(tool=name):
                    response = self.call(name, {"source_id": "fixture", "refresh": False})
                    self.assertFalse(response["result"]["isError"], response)
                    self.assertEqual(decode_tool(response)["source"], expected)

    def test_unknown_tools_methods_and_invalid_arguments_never_execute(self):
        self.ready()
        self.assertEqual(self.call("execute_sql", {"sql": "DROP TABLE items"})["error"]["code"], -32602)
        self.assertEqual(self.server.handle(request("resources/list"))["error"]["code"], -32601)
        cases = [
            ("search_bookmarks", {"source_id": "fixture", "compact": "false"}),
            ("search_bookmarks", {"source_id": "fixture", "compact": 1}),
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
            ("search_web", {"targets": [123]}),
            ("update_settings", {"changes": {"server": {"network_workers": 17}}}),
            ("update_settings", {"changes": {"fetch": {"reuse_seconds": 86401}}}),
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
        self.settings.path.unlink()
        scope = mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_TOOL_SCOPE": ""})
        scope.start()
        self.addCleanup(scope.stop)
        self.ready()
        current = decode_tool(self.call("get_settings"))
        self.assertFalse(current["config_exists"])
        self.assertFalse(self.settings.path.exists())

        changed = self.call("update_settings", {"changes": {
            "search": {"providers": ["exa"], "cache_seconds": 60},
            "archive": {"directory": str(self.base / "knowledge")},
            "fetch": {"max_characters": 20000, "reuse_seconds": 900},
            "server": {"network_workers": 2, "max_pending_calls": 4}}})
        self.assertFalse(changed["result"]["isError"], changed)
        client = mock.Mock()
        client.list_tools.return_value = [{"name": "web_fetch_exa", "inputSchema": {
            "properties": {"urls": {}, "maxCharacters": {}}, "required": ["urls"]}}]
        client.call_tool.return_value = {"content": [{"type": "text",
            "text": "# Page\nURL: https://example.test/page\n\nActual page body"}]}
        with mock.patch("web_search.SearchProviders._client", return_value=client):
            fetched = decode_tool(self.call("fetch_web", {"urls": ["https://example.test/page"]}))
            self.assertEqual(fetched["archive"]["status"], "saved")
            self.assertEqual(fetched["pages"][0]["text"], "Actual page body")
            self.assertNotIn("result", fetched)
            self.assertEqual(Path(fetched["archive"]["pages"][0]["body_path"]).read_text(), "Actual page body")
            self.assertEqual(client.call_tool.call_args.args[1]["maxCharacters"], 20000)
            raw = decode_tool(self.call("fetch_web", {"urls": ["https://example.test/page"], "raw": True}))
            self.assertEqual(raw["result"], client.call_tool.return_value)
            self.assertNotIn("pages", raw)
            self.call("update_settings", {"changes": {"archive": {"enabled": False}}})
            disabled = decode_tool(self.call("fetch_web", {"urls": ["https://example.test/page"]}))
            self.assertEqual(disabled["archive"]["status"], "disabled")
        self.assertFalse(self.db_path.exists())

    def test_search_archive_finds_saved_page_text_without_network(self):
        from archive import SourceArchive
        data = self.base / "data"
        with mock.patch.dict("os.environ", {"BOOKMARK_RESEARCH_DATA_DIR": str(data)}):
            self.ready()
            store = SourceArchive(data / "knowledge")
            for _ in range(2):
                store.save({"provider": "exa", "tool": "web_fetch_exa", "urls": ["https://example.test/page"],
                            "result": {"structuredContent": {"url": "https://example.test/page", "text": "Saved archive marker text"}},
                            "retrieved_at": "2026-09-29T00:00:00+00:00", "request_arguments": {}, "requested_max_characters": 12000})
            with mock.patch("web_search.SearchProviders._client", side_effect=AssertionError("no network")):
                response = self.call("search_archive", {"query": "archive marker", "url": "example.test"})
            self.assertFalse(response["result"]["isError"], response)
            result = decode_tool(response)
            self.assertEqual(result["total"], 1)
            self.assertEqual([row["kind"] for row in result["results"][0]["occurrences"]], ["archive", "archive"])
            self.assertEqual(result["indexed"]["documents"], 1)
            self.assertTrue((data / "raw-library.sqlite3").is_file())
            self.assertEqual(decode_tool(self.call("search_archive", {"query": "marker", "url": "other.test"}))["total"], 0)
            self.assertEqual(self.call("search_archive", {"query": "x" * 501})["error"]["code"], -32602)
            self.assertEqual(self.call("search_archive", {"query": "marker", "limit": 51})["error"]["code"], -32602)

    def test_readiness_is_available_without_creating_index_or_running_research(self):
        self.ready()
        result = decode_tool(self.call("research_readiness", {"offline": True, "providers": ["exa"],
                                                             "host": "claude_code", "observed_tools": []}))
        self.assertTrue(result["offline_ready"])
        self.assertFalse(result["network_checked"])
        self.assertEqual(result["research_jobs_started"], 0)
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
        # Plain strings are shorthand targets accepted alongside objects.
        self.assertFalse(self.call("search_web", {"targets": ["plain query string"]})["result"]["isError"])
        urls = ["https://example.test/%s" % number for number in range(16)]
        for count in (1, 16):
            with self.subTest(accepted_urls=count):
                result = self.call("fetch_web", {"urls": urls[:count]})
                self.assertFalse(result["result"]["isError"])
        invalid = [
            ("search_web", {"targets": []}),
            ("search_web", {"targets": targets + [{"target": "thirteenth", "query": "website"}]}),
            ("search_web", {"targets": [{"target": "公" * 201, "query": "website"}]}),
            ("search_web", {"targets": [{"target": "company", "query": "查" * 2001}]}),
            ("search_web", {"targets": ["查" * 2001]}),
            ("fetch_web", {"urls": []}),
            ("fetch_web", {"urls": urls + ["https://example.test/extra"]}),
        ]
        for name, arguments in invalid:
            with self.subTest(rejected_tool=name, argument_count=len(next(iter(arguments.values())))):
                self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)
        # Invalid calls fail at the advertised protocol boundary, before a
        # provider can perform network work or return a less useful tool error.
        self.assertEqual(provider.search.call_count, 3)
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
        primitive_read = decode_tool(self.call("read", {"research_id": research_id,
                                                          "evidence_source_id": "s1"}))
        self.assertEqual(read["text"], primitive_read["text"])
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

    def test_research_start_accepts_url_lists_without_canvas_registration(self):
        from research import ResearchSessions
        self.ready()
        self.server._research_sessions = ResearchSessions(self.base / "research", settings=self.settings, db_path=self.db_path)
        urls = ["https://example.test/first", "https://example.test/second", "https://example.test/first"]
        started = decode_tool(self.call("research_start", {"brief": "Read all my links", "urls": urls,
            "questions": [{"id": "q1", "question": "What do these sources say?"}]}))
        self.assertEqual(started["source_scope"]["input_url_count"], 2)
        self.assertEqual(started["source_scope"]["input_instance_count"], 3)
        inventory = decode_tool(self.call("research_inventory", {"research_id": started["research_id"]}))
        self.assertEqual({row["original_url"] for row in inventory["items"]}, set(urls))
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
            ("research_record", {"research_id": "r-1234567890abcdef", "entries": []}),
            ("research_record", {"research_id": "r-1234567890abcdef", "entries": [{"kind": "resume", "text": "Continue"}]}),
            ("research_record", {"research_id": "r-1234567890abcdef", "entries": [{"kind": "gap"}] * 51}),
        ]
        for name, arguments in invalid:
            with self.subTest(name=name):
                self.assertEqual(self.call(name, arguments)["error"]["code"], -32602)
        self.assertIsNone(self.server._research_sessions)

    def test_record_batch_through_mcp_returns_ids_and_replays_without_new_events(self):
        from research import ResearchSessions
        self.ready()
        self.server._research_sessions = ResearchSessions(self.base / "research", settings=self.settings)
        research_id = decode_tool(self.call("research_start", {"brief": "Batch protocol", "questions": [
            {"id": "q1", "question": "What is supported?"}]}))["research_id"]
        self.call("research_import_evidence", {"research_id": research_id, "operation_id": "import-1", "question_id": "q1",
            "url": "https://example.test/docs", "text": "The service supports fetch.", "provenance": {"kind": "page"}})
        arguments = {"research_id": research_id, "batch_id": "read-group-1", "entries": [
            {"kind": "source_review", "source_id": "s1", "verdict": "accepted", "text": "Page identity checked."},
            {"kind": "claim", "question_id": "q1", "statement": "Fetch is supported.",
             "citations": [{"source_id": "s1", "quote": "The service supports fetch."}]}]}
        first = decode_tool(self.call("research_record", arguments))
        self.assertEqual(first["count"], 2)
        self.assertEqual([row["id"] for row in first["results"]], ["s1", "c1"])
        self.assertNotIn("citations", json.dumps(first))
        self.assertEqual(decode_tool(self.call("research_record", arguments)), {**first, "replayed": True})
        state = decode_tool(self.call("research_status", {"research_id": research_id, "section": "events"}))
        self.assertEqual(state["total"], 2)

    def test_line_transport_only_emits_json_and_recovers_from_parse_errors(self):
        messages = [initialize(), {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request("tools/list", request_id=2), request("ping", request_id="p"),
            request("tools/call", {"name": "sync_package", "arguments": {"package_path": "missing"}}, request_id=3)]
        stdin = io.StringIO("{broken\n" + "\n".join(json.dumps(value, ensure_ascii=False) for value in messages) + "\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        serve(self.db_path, stdin=stdin, stdout=stdout, stderr=stderr,
              settings=self.settings)
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

    def test_lookup_url_and_traverse_graph_and_search_score(self):
        from test_bookmark_index import make_package

        self.ready()
        pkg = self.base / "Pkg"
        make_package(pkg)
        self.call("sync_package", {"package_path": str(pkg), "source_id": "src1"})

        # 1. lookup_url tool call
        lookup = decode_tool(self.call("lookup_url", {"url": "https://example.test/alpha"}))
        self.assertEqual(lookup["total_instances"], 2)
        self.assertEqual(lookup["unique_sources"], 1)

        # 2. traverse_graph tool call
        traverse = decode_tool(self.call("traverse_graph", {"source_id": "src1", "section": "A", "max_depth": 2}))
        self.assertIn("group-one", {n["node_id"] for n in traverse["nodes"]})
        self.assertIn("temp-section-A-1", {n["node_id"] for n in traverse["nodes"]})

        # 3. search_bookmarks with score=true
        scored = decode_tool(self.call("search_bookmarks", {"source_id": "src1", "targets": ["示例"], "score": True}))
        self.assertEqual(scored["score_mode"], "hint")
        self.assertTrue(len(scored["results"]) > 0)
        self.assertIn("score", scored["results"][0])

    def test_locate_canvas_returns_index_why_and_source_version(self):
        self.ready()
        self.sync()

        located = decode_tool(self.call("locate", {
            "text": "示例公司甲", "in": ["canvas"], "source_id": "fixture", "refresh": False}))
        self.assertEqual(["canvas"], located["in"])
        self.assertEqual(1, located["total"])
        hit = located["hits"][0]
        self.assertEqual("canvas", hit["source_kind"])
        self.assertEqual("bookmark_instance", hit["evidence_kind"])
        self.assertEqual("fixture", hit["source_id"])
        self.assertTrue(hit["version_id"])
        self.assertEqual(["示例", "公司", "司甲"], hit["why"]["terms"])
        self.assertIn("title", hit["why"]["fields"])
        self.assertEqual(140, hit["why"]["field_weights"]["title"])
        self.assertEqual(located["match_mode"], hit["why"]["match_mode"])
        self.assertLessEqual(len(hit["ref"]), 8)
        read = decode_tool(self.call("read", {"ref": hit["ref"], "refresh": False}))
        self.assertEqual("temp-one", read["items"][0]["item_id"])
        self.assertEqual("fixture", read["source"]["source_id"])
        self.assertEqual(hit["version_id"], read["source"]["version_id"])
        self.assertTrue(read["v"].startswith("v-"))
        repeated = decode_tool(self.call("read", {"ref": hit["ref"], "refresh": False}))
        self.assertEqual(read["v"], repeated["v"])
        self.assertEqual(read["source"]["source_id"], repeated["source"]["source_id"])
        self.assertEqual({"source_id", "version_id"}, set(repeated["source"]))
        self.assertLess(len(json.dumps(repeated, ensure_ascii=False)),
                        len(json.dumps(read, ensure_ascii=False)))
        self.assertLessEqual(len(read["v"]), 8)
        expanded = decode_tool(self.call("read", {"v": read["v"]}))
        self.assertEqual(hit["version_id"], expanded["source"]["version_id"])
        self.assertGreater(len(expanded["source"]), len(repeated["source"]))
        walked = decode_tool(self.call("walk", {"ref": hit["ref"], "refresh": False}))
        self.assertIn("No matching canvas nodes", walked.get("error", ""))
        self.assertEqual([], located["candidates"])

        self.document["items"].append({"id": "three-d", "sectionId": "temp-section-A-1",
            "type": "bookmark", "title": "3D 工具", "url": "https://example.test/3d",
            "note": "Note"})
        self.document["items"].append({"id": "two-d", "sectionId": "temp-section-A-1",
            "type": "bookmark", "title": "2D 工具", "url": "https://example.test/2d",
            "tags": [{"text": "vision", "color": "blue"}]})
        self.write_document()
        self.sync()
        phrase = decode_tool(self.call("locate", {
            "text": "3D 2D 英文名字 带 Note", "in": ["canvas"], "source_id": "fixture"}))
        self.assertEqual(1, phrase["total"])
        self.assertEqual("3D 工具", phrase["hits"][0]["title"])
        self.assertNotIn("note", phrase["hits"][0]["why"]["fields"])
        self.assertEqual(phrase["match_mode"], phrase["hits"][0]["why"]["match_mode"])
        self.assertEqual({"has_note": True}, phrase["filters"])

        explicit_filter = decode_tool(self.call("locate", {
            "text": "3D 2D", "in": ["canvas"], "source_id": "fixture",
            "has_note": True, "refresh": False}))
        self.assertEqual(1, explicit_filter["total"])
        self.assertEqual("3D 工具", explicit_filter["hits"][0]["title"])
        self.assertEqual("1 hit with title+note; stop if it matches", explicit_filter["next"])

        tag_filter = decode_tool(self.call("locate", {
            "text": "3D 2D", "in": ["canvas"], "source_id": "fixture",
            "has_tags": True, "refresh": False}))
        self.assertEqual(1, tag_filter["total"])
        self.assertEqual("2D 工具", tag_filter["hits"][0]["title"])

        chinese_digit = decode_tool(self.call("locate", {
            "text": "三D/二D", "in": ["canvas"], "source_id": "fixture", "refresh": False}))
        self.assertGreaterEqual(chinese_digit["total"], 2)
        self.assertIn("3D", chinese_digit["hits"][0]["why"]["terms"])

        exact = decode_tool(self.call("locate", {
            "url": "https://example.test/docs", "in": ["canvas"], "source_id": "fixture", "refresh": False}))
        self.assertEqual(1, exact["total"])
        self.assertEqual({"url"}, set(exact["hits"][0]["why"]["fields"]))
        self.assertEqual("exact", exact["hits"][0]["why"]["match_mode"])
        self.assertEqual(exact["match_mode"], exact["hits"][0]["why"]["match_mode"])

        ambiguous = self.call("locate", {
            "text": "示例", "url": "https://example.test/docs", "in": ["canvas"],
            "source_id": "fixture", "refresh": False})
        self.assertTrue(ambiguous["result"]["isError"])
        self.assertIn("exactly one", decode_tool(ambiguous)["error"])
        unsupported = self.call("locate", {
            "text": "示例", "in": ["wiki"], "refresh": False})
        self.assertFalse(unsupported["result"]["isError"])
        self.assertEqual(["wiki"], decode_tool(unsupported)["in"])

    def test_locate_folds_inherited_matches_for_unrelated_terms(self):
        section_id = self.document["id"]
        terms = ["视频", "agent", "code", "RAG", "公司", "3D"]
        folder_ids = {}
        for term_index, term in enumerate(terms):
            folder_id = "path-folder-%02d" % term_index
            children = [
                {"id": "path-child-%02d-%02d" % (term_index, index), "sectionId": section_id,
                 "type": "bookmark", "title": "Candidate %02d-%02d" % (term_index, index),
                 "url": "https://example.test/path/%02d/%02d" % (term_index, index)}
                for index in range(5)
            ]
            if term == "RAG":
                folder_ids[term] = folder_id + "-nested"
                nested = {"id": folder_ids[term], "sectionId": section_id, "type": "folder",
                          "title": "RAG", "children": children}
                outer_children = [nested]
            else:
                folder_ids[term] = folder_id
                outer_children = children
            self.document["items"].append({
                "id": folder_id, "sectionId": section_id, "type": "folder",
                "title": "RAG collection" if term == "RAG" else ("2D / 3D" if term == "3D" else term),
                "children": outer_children,
            })
        self.write_document()
        self.ready()
        self.sync()

        for term in terms:
            with self.subTest(term=term):
                located = decode_tool(self.call("locate", {
                    "text": term, "in": ["canvas"], "source_id": "fixture", "refresh": False}))
                folder = next(hit for hit in located["hits"]
                              if hit.get("kind") == "folder" and hit["folder_id"] == folder_ids[term])
                self.assertEqual(5, folder["count"])
                self.assertEqual(3, len(folder["sample"]))
                expected_path = (["2D / 3D"] if term == "3D" else
                                 ["RAG collection", "RAG"] if term == "RAG" else [term])
                self.assertEqual(expected_path, folder["path"])
                self.assertEqual({"matched": 5, "folders": 1, "sampled": 3}, located["coverage"]["inherited"])
                self.assertEqual(1, located["coverage"]["folders"])
                self.assertFalse(any(hit.get("kind") != "folder" and hit["why"]["fields"] == ["path"]
                                     for hit in located["hits"]))
                if any(hit.get("kind") == "bookmark" for hit in located["hits"]):
                    self.assertIn("direct hits", located["next"])
                    if term == "公司":
                        self.assertIn("top score 140 vs 60", located["next"])
                    self.assertLess(
                        next(index for index, hit in enumerate(located["hits"]) if hit.get("kind") == "bookmark"),
                        next(index for index, hit in enumerate(located["hits"]) if hit.get("kind") == "folder"))
                else:
                    self.assertIn("inherited", located["next"])
                read = decode_tool(self.call("read", {"ref": folder["ref"], "refresh": False}))
                self.assertEqual(folder_ids[term], read["items"][0]["item_id"])

        partial = decode_tool(self.call("locate", {
            "text": "3D建模", "in": ["canvas"], "source_id": "fixture", "refresh": False}))
        self.assertEqual(1, partial["coverage"]["folders"])
        self.assertEqual("3D", partial["hints"][0]["term"])
        self.assertIn("No full match", partial["next"])

        empty = decode_tool(self.call("locate", {
            "text": "bookmark-research-no-such-term", "in": ["canvas"],
            "source_id": "fixture", "refresh": False}))
        self.assertEqual(0, empty["coverage"]["matched"])
        self.assertIn("No direct or inherited matches", empty["next"])

    def test_locate_folder_id_without_query_lists_direct_children(self):
        children = [self.document["items"][0]]
        children.extend([
            {"id": "temp-three", "sectionId": self.document["id"], "type": "bookmark",
             "title": "第三项", "url": "https://example.test/three"},
            {"id": "temp-four", "sectionId": self.document["id"], "type": "bookmark",
             "title": "第四项", "url": "https://example.test/four"},
        ])
        self.document["items"] = [{"id": "temp-folder", "sectionId": self.document["id"],
            "type": "folder", "title": "研究", "children": children}]
        self.write_document()
        self.ready()
        self.sync()

        first = decode_tool(self.call("locate", {"source_id": "fixture", "folder_id": "temp-folder",
            "limit": 2, "refresh": False}))
        self.assertEqual("folder_children", first["match_mode"])
        self.assertEqual("研究", first["folder"]["title"])
        self.assertEqual(3, first["total"])
        self.assertEqual(["temp-one", "temp-three"], [hit["item_id"] for hit in first["hits"]])
        self.assertEqual(["temp-folder", "temp-folder"], [hit["parent_id"] for hit in first["hits"]])
        self.assertEqual(3, first["coverage"]["matched"])
        self.assertEqual(2, first["more"]["offset"])

        second = decode_tool(self.call("locate", {"handle": first["more"]["handle"],
            "offset": first["more"]["offset"]}))
        self.assertEqual(["temp-four"], [hit["item_id"] for hit in second["hits"]])
        child = decode_tool(self.call("read", {"ref": second["hits"][0]["ref"], "refresh": False}))
        self.assertEqual("temp-four", child["items"][0]["item_id"])

    def test_locate_metadata_only_filters_without_text_or_url(self):
        self.document["items"] = [
            {"id": "temp-note", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "带笔记的书签", "url": "https://example.test/note", "note": "内部备注"},
            {"id": "temp-tag", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "带标签的书签", "url": "https://example.test/tag",
             "tags": [{"color": "green", "text": "关注"}]},
            {"id": "temp-plain", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "普通书签", "url": "https://example.test/plain"},
        ]
        self.write_document()
        self.ready()
        self.sync()

        noted = decode_tool(self.call("locate", {
            "has_note": True, "source_id": "fixture", "refresh": False}))
        self.assertEqual("metadata", noted["match_mode"])
        self.assertEqual(["temp-note"], [hit["item_id"] for hit in noted["hits"]])
        self.assertEqual({"has_note": True}, noted["filters"])

        tagged = decode_tool(self.call("locate", {
            "tags": ["关注"], "source_id": "fixture", "refresh": False}))
        self.assertEqual(["temp-tag"], [hit["item_id"] for hit in tagged["hits"]])

        untagged = decode_tool(self.call("locate", {
            "has_tags": False, "source_id": "fixture", "refresh": False}))
        self.assertEqual(["temp-note", "temp-plain"],
                         sorted(hit["item_id"] for hit in untagged["hits"]))

        ambiguous = self.call("locate", {"source_id": "fixture", "refresh": False})
        self.assertTrue(ambiguous["result"]["isError"])

    def test_locate_package_path_imports_a_single_section_and_summarises(self):
        self.ready()
        summary = decode_tool(self.call("locate", {"package_path": str(self.section_path)}))
        self.assertEqual(1, summary["counts"]["items"])
        self.assertEqual(1, summary["counts"]["bookmarks"])
        self.assertEqual(1, len(summary["sections"]))
        self.assertEqual("A-1", summary["sections"][0]["label"])
        self.assertIn("locate(source_id=", summary["next"])

        found = decode_tool(self.call("locate", {
            "package_path": str(self.section_path), "text": "示例公司甲"}))
        self.assertGreaterEqual(found["total"], 1)
        self.assertEqual("temp-one", found["hits"][0]["item_id"])

    def test_locate_package_path_requires_an_absolute_path(self):
        self.ready()
        response = self.call("locate", {"package_path": "relative/export.json"})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("absolute", decode_tool(response)["error"])

    def test_spawn_enqueues_local_job_and_job_observes_it(self):
        self.ready()
        data = self.base / "jobdata"
        with mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(data)}):
            spawned = decode_tool(self.call("spawn", {
                "task": "fetch", "args": {"urls": ["https://example.test/a"]},
                "operation_id": "op-local"}))
            again = decode_tool(self.call("spawn", {
                "task": "fetch", "args": {"urls": ["https://example.test/a"]},
                "operation_id": "op-local"}))
            self.assertTrue(spawned["job_id"].startswith("j-"))
            self.assertEqual("queued", spawned["state"])
            self.assertEqual(spawned["job_id"], again["job_id"])

            status = decode_tool(self.call("job", {"job_id": spawned["job_id"]}))
            self.assertEqual("queued", status["job"]["state"])
            pending = decode_tool(self.call("job", {"job_id": spawned["job_id"], "action": "result"}))
            self.assertIsNone(pending["result"])
            cancelled = decode_tool(self.call("job", {"job_id": spawned["job_id"], "action": "cancel"}))
            self.assertEqual("cancelled", cancelled["job"]["state"])

        missing = self.call("spawn", {"task": "deep_research"})
        self.assertTrue(missing["result"]["isError"])

    def test_locate_exclude_junk_drops_divider_rows(self):
        self.document["items"].append({
            "id": "temp-divider", "sectionId": "temp-section-A-1", "type": "bookmark",
            "title": "───────────── - 搜索",
            "url": "https://www.bing.com/search?q=%E2%94%80%E2%94%80%E2%94%80"})
        self.write_document()
        self.ready()
        self.sync()
        everything = decode_tool(self.call("locate", {
            "text": "搜索", "source_id": "fixture", "refresh": False}))
        self.assertGreaterEqual(everything["total"], 1)
        filtered = decode_tool(self.call("locate", {
            "text": "搜索", "source_id": "fixture", "refresh": False, "exclude_junk": True}))
        self.assertEqual(0, filtered["total"])

    def test_read_folder_ref_returns_children_summary(self):
        children = [
            {"id": "temp-a", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "子项甲", "url": "https://example.test/a"},
            {"id": "temp-b", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "子项乙", "url": "https://example.test/b", "note": "乙的备注"},
        ]
        self.document["items"] = [{"id": "temp-folder", "sectionId": "temp-section-A-1",
            "type": "folder", "title": "资料", "children": children}]
        self.write_document()
        self.ready()
        self.sync()

        listing = decode_tool(self.call("locate", {
            "source_id": "fixture", "folder_id": "temp-folder", "refresh": False}))
        read = decode_tool(self.call("read", {"ref": listing["folder"]["ref"]}))
        self.assertEqual("folder_children", read["read_scope"])
        self.assertEqual(2, read["child_count"])
        self.assertEqual(["temp-a", "temp-b"], [child["item_id"] for child in read["children"]])
        self.assertEqual("乙的备注", read["children"][1]["note"])
        self.assertLess(len(json.dumps(read, ensure_ascii=False)), 4096)

    def test_read_canvas_ref_defaults_to_target_and_explicit_all_returns_section(self):
        neighbors = [
            {"id": "neighbor-%02d" % i, "type": "text", "text": "Neighbor %02d " % i + "x" * 300,
             "x": 200 + i * 120, "y": 0, "width": 100, "height": 100}
            for i in range(16)
        ]
        nodes = [{"id": "bookmark-card", "type": "file",
                  "file": "临时栏目/常规链式/A-1 demo.json",
                  "x": 0, "y": 0, "width": 100, "height": 100}, *neighbors]
        edges = [{"id": "edge-%02d" % i, "fromNode": "bookmark-card",
                  "toNode": "neighbor-%02d" % i, "toEnd": "arrow"}
                 for i in range(len(neighbors))]
        (self.package / "Board.canvas").write_text(
            json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False), encoding="utf-8")

        self.ready()
        self.sync()
        located = decode_tool(self.call("locate", {
            "text": "示例公司甲", "in": ["canvas"], "source_id": "fixture", "refresh": False}))
        ref = located["hits"][0]["ref"]

        compact = decode_tool(self.call("read", {"ref": ref, "refresh": False}))
        compact_size = len(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        self.assertLess(compact_size, 2048)
        self.assertEqual("temp-one", compact["items"][0]["item_id"])
        self.assertIn("ancestors", compact["items"][0])
        self.assertEqual("target_item_and_folder_ancestors", compact["read_scope"])
        self.assertNotIn("raw_json", compact["items"][0])
        self.assertNotIn("nodes", compact)
        self.assertNotIn("related_nodes", compact)

        full = decode_tool(self.call("read", {
            "ref": ref, "collection": "all", "refresh": False}))
        self.assertEqual(16, len(full["related_nodes"]))
        self.assertGreater(len(json.dumps(full, ensure_ascii=False)), 2048)

    def test_locate_schema_parameters_are_consumed_and_match_mode_is_consistent(self):
        """Keep the public locate schema and handler contract in lockstep.

        Each optional argument is sent through the real JSON-RPC path.  The
        response echoes filter arguments, which makes a dropped wrapper
        argument observable without reaching into private implementation
        details.  The core exports the same request-key set so schema drift
        fails at test collection instead of during a later harness review.
        """
        from locate import LOCATE_ARGUMENTS

        self.ready()
        self.sync()
        schema_arguments = set(TOOL_SCHEMAS["locate"]["properties"])
        self.assertEqual(schema_arguments, set(LOCATE_ARGUMENTS))

        base = {"text": "示例公司甲", "source_id": "fixture", "refresh": False}
        matrix = {
            "in": ["canvas"],
            "source_id": "fixture",
            "section": "temp-section-A-1",
            "folder_id": "missing-folder",
            "tags": ["blue"],
            "tag_colors": ["blue"],
            "has_note": True,
            "has_tags": False,
            "metadata_match": "any",
            "limit": 1,
            "refresh": False,
        }
        for argument, value in matrix.items():
            request_arguments = dict(base)
            request_arguments[argument] = value
            response = self.call("locate", request_arguments)
            if argument == "folder_id":
                # The fixture has no folder node.  A specific validation error
                # proves the argument reached the index instead of being
                # silently dropped by the MCP adapter.
                self.assertTrue(response["result"]["isError"], response)
                self.assertIn("Unknown folder ID", decode_tool(response)["error"])
                continue
            self.assertFalse(response["result"]["isError"], (argument, response))
            result = decode_tool(response)
            if argument == "in":
                self.assertEqual(value, result["in"])
            elif argument == "source_id":
                self.assertEqual([value], result["source_ids"])
            elif argument == "limit":
                self.assertLessEqual(len(result["hits"]), value)
            elif argument == "refresh":
                # refresh is an execution control; successful dispatch is its
                # observable contract and the response intentionally omits it.
                self.assertIn("source_ids", result)
            else:
                self.assertEqual(value, result["filters"].get(argument), argument)

            for hit in result["hits"]:
                self.assertEqual(result["match_mode"], hit["why"]["match_mode"])

        url_result = decode_tool(self.call("locate", {
            "url": "https://example.test/docs", "in": ["canvas"],
            "source_id": "fixture", "refresh": False,
        }))
        self.assertEqual("https://example.test/docs", url_result["url"])
        self.assertEqual("exact", url_result["match_mode"])
        for hit in url_result["hits"]:
            self.assertEqual("exact", hit["why"]["match_mode"])

    def test_locate_continuation_returns_more_handle_and_next_page(self):
        """A bounded locate page must expose a usable continuation cursor."""
        self.ready()
        self.sync()
        for index in range(3):
            self.document["items"].append({
                "id": f"needle-{index}", "sectionId": "temp-section-A-1",
                "type": "bookmark", "title": f"Needle card {index}",
                "url": f"https://example.test/needle-{index}",
            })
        self.write_document()
        self.sync()

        first = decode_tool(self.call("locate", {
            "text": "Needle", "in": ["canvas"], "source_id": "fixture",
            "limit": 1, "refresh": False,
        }))
        self.assertEqual(3, first["total"])
        self.assertEqual(1, len(first["hits"]))
        self.assertIn("more", first)
        self.assertEqual({"handle", "offset", "total"}, set(first["more"]))
        self.assertEqual(1, first["more"]["offset"])
        self.assertEqual(3, first["more"]["total"])
        self.assertEqual({"tool", "handle", "offset", "reason", "message"}, set(first["next"]))
        self.assertEqual("locate", first["next"]["tool"])
        first_ref = first["hits"][0]["ref"]

        second = decode_tool(self.call("locate", {
            "handle": first["more"]["handle"], "offset": first["more"]["offset"],
        }))
        self.assertEqual(first["total"], second["total"])
        self.assertEqual(1, len(second["hits"]))
        self.assertNotEqual(first_ref, second["hits"][0]["ref"])
        self.assertEqual(first["match_mode"], second["match_mode"])

        stale = self.call("locate", {"handle": "lh-does-not-exist", "offset": 1})
        self.assertTrue(stale["result"]["isError"])
        self.assertIn("unknown locate continuation handle", decode_tool(stale)["error"])


if __name__ == "__main__":
    unittest.main()
