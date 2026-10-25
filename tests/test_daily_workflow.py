"""Exercise the default tools from read sources to retained knowledge and API runs."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive
from mcp_server import StdioMcpServer
from research import ResearchSessions
from research_services import ResearchServices
from routing import ResearchRouting
from settings import Settings
from wiki import WikiStore


class DailyWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-daily-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data"),
            "OPENAI_API_KEY": "synthetic-test-key", "BOOKMARK_RESEARCH_TOOL_SCOPE": ""})
        environment.start()
        self.addCleanup(environment.stop)
        # Test the saved default, rather than an environment allowlist override.
        os.environ.pop("BOOKMARK_RESEARCH_TOOL_SCOPE")
        self.settings = Settings(self.root / "settings.json")
        self.server = StdioMcpServer(self.root / "index.sqlite3", settings=self.settings, stderr=io.StringIO())
        self.addCleanup(self.server.close)
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "daily-test", "version": "1"}}})
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name, arguments):
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": name, "arguments": arguments}})
        self.assertNotIn("error", response, response)
        self.assertFalse(response["result"]["isError"], response)
        return response["result"]["structuredContent"]

    @staticmethod
    def page(text="Aurora documents reusable sessions."):
        return {"title": "Aurora sessions", "kind": "topic", "links": [],
                "sections": [{"heading": "Reuse", "text": text,
                              "citations": [{"source_id": "docs", "quote": "Reusable sessions are supported."}]}],
                "review": {"method": "model", "reviewer": "Fixture reviewer",
                           "note": "Reviewed the supplied synthetic source and its exact quotation."}}

    def test_default_catalog_contains_complete_daily_paths(self):
        listing = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = {row["name"] for row in listing["result"]["tools"]}
        self.assertEqual(set(Settings.QUICK_TOOLS), names)
        self.assertNotIn("research_pack", names)
        self.assertNotIn("research_record", names)
        self.assertNotIn("research_route", names)
        self.assertFalse((self.root / "index.sqlite3").exists())
        self.assertFalse(self.settings.path.exists())

    def test_host_sources_are_saved_and_reused_without_a_canvas_or_network(self):
        result = self.call("wiki_write", {"page_id": "aurora", "page": self.page(), "change_note": "Save findings",
            "sources": [{"id": "docs", "url": "https://example.test/docs",
                         "text": "Reusable sessions are supported."}]})
        self.assertEqual(1, result["revision"])
        read = self.call("wiki_get", {"page_id": "aurora"})
        self.assertEqual("valid", read["validation"]["integrity"])
        self.assertEqual("Reusable sessions are supported.", read["evidence"][0]["citations"][0]["quote"])
        plan = self.call("plan_research", {"question": "Aurora", "include_archive": False})
        self.assertEqual("aurora", plan["wiki"][0]["page_id"])
        self.assertIsNone(plan["source_id"])
        self.assertNotIn("route", plan)
        self.assertIsNone(self.server._providers)
        self.assertEqual("completed", self.server._research().status()["sessions"][0]["status"])

    def test_capture_text_is_reused_and_bad_quotes_write_no_research_state(self):
        archive = SourceArchive(self.settings.load()["archive"]["directory"])
        text = "Reusable sessions are supported. " * 30
        saved = archive.save({"provider": "exa", "tool": "fixture", "urls": ["https://example.test/docs"],
            "request_arguments": {}, "retrieved_at": "2026-10-25T00:00:00Z", "requested_max_characters": 12000,
            "result": {"structuredContent": {"url": "https://example.test/docs", "text": text}}})
        source = {"id": "docs", "url": "https://example.test/docs", "capture_id": saved["capture_id"]}
        page = self.page()
        page["sections"][0]["citations"][0]["quote"] = "This text is absent."
        wiki = self.server._wiki()
        with self.assertRaisesRegex(ValueError, "Quote is absent"):
            wiki.write("aurora", page, "Invalid quote", sources=[source])
        self.assertFalse(wiki.research.directory.exists())
        self.call("wiki_write", {"page_id": "aurora", "page": self.page(), "change_note": "Reuse capture",
                                 "sources": [source]})
        read = self.call("wiki_get", {"page_id": "aurora"})
        self.assertEqual("2026-10-25T00:00:00Z", read["evidence"][0]["citations"][0]["retrieved_at"])
        self.assertIsNone(self.server._providers)

    def test_preflight_keeps_short_names_and_canvas_text(self):
        package = self.root / "package"
        package.mkdir()
        (package / "临时栏目").mkdir()
        (package / "临时栏目" / "tools.json").write_text(json.dumps({
            "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "temporary",
            "id": "tools", "label": "Tools", "title": "Tools", "items": [
                {"id": "uv", "type": "bookmark", "title": "uv", "url": "https://example.test/uv"},
                {"id": "go", "type": "bookmark", "title": "Go", "url": "https://example.test/go"}]}))
        (package / "context.canvas").write_text(json.dumps({"nodes": [
            {"id": "uv", "type": "file", "file": "临时栏目/tools.json", "x": 0, "y": 0, "width": 200, "height": 100},
            {"id": "note", "type": "text", "text": "StoredNebulaTopic", "x": 250, "y": 0, "width": 200, "height": 100}],
            "edges": [{"id": "edge", "fromNode": "uv", "toNode": "note", "label": "Go"}]}))
        source = self.call("sync_package", {"package_path": str(package), "mode": "snapshot"})["source_id"]
        for question in ("uv", "Go", "StoredNebulaTopic"):
            plan = self.call("plan_research", {"source_id": source, "question": question,
                                              "include_wiki": False, "include_archive": False})
            self.assertTrue(plan["urls"] or plan["canvas_matches"], plan)

    def test_invalid_direct_writes_leave_no_retained_tasks(self):
        wiki = self.server._wiki()
        source = {"id": "docs", "url": "https://example.test/docs",
                  "text": "Reusable sessions are supported."}
        for failure in ("url", "link", "version", "publication"):
            with self.subTest(failure=failure):
                page, supplied, arguments = self.page(), dict(source), {}
                if failure == "url":
                    supplied["url"] = "not a URL"
                elif failure == "link":
                    page["links"] = [{"page_id": "absent", "relation": "depends on"}]
                elif failure == "version":
                    arguments["reviewed_input_version"] = "wrong-version"
                if failure == "publication":
                    with patch.object(wiki, "_write_page", side_effect=ValueError("Simulated publication failure")):
                        with self.assertRaises(ValueError):
                            wiki.write("aurora", page, "Save", sources=[supplied], **arguments)
                else:
                    with self.assertRaises(ValueError):
                        wiki.write("aurora", page, "Save", sources=[supplied], **arguments)
                self.assertEqual([], wiki.research.status()["sessions"])
                self.assertFalse((wiki.directory / "index.json").exists())

    def test_failed_write_does_not_invalidate_previously_saved_sources(self):
        from datetime import datetime, timedelta, timezone
        wiki = self.server._wiki()
        now = datetime.now(timezone.utc)
        source = {"id": "docs", "url": "https://example.test/docs",
                  "text": "Reusable sessions are supported.", "retrieved_at": now.isoformat()}
        wiki.write("aurora", self.page(), "First version", sources=[source])
        before = wiki.get("aurora")["validation"]
        changed = {**source, "text": "Reusable sessions are supported. Updated findings.",
                   "retrieved_at": (now + timedelta(seconds=1)).isoformat()}
        with patch.object(wiki, "_write_page", side_effect=OSError("Simulated publication failure")):
            with self.assertRaises(OSError):
                wiki.write("aurora-new", self.page(), "Uncommitted version", sources=[changed])
        self.assertEqual(before, wiki.get("aurora")["validation"])
        self.assertEqual(1, len(wiki.research.status()["sessions"]))

    def test_long_capture_tail_and_whitespace_sections_are_retained(self):
        quote = "Reusable sessions are supported."
        text = "Long document introduction. " * 5000 + quote
        archive = SourceArchive(self.settings.load()["archive"]["directory"])
        saved = archive.save({"provider": "exa", "tool": "fixture", "urls": ["https://example.test/docs"],
            "request_arguments": {}, "retrieved_at": "2026-10-25T00:00:00Z", "requested_max_characters": 200000,
            "result": {"structuredContent": {"url": "https://example.test/docs", "text": text}}})
        result = self.call("wiki_write", {"page_id": "aurora", "page": self.page("Start." + " " * 8000 + "End."),
            "change_note": "Retain tail evidence", "sources": [{"id": "docs", "url": "https://example.test/docs",
            "capture_id": saved["capture_id"]}]})
        read = self.call("wiki_get", {"page_id": result["page_id"]})
        self.assertEqual("valid", read["validation"]["integrity"])
        self.assertEqual(quote, read["evidence"][0]["citations"][0]["quote"])

    def test_canvas_preflight_merges_term_hits_and_reports_budget_truncation(self):
        from research_plan import ResearchPlan
        index = Mock()
        index.plan_scope.return_value = {"cards": [], "urls": [], "terms": ["Nebula", "topic"], "truncated": False}
        index._canvas_matches.return_value = [
            {"kind": "text", "canvas_path": "c.canvas", "node_id": "n1", "text": "Nebula topic", "target": term}
            for term in ("Nebula", "topic")]
        plan = ResearchPlan(index=index, settings=self.settings)
        result = plan.build("source", "Nebula topic", include_wiki=False, include_archive=False)
        self.assertEqual(1, len(result["canvas_matches"]))
        self.assertEqual(["Nebula", "topic"], result["canvas_matches"][0]["matched_terms"])
        self.assertFalse(result["canvas_matches_truncated"])
        self.settings.update({"plan": {"max_characters": 1000}})
        index._canvas_matches.return_value = [{"kind": "text", "canvas_path": "c.canvas", "node_id": "n" + str(i),
                                               "text": "x" * 1200, "target": "Nebula"} for i in range(3)]
        result = plan.build("source", "Nebula", include_wiki=False, include_archive=False)
        self.assertTrue(result["canvas_matches_truncated"])
        self.assertTrue(result["preflight_budget"]["truncated"])
        oversized = plan.build(question="x" * 1800, include_wiki=False, include_archive=False)
        self.assertTrue(oversized["preflight_budget"]["truncated"])

    def test_standalone_api_run_is_replayed_and_retains_report_without_a_session(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        transport = Mock()
        transport.request.return_value = {"id": "resp_fixture", "status": "queued", "output": []}
        services = ResearchServices(settings=self.settings, research_sessions=self.server._research(), transport=transport)
        self.server._research_services = services
        arguments = {"operation_id": "daily-api", "input": "Compare public source capabilities.",
                     "options": {"model": "gpt-5.6-sol"}}
        prepared = self.call("research_service_prepare", {key: value for key, value in arguments.items() if key != "operation_id"})
        self.assertEqual("gpt-5.6-sol", prepared["payload"]["model"])
        first = self.call("research_service_start", arguments)
        replay = self.call("research_service_start", arguments)
        self.assertEqual(first["external_id"], replay["external_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(1, transport.request.call_count)
        transport.request.return_value = {"id": "resp_fixture", "status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Reviewed report.", "annotations": []}]}]}
        result = self.call("research_service_result", {"external_id": first["external_id"], "refresh": True})
        self.assertIn("Reviewed report.", json.dumps(result))
        self.assertFalse(services.sessions.directory.exists())

    def test_native_codex_search_names_and_plugin_search_are_distinguished(self):
        for tool in ("web.run", "web__run", "functions.web__run"):
            route = ResearchRouting(self.settings).route(host="codex", observed_tools=[tool])
            self.assertEqual(tool, route["host_search"]["tool"])
        route = ResearchRouting(self.settings).route(host="codex", observed_tools=["mcp__other__web_search"])
        self.assertFalse(route["host_search"]["available"])

    def test_research_draft_respects_write_limits_and_keeps_remaining_ids(self):
        state = {"research_id": "r-0123456789abcdef", "brief": "Fixture", "questions": [
            {"id": "q1", "question": "Question\nwith a newline?"}]}
        drafts = [{"claim_id": "c%d" % i, "question_id": "q1", "statement": "S" * 1100} for i in range(25)]
        draft = ResearchSessions._wiki_page(drafts, state)
        self.assertTrue(draft["truncated"])
        self.assertEqual(["c24"], draft["remaining_claim_ids"])
        draft["page"]["review"] = self.page()["review"]
        self.server._wiki()._page(draft["page"])
        self.assertNotIn("Ask the user", draft["instruction"])


if __name__ == "__main__":
    unittest.main()
